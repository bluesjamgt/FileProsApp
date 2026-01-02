# delete_pane.py
# Compatible with main.py v4.x
# version: 2.0.1
__version__ = "2.0.1"

import os
import sys
import json
import stat
import time
import threading
import queue
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime
from tkinterdnd2 import DND_FILES

# 嘗試載入 utils，若失敗則使用備援定義 (確保獨立執行與主程式的一致性)
try:
    from utils import format_size, ensure_tk_with_dnd
except ImportError:
    def format_size(size_bytes):
        if size_bytes == 0: return "0 B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(__import__("math").floor(__import__("math").log(size_bytes, 1024)))
        p = __import__("math").pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"
    def ensure_tk_with_dnd():
        try: from tkinterdnd2 import TkinterDND; return TkinterDND.Tk()
        except ImportError: return tk.Tk()

CONFIG_NAME = "DeleteFolderGUI.config.json"

def is_windows() -> bool: return os.name == "nt"
def safe_path(path: str) -> str: return os.path.abspath(os.path.expanduser(path or "")).rstrip("\\/")

def open_in_explorer(path: str):
    if not path or not os.path.exists(path): return
    try:
        if is_windows(): os.startfile(path)
        elif sys.platform == "darwin": os.system(f'open "{path}"')
        else: os.system(f'xdg-open "{path}"')
    except Exception as e: print(f"Error opening path {path}: {e}")

def is_dangerous_root(path: str) -> bool:
    p = safe_path(path)
    if not p: return True
    if is_windows() and len(p) <= 3 and p.endswith(":\\"): return True
    if not is_windows() and p == "/": return True
    try:
        if os.path.normcase(p) == os.path.normcase(os.path.expanduser("~")): return True
    except Exception: pass
    return False

class DeleteWorker(threading.Thread):
    def __init__(self, target_dir: str, files_to_delete: list, dirs_to_delete: list, total_size: int, log_file: str, ui_queue: queue.Queue, cancel_event: threading.Event):
        super().__init__(daemon=True)
        self.target = os.path.normpath(target_dir)
        self.files_to_delete = files_to_delete
        self.dirs_to_delete = dirs_to_delete
        self.total_size = total_size
        self.log_file = log_file
        self.ui_queue = ui_queue
        self.cancel_event = cancel_event
        self.log_batch = []
        self.last_update_time = 0

    def _send_log_batch(self, force=False):
        if force or len(self.log_batch) >= 100:
            if self.log_batch:
                self.ui_queue.put(("log_batch", self.log_batch)); self.log_batch = []

    def _update_status(self, current, total, start_time):
        now = time.time()
        if now - self.last_update_time > 0.2:
            self.last_update_time = now
            progress = int(current * 100 / total) if total > 0 else 0
            elapsed = now - start_time
            speed = current / elapsed if elapsed > 0 else 0
            remaining_items = total - current
            eta = remaining_items / speed if speed > 0 else 0
            eta_str = f"{int(eta // 60)} 分 {int(eta % 60)} 秒" if eta > 60 else f"{eta:.1f} 秒"
            status_text = f"刪除中... (剩餘 {remaining_items:,} 個項目, 預計 {eta_str})"
            self.ui_queue.put(("progress", progress)); self.ui_queue.put(("status", status_text))

    def _log(self, msg: str, batch=True):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        try:
            with open(self.log_file, "a", encoding="utf-8") as f: f.write(line + "\n")
        except Exception: pass
        if batch: self.log_batch.append(line); self._send_log_batch()
        else: self.ui_queue.put(("log", line))

    def run(self):
        start_time = time.time()
        try:
            total_items = len(self.files_to_delete) + len(self.dirs_to_delete) + 1
            completed_items = 0
            deletion_start_time = time.time()

            for f in self.files_to_delete:
                if self.cancel_event.is_set(): break
                try: os.chmod(f, stat.S_IWRITE); os.remove(f); self._log(f"檔案已刪除: {f}")
                except Exception as e: self._log(f"刪除檔案失敗: {f} -> {e}")
                finally: completed_items += 1; self._update_status(completed_items, total_items, deletion_start_time)
            
            for d in sorted(self.dirs_to_delete, key=lambda p: -len(p)):
                if self.cancel_event.is_set(): break
                try: os.rmdir(d); self._log(f"資料夾已刪除: {d}")
                except Exception as e: self._log(f"刪除資料夾失敗: {d} -> {e}")
                finally: completed_items += 1; self._update_status(completed_items, total_items, deletion_start_time)

            if not self.cancel_event.is_set():
                try: os.rmdir(self.target); self._log(f"根目錄已刪除: {self.target}")
                except Exception as e: self._log(f"刪除根目錄失敗: {self.target} -> {e}")
                finally: completed_items += 1
            
            self._send_log_batch(force=True); self.ui_queue.put(("progress", 100))
            duration = time.time() - start_time
            
            summary = (f"總共刪除: {completed_items:,} / {total_items:,} 個項目\n"
                       f"釋放空間: {format_size(self.total_size)}\n"
                       f"總花費時間: {duration:.2f} 秒")
            self.ui_queue.put(("summary", summary))

            if self.cancel_event.is_set(): self._log("使用者已取消刪除操作。", batch=False); self.ui_queue.put(("done", "cancel"))
            else: self._log(f"✅ 完成。", batch=False); self.ui_queue.put(("done", "ok"))
        except Exception as e:
            self._log(f"❌ 執行緒發生未預期的嚴重錯誤：{e}", batch=False); self.ui_queue.put(("done", "error"))

