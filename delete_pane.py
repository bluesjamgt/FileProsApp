# folder_pane.py
# version: 2.2.0
__version__ = "2.2.0"

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from tkinterdnd2 import DND_FILES
import queue

from utils import ensure_tk_with_dnd, natural_sort_key, create_scrollable_treeview

class FolderOrganizerPane(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.pane_name = "folder_pane"
        self.folder_list_to_process = []

        self.worker_thread = None
        self.ui_queue = queue.Queue()
        self.cancel_event = threading.Event()

        self.var_add_string = tk.StringVar(value="")
        self.var_add_position = tk.StringVar(value="prefix")
        self.var_search_string = tk.StringVar(value="")
        self.var_search_mode = tk.StringVar(value="delete")
        self.var_replace_string = tk.StringVar(value="")

        self._build_ui()
        self._load_config()
        self.after(100, self._process_ui_queue)

    def _build_ui(self):
        main_frame = ttk.LabelFrame(self, text=f"資料夾整理 v{__version__}")
        main_frame.pack(fill="both", expand=True, padx=5, pady=5)

        frame_naming = tk.LabelFrame(main_frame, text="命名設定")
        frame_naming.pack(fill="x", padx=10, pady=5)
        
        tk.Label(frame_naming, text="新增字串:").grid(row=0, column=0, padx=5, pady=2, sticky="w")
        tk.Entry(frame_naming, textvariable=self.var_add_string, width=20).grid(row=0, column=1)
        tk.Radiobutton(frame_naming, text="前置", variable=self.var_add_position, value="prefix", command=self.update_folder_preview).grid(row=0, column=2, padx=5)
        tk.Radiobutton(frame_naming, text="後置", variable=self.var_add_position, value="suffix", command=self.update_folder_preview).grid(row=0, column=3, padx=5)
        
        tk.Label(frame_naming, text="搜尋字串:").grid(row=1, column=0, padx=5, pady=2, sticky="w")
        tk.Entry(frame_naming, textvariable=self.var_search_string, width=20).grid(row=1, column=1)
        tk.Radiobutton(frame_naming, text="刪除", variable=self.var_search_mode, value="delete", command=self.update_folder_preview).grid(row=1, column=2, padx=5)
        tk.Radiobutton(frame_naming, text="取代為", variable=self.var_search_mode, value="replace", command=self.update_folder_preview).grid(row=1, column=3, padx=5)
        tk.Entry(frame_naming, textvariable=self.var_replace_string, width=20).grid(row=1, column=4, padx=5)
        
        ttk.Button(frame_naming, text="儲存設定", command=self._save_config).grid(row=0, column=5, rowspan=2, padx=20, sticky="e")
        frame_naming.columnconfigure(5, weight=1)

        for var in [self.var_add_string, self.var_search_string, self.var_replace_string]:
            var.trace_add("write", lambda *args: [self.update_folder_preview(), self.update_folder_button_state()])

        frame_preview = tk.LabelFrame(main_frame, text="資料夾預覽區 (將會處理所有子目錄)")
        frame_preview.pack(fill="both", expand=True, padx=10, pady=(5, 0))
        
        tree_container, self.folder_tree = create_scrollable_treeview(frame_preview)
        tree_container.pack(fill="both", expand=True)

        columns = ("original", "new")
        self.folder_tree.configure(columns=columns, show="headings")
        self.folder_tree.heading("original", text="原資料夾名稱"); self.folder_tree.heading("new", text="新資料夾名稱")
        self.folder_tree.column("original", width=350); self.folder_tree.column("new", width=350)

        exec_frame = ttk.Frame(main_frame)
        exec_frame.pack(fill="x", padx=10, pady=10)
        exec_frame.columnconfigure(0, weight=1)
        self.pbar = ttk.Progressbar(exec_frame)
        self.pbar.grid(row=0, column=0, sticky="ew")
        self.btn_execute = ttk.Button(exec_frame, text="開始處理", command=self.execute_folder_rename, state="disabled")
        self.btn_execute.grid(row=0, column=1, padx=(10, 0))
        self.btn_cancel = ttk.Button(exec_frame, text="取消", command=self._on_cancel, state="disabled")
        self.btn_cancel.grid(row=0, column=2, padx=(5, 0))
        
    def _get_settings_as_dict(self):
        return {
            "add_string": self.var_add_string.get(), "add_position": self.var_add_position.get(),
            "search_string": self.var_search_string.get(), "search_mode": self.var_search_mode.get(),
            "replace_string": self.var_replace_string.get(),
        }

    def _apply_settings_from_dict(self, settings_dict):
        for key, value in settings_dict.items():
            var_name = f"var_{key}"
            if hasattr(self, var_name):
                try: getattr(self, var_name).set(value)
                except tk.TclError: pass
        self.update_folder_preview()
        
    def _load_config(self):
        all_configs = self.app.load_app_config()
        pane_settings = all_configs.get(self.pane_name, self._get_settings_as_dict())
        self._apply_settings_from_dict(pane_settings)
    
    def _save_config(self):
        all_configs = self.app.load_app_config()
        all_configs[self.pane_name] = self._get_settings_as_dict()
        self.app.save_app_config(all_configs)
        self.app.log(f"FolderPane: 設定已儲存。")

    def receive_update(self, data_state):
        self.update_folder_preview(data_state)
        self.update_folder_button_state()

    def update_folder_preview(self, data_state=None):
        if data_state is None: data_state = self.app.data_state if hasattr(self.app, 'data_state') else None
        if not data_state or not data_state["root_folder"]:
            self.folder_tree.delete(*self.folder_tree.get_children()); return
            
        self.folder_tree.delete(*self.folder_tree.get_children())
        self.folder_list_to_process.clear()
        
        root_folder = data_state["root_folder"]
        all_folders_to_preview = sorted(data_state["folders"], key=lambda p: natural_sort_key(os.path.basename(p)))

        for folder_path in all_folders_to_preview:
            folder_name = os.path.basename(folder_path)
            new_name = folder_name
            if self.var_add_string.get():
                if self.var_add_position.get() == "prefix": new_name = f"{self.var_add_string.get()}{new_name}"
                else: new_name = f"{new_name}{self.var_add_string.get()}"
            if self.var_search_string.get():
                if self.var_search_mode.get() == "delete": new_name = new_name.replace(self.var_search_string.get(), "")
                elif self.var_search_mode.get() == "replace": new_name = new_name.replace(self.var_search_string.get(), self.var_replace_string.get())
            
            relative_path = os.path.relpath(folder_path, data_state["root_folder"])
            self.folder_tree.insert("", "end", values=(relative_path, new_name))

            if folder_name != new_name:
                parent_dir = os.path.dirname(folder_path)
                self.folder_list_to_process.append((folder_path, os.path.join(parent_dir, new_name)))

    def update_folder_button_state(self):
        add_text = self.var_add_string.get().strip()
        search_text = self.var_search_string.get().strip()
        state = "normal" if add_text or search_text else "disabled"
        self.btn_execute.config(state=state)
            
    def execute_folder_rename(self):
        if not self.folder_list_to_process: messagebox.showwarning("注意", "沒有可重新命名的資料夾。"); return
        
        self.btn_execute.config(state="disabled"); self.btn_cancel.config(state="normal")
        self.pbar['value'] = 0; self.cancel_event.clear()

        self.worker_thread = FolderOrganizerWorker(self.folder_list_to_process.copy(), self.ui_queue, self.cancel_event, self.app)
        self.worker_thread.start()

    def _on_cancel(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.app.log("[資料夾整理] 正在傳送取消訊號...")
            self.cancel_event.set()
            self.btn_cancel.config(state="disabled")

    def _process_ui_queue(self):
        try:
            while not self.ui_queue.empty():
                kind, payload = self.ui_queue.get_nowait()
                if kind == "progress": self.pbar['value'] = payload
                elif kind == "done":
                    status_text = "任務已取消" if payload == "cancel" else "任務已完成"
                    self.app.update_status(f"資料夾整理：{status_text}")
                    self.btn_execute.config(state="normal"); self.btn_cancel.config(state="disabled")
        finally: self.after(100, self._process_ui_queue)

class FolderOrganizerWorker(threading.Thread):
    def __init__(self, folder_list, ui_queue, cancel_event, app):
        super().__init__(daemon=True)
        self.folder_list = folder_list
        self.ui_queue = ui_queue
        self.cancel_event = cancel_event
        self.app = app

    def run(self):
        total_folders = len(self.folder_list)
        changed_count = 0
        
        # Sort reverse by length is CRITICAL for folder renaming to avoid path not found errors
        sorted_list = sorted(self.folder_list, key=lambda x: len(x[0]), reverse=True)
        
        for i, (old_path, new_path) in enumerate(sorted_list):
            if self.cancel_event.is_set(): break
            try:
                if os.path.exists(new_path):
                    self.app.log(f"❌ 無法重新命名: 目標 {os.path.basename(new_path)} 已存在。")
                    continue
                os.rename(old_path, new_path)
                self.app.log(f"✅ 重新命名資料夾: {os.path.basename(old_path)} → {os.path.basename(new_path)}")
                changed_count += 1
            except Exception as e:
                self.app.log(f"❌ 重新命名失敗 {os.path.basename(old_path)}: {e}")
            
            progress = int((i + 1) * 100 / total_folders)
            self.ui_queue.put(("progress", progress))

        final_status = "cancel" if self.cancel_event.is_set() else "ok"
        if final_status == "ok":
            self.app.log(f"✔ 資料夾整理完成：共重新命名 {changed_count} 個資料夾。")
            if hasattr(self.app, '_scan_folder'): threading.Thread(target=self.app._scan_folder, daemon=True).start()
        
        self.ui_queue.put(("done", final_status))

if __name__ == '__main__':
    root = ensure_tk_with_dnd()
    root.title("Folder Organizer Pane - Standalone Test")
    root.geometry("760x600")

    class MockApp:
        def __init__(self):
            self.root = root; self.app_dir = '.'
            self.data_state = {"root_folder": "", "folders": []}
            self.pane_instance = None
        def log(self, msg): print(f"[MOCK LOG] {msg}")
        def update_status(self, text): print(f"[MOCK STATUS] {text}")
        def load_app_config(self): print(f"[MOCK] Loading master config..."); return {}
        def save_app_config(self, cfg): print(f"[MOCK] Saving master config: {cfg}")
        def _on_drop(self, event):
            folder = event.data.strip("{}")
            if os.path.isdir(folder):
                self.data_state["root_folder"] = folder
                threading.Thread(target=self._scan_folder, daemon=True).start()
        def _scan_folder(self):
            self.data_state["folders"] = []
            root_folder = self.data_state["root_folder"]
            for r, d_list, _ in os.walk(root_folder):
                for d in d_list: self.data_state["folders"].append(os.path.join(r, d))
            self.root.after(0, self._notify_panes)
        def _notify_panes(self):
            if self.pane_instance: self.pane_instance.receive_update(self.data_state)
            
    mock_app = MockApp()
    frame_drag = tk.LabelFrame(root, text="[MOCK] Drop Zone for Standalone Test")
    frame_drag.pack(fill="x", padx=10, pady=10)
    label_drag = tk.Label(frame_drag, text="📂 Drop a folder here to test", height=4)
    label_drag.pack(fill="x", expand=True)
    try:
        label_drag.drop_target_register(DND_FILES)
        label_drag.dnd_bind("<<Drop>>", mock_app._on_drop)
    except: pass

    pane = FolderOrganizerPane(root, mock_app)
    pane.pack(fill="both", expand=True)
    mock_app.pane_instance = pane
    
    root.mainloop()