class DeletePane(ttk.Frame):
    def __init__(self, parent, app, app_dir: str):
        super().__init__(parent)
        self.app, self.app_dir = app, app_dir
        self.config_path = os.path.join(self.app_dir, CONFIG_NAME)
        self.ui_queue, self.cancel_event = queue.Queue(), threading.Event()
        self.worker_thread, self.last_log_file, self.last_summary = None, "", ""
        self._setup_ui_variables()
        self._build_ui()
        self._load_config()
        self.after(100, self._process_ui_queue)

    def _setup_ui_variables(self):
        self.var_target_dir_text = tk.StringVar(value="目標：尚未從中央拖曳區載入資料夾")
        self.var_log_dir = tk.StringVar()
        self.var_confirm_delete = tk.BooleanVar(value=True)
        self.var_status_text = tk.StringVar(value="狀態：待機")

    def _build_ui(self):
        main_frame = ttk.LabelFrame(self, text=f"資料夾刪除 v{__version__}")
        main_frame.pack(fill="both", expand=True, padx=5, pady=5)
        main_frame.rowconfigure(4, weight=1); main_frame.columnconfigure(0, weight=1)

        target_frame = ttk.Frame(main_frame)
        target_frame.grid(row=0, column=0, columnspan=4, sticky="ew", padx=10, pady=5)
        target_frame.columnconfigure(0, weight=1)
        ttk.Label(target_frame, textvariable=self.var_target_dir_text, wraplength=500, justify="left").grid(row=0, column=0, sticky="w")
        
        log_frame = ttk.Frame(main_frame)
        log_frame.grid(row=1, column=0, columnspan=4, sticky="ew", padx=10, pady=5)
        log_frame.columnconfigure(1, weight=1)
        ttk.Label(log_frame, text="Log 位置：").grid(row=0, column=0)
        ttk.Entry(log_frame, textvariable=self.var_log_dir).grid(row=0, column=1, sticky="ew")
        ttk.Button(log_frame, text="瀏覽…", command=self.on_browse_log).grid(row=0, column=2, padx=(5,0))
        ttk.Button(log_frame, text="開啟Log資料夾", command=self.on_open_logdir).grid(row=0, column=3, padx=(5,0))

        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=2, column=0, columnspan=4, sticky="ew", padx=10, pady=5)
        ttk.Checkbutton(control_frame, text="刪除前詢問確認", variable=self.var_confirm_delete).pack(side="left")
        self.btn_preview = ttk.Button(control_frame, text="預覽統計", command=self.on_preview)
        self.btn_preview.pack(side="left", padx=10)
        self.btn_cancel = ttk.Button(control_frame, text="取消", command=self.on_cancel, state="disabled")
        self.btn_cancel.pack(side="right")
        self.btn_delete = ttk.Button(control_frame, text="⚠ 刪除", command=self.on_delete)
        self.btn_delete.pack(side="right", padx=5)

        status_frame = ttk.Frame(main_frame)
        status_frame.grid(row=3, column=0, columnspan=4, sticky="ew", padx=10, pady=5)
        status_frame.columnconfigure(0, weight=1)
        ttk.Label(status_frame, textvariable=self.var_status_text).grid(row=0, column=0, sticky="w")
        self.pbar = ttk.Progressbar(status_frame, orient="horizontal", mode="determinate")
        self.pbar.grid(row=1, column=0, sticky="ew")
        
        console_frame = ttk.LabelFrame(main_frame, text="日誌")
        console_frame.grid(row=4, column=0, columnspan=4, sticky="nsew", padx=10, pady=5)
        console_frame.rowconfigure(0, weight=1); console_frame.columnconfigure(0, weight=1)
        self.txt_console = tk.Text(console_frame, height=10, wrap="none")
        self.txt_console.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(console_frame, orient="vertical", command=self.txt_console.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.txt_console.config(yscrollcommand=scrollbar.set)

    def receive_update(self, data_state):
        target_folder = data_state.get("root_folder")
        if target_folder: self.var_target_dir_text.set(f"目標：{target_folder}")
        else: self.var_target_dir_text.set("目標：尚未從中央拖曳區載入資料夾")
        self.txt_console.delete("1.0", "end"); self.pbar['value'] = 0

    def on_browse_log(self):
        p = filedialog.askdirectory(title="選擇 Log 儲存資料夾"); 
        if p: self.var_log_dir.set(p)
    def on_open_logdir(self):
        p = safe_path(self.var_log_dir.get())
        if p: os.makedirs(p, exist_ok=True); open_in_explorer(p)

    def on_preview(self):
        ds = self.app.data_state
        target = ds.get("root_folder")
        if not target or not os.path.isdir(target): messagebox.showwarning("注意", "請先從中央拖曳區載入一個有效的目標資料夾。"); return
        result = f"資料夾：{target}\n檔案：{len(ds.get('all_files',[])):,}\n子資料夾：{len(ds.get('folders',[])):,}\n總大小：{format_size(ds.get('total_size', 0))}"
        messagebox.showinfo("預覽統計 (來自中央數據)", result)

    def on_delete(self):
        ds = self.app.data_state
        target, files, folders, total_size = ds.get("root_folder"), ds.get("all_files",[]), ds.get("folders",[]), ds.get("total_size", 0)
        
        if not target or not os.path.isdir(target): messagebox.showwarning("注意", "請先從中央拖曳區載入一個目標資料夾。"); return
        if is_dangerous_root(target): messagebox.showerror("阻擋", "為避免災難，禁止刪除磁碟根目錄/家目錄。"); return
        if self.var_confirm_delete.get() and not messagebox.askyesno("確認刪除", f"真的要永久刪除？\n{target}\n\n總計 {len(files):,} 個檔案, {len(folders):,} 個資料夾\n大小 {format_size(total_size)}"): return

        self.last_summary = ""; self.txt_console.delete("1.0", "end"); self.pbar["value"] = 0
        self.var_status_text.set("狀態：刪除中…"); self.btn_delete.config(state="disabled")
        self.btn_preview.config(state="disabled"); self.btn_cancel.config(state="normal")
        self.cancel_event.clear(); logf = self._get_new_log_filepath()
        self._append_console(f"=== 刪除開始：{target} ===\n（Log 檔：{logf}）\n")
        self.worker_thread = DeleteWorker(target, files, folders, total_size, logf, self.ui_queue, self.cancel_event); self.worker_thread.start()
        
    def on_cancel(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.cancel_event.set(); self.var_status_text.set("狀態：嘗試取消…")
    def on_open_last_log(self):
        if self.last_log_file and os.path.exists(self.last_log_file): open_in_explorer(self.last_log_file)
        else: messagebox.showinfo("提示", "尚未產生 Log 或檔案不存在。")
    def save_config(self): pass

    def _get_new_log_filepath(self) -> str:
        logdir = safe_path(self.var_log_dir.get())
        if not logdir: logdir = os.path.join(self.app_dir, "Logs_Delete"); self.var_log_dir.set(logdir)
        os.makedirs(logdir, exist_ok=True)
        name = f"DeleteLog_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        self.last_log_file = os.path.join(logdir, name)
        return self.last_log_file
    def _load_config(self):
        defaults = {"LogDir": os.path.join(self.app_dir, "Logs_Delete"), "ConfirmBefore": True}
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f: defaults.update(json.load(f))
        except Exception: pass
        self.var_log_dir.set(defaults["LogDir"]); self.var_confirm_delete.set(bool(defaults["ConfirmBefore"]))
    def _append_console(self, s: str):
        self.txt_console.insert("end", s); self.txt_console.see("end")

    def _process_ui_queue(self):
        try:
            while not self.ui_queue.empty():
                kind, payload = self.ui_queue.get_nowait()
                if kind == "log": self._append_console(payload + "\n")
                elif kind == "log_batch": self._append_console("".join(f"{line}\n" for line in payload))
                elif kind == "progress": self.pbar["value"] = payload
                elif kind == "status": self.app.update_status(payload)
                elif kind == "summary":
                    self.last_summary = payload
                    self.app.log(f"\n{'-'*20}\n[資料夾刪除] 總結報告:\n{payload}\n{'-'*20}\n")
                elif kind == "done":
                    if payload == "cancel": msg = "刪除任務已被使用者中斷。"
                    else: msg = f"刪除任務已完成！\n\n{self.last_summary}"
                    messagebox.showinfo("任務報告", msg)
                    self.var_status_text.set(f"狀態：{payload}")
                    self.btn_delete.config(state="normal"); self.btn_preview.config(state="normal"); self.btn_cancel.config(state="disabled")
        finally: self.after(100, self._process_ui_queue)

if __name__ == '__main__':
    root = ensure_tk_with_dnd()
    root.title("Delete Pane - Standalone Test")
    root.geometry("800x600")

    class MockApp:
        def __init__(self):
            self.root = root; self.app_dir = '.'
            self.data_state = {"root_folder": "", "all_files": [], "folders": [], "total_size": 0}
            self.pane_instance = None
        def log(self, msg): print(f"[MOCK LOG] {msg}")
        def update_status(self, text): print(f"[MOCK STATUS] {text}")
        def _on_drop(self, event):
            folder = event.data.strip("{}")
            if os.path.isdir(folder):
                self.data_state["root_folder"] = folder
                threading.Thread(target=self._scan_folder, daemon=True).start()
        def _scan_folder(self):
            all_files, folders, total_size = [], [], 0
            for r, d_list, f_list in os.walk(self.data_state["root_folder"]):
                for d in d_list: folders.append(os.path.join(r, d))
                for f in f_list:
                    fp = os.path.join(r, f); all_files.append(fp)
                    try: total_size += os.path.getsize(fp)
                    except OSError: pass
            self.data_state.update({"all_files": all_files, "folders": folders, "total_size": total_size})
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

    pane = DeletePane(root, mock_app, mock_app.app_dir)
    pane.pack(fill="both", expand=True)
    mock_app.pane_instance = pane
    
    root.mainloop()