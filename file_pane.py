# file_pane.py
# version: 2.9.6 (Perfect Alchemy Edition)
__version__ = "2.9.6"

import os
import shutil
import tkinter as tk
from tkinter import ttk, messagebox
from tkinterdnd2 import DND_FILES
import threading
import queue
from collections import defaultdict

# 嘗試載入 utils，若失敗則使用備援定義 (確保獨立執行與主程式的一致性)
try:
    from utils import IMAGE_EXTS, VIDEO_EXTS, natural_sort_key, ensure_tk_with_dnd, create_scrollable_treeview
except ImportError:
    IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.ico']
    # [修正] 同步 utils.py 的完整視訊列表
    VIDEO_EXTS = ['.mp4', '.mov', '.mkv', '.webm', '.avi', '.wmv', '.flv', '.m4v']
    
    def natural_sort_key(s, _re=__import__("re")):
        return [int(c) if c.isdigit() else c.lower() for c in _re.split('([0-9]+)', s)]
    def ensure_tk_with_dnd(): return tk.Tk()
    def create_scrollable_treeview(parent):
        container = ttk.Frame(parent)
        tree = ttk.Treeview(container)
        scrollbar_y = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
        scrollbar_x = ttk.Scrollbar(container, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        return container, tree

class FileOrganizerPane(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.pane_name = "file_pane"
        self.file_list_to_process = []
        
        self.worker_thread = None
        self.ui_queue = queue.Queue()
        self.cancel_event = threading.Event()

        self.checked_state = {}
        self.last_clicked_item = None
        
        self.var_mode = tk.StringVar(value="flatten")
        self.var_flatten_scope = tk.StringVar(value="root_first")
        self.var_rename_img_enabled = tk.BooleanVar(value=True)
        self.var_rename_vid_enabled = tk.BooleanVar(value=True)
        self.var_prefix_img = tk.StringVar(value="")
        self.var_digits_img = tk.IntVar(value=3)
        self.var_start_img = tk.IntVar(value=1)
        self.var_prefix_vid = tk.StringVar(value="v")
        self.var_digits_vid = tk.IntVar(value=2)
        self.var_start_vid = tk.IntVar(value=1)
        self.var_add_string = tk.StringVar(value="")
        self.var_add_position = tk.StringVar(value="prefix")
        self.var_search_string = tk.StringVar(value="")
        self.var_search_mode = tk.StringVar(value="delete")
        self.var_replace_string = tk.StringVar(value="")
        self.img_ext_vars = {ext: tk.BooleanVar(value=True) for ext in IMAGE_EXTS}
        self.vid_ext_vars = {ext: tk.BooleanVar(value=True) for ext in VIDEO_EXTS}
        self.var_img_etc = tk.BooleanVar(value=False)
        self.var_vid_etc = tk.BooleanVar(value=False)
        self.var_select_all_images = tk.BooleanVar(value=True)
        self.var_select_all_videos = tk.BooleanVar(value=True)
        self.var_mem_slot = tk.StringVar(value="slot1")
        self.var_example_original = tk.StringVar(value="EX: D:\\Root\\Image\\Photo\\Cats\\img001.jpg")
        self.var_example_preview = tk.StringVar()

        self._build_ui()
        self._load_config(startup=True)
        self.after(100, self._process_ui_queue)

    def _build_ui(self):
        main_frame = ttk.LabelFrame(self, text=f"檔案整理 v{__version__}")
        main_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        frame_top_control = ttk.Frame(main_frame)
        frame_top_control.pack(fill="x", padx=5, pady=(5,0))

        frame_top = ttk.Frame(frame_top_control)
        frame_top.pack(side="left", fill="x", expand=True)
        
        mem_slot_frame = ttk.LabelFrame(frame_top_control, text="Memory Slot")
        mem_slot_frame.pack(side="right", padx=(10,5))
        
        slot_select_frame = ttk.Frame(mem_slot_frame)
        slot_select_frame.pack()
        ttk.Radiobutton(slot_select_frame, text="Slot 1", variable=self.var_mem_slot, value="slot1").pack(side="left", padx=5)
        ttk.Radiobutton(slot_select_frame, text="Slot 2", variable=self.var_mem_slot, value="slot2").pack(side="left", padx=5)

        slot_action_frame = ttk.Frame(mem_slot_frame)
        slot_action_frame.pack(pady=(0, 5))
        ttk.Button(slot_action_frame, text="Save", command=self._save_config).pack(side="left", padx=5)
        ttk.Button(slot_action_frame, text="Load", command=self._load_config).pack(side="left", padx=5)
        
        mode_frame = ttk.Frame(frame_top)
        mode_frame.grid(row=0, column=0, sticky="w", pady=(0, 5))
        ttk.Label(mode_frame, text="[功能切換]:").pack(side="left", padx=5)
        modes = [("扁平化", "flatten"), ("重新命名", "rename"), ("扁平化+重新命名", "both")]
        for text, value in modes:
            ttk.Radiobutton(mode_frame, text=text, variable=self.var_mode, value=value, command=self._on_mode_change).pack(side="left")

        self.frame_flatten_scope = ttk.LabelFrame(frame_top, text="[處理範圍]:")
        self.frame_flatten_scope.grid(row=1, column=0, sticky="w", padx=5)
        
        scope_modes = [
            ("根目錄優先 Root-Top-SubA-SubB-File (所有子目錄移除)", "root_first"),
            ("頂層優先 Root-File (除頂層子目錄外移除)", "top_level_first"),
            ("子目錄優先 Root-SubA-SubB-file (僅移除頂層子目錄)", "sub_level_first")
        ]
        
        def command_wrapper():
            self._master_preview_updater()
            self._update_example_preview()

        for i, (text, value) in enumerate(scope_modes):
            ttk.Radiobutton(
                self.frame_flatten_scope, text=text, variable=self.var_flatten_scope, 
                value=value, command=command_wrapper
            ).grid(row=i, column=0, sticky="w", padx=5, pady=2)
        
        ttk.Separator(self.frame_flatten_scope, orient="horizontal").grid(row=i+1, column=0, sticky="ew", pady=5, padx=5)
        ttk.Label(self.frame_flatten_scope, textvariable=self.var_example_original, foreground="gray").grid(row=i+2, column=0, sticky="w", padx=5)
        ttk.Label(self.frame_flatten_scope, textvariable=self.var_example_preview, foreground="blue").grid(row=i+3, column=0, sticky="w", padx=5, pady=(0, 5))

        frame_naming = tk.LabelFrame(main_frame, text="命名設定")
        frame_naming.pack(fill="x", padx=10, pady=5, ipady=5)
        
        ttk.Checkbutton(frame_naming, text="圖片流水號:", variable=self.var_rename_img_enabled, command=self._master_preview_updater).grid(row=0, column=0, sticky="w", padx=5, pady=2)
        entry_prefix_img = tk.Entry(frame_naming, textvariable=self.var_prefix_img, width=8); entry_prefix_img.grid(row=0, column=1)
        entry_prefix_img.bind("<KeyRelease>", lambda e: self._master_preview_updater())
        ttk.Label(frame_naming, text="位元數:").grid(row=0, column=2, padx=(5,0))
        tk.Spinbox(frame_naming, from_=1, to=6, textvariable=self.var_digits_img, width=5, command=self._master_preview_updater).grid(row=0, column=3)
        ttk.Label(frame_naming, text="起始值:").grid(row=0, column=4, padx=(5,0))
        tk.Spinbox(frame_naming, from_=1, to=9999, textvariable=self.var_start_img, width=5, command=self._master_preview_updater).grid(row=0, column=5)
        self.preview_img = tk.Label(frame_naming, text="預覽: 001"); self.preview_img.grid(row=0, column=6, padx=10)
        
        ttk.Checkbutton(frame_naming, text="影片流水號:", variable=self.var_rename_vid_enabled, command=self._master_preview_updater).grid(row=1, column=0, sticky="w", padx=5, pady=2)
        entry_prefix_vid = tk.Entry(frame_naming, textvariable=self.var_prefix_vid, width=8); entry_prefix_vid.grid(row=1, column=1)
        entry_prefix_vid.bind("<KeyRelease>", lambda e: self._master_preview_updater())
        ttk.Label(frame_naming, text="位元數:").grid(row=1, column=2, padx=(5,0))
        tk.Spinbox(frame_naming, from_=1, to=6, textvariable=self.var_digits_vid, width=5, command=self._master_preview_updater).grid(row=1, column=3)
        ttk.Label(frame_naming, text="起始值:").grid(row=1, column=4, padx=(5,0))
        tk.Spinbox(frame_naming, from_=1, to=9999, textvariable=self.var_start_vid, width=5, command=self._master_preview_updater).grid(row=1, column=5)
        self.preview_vid = tk.Label(frame_naming, text="預覽: v01"); self.preview_vid.grid(row=1, column=6, padx=10)
        
        ttk.Separator(frame_naming, orient="horizontal").grid(row=2, column=0, columnspan=7, sticky="ew", pady=5)
        tk.Label(frame_naming, text="新增字串:").grid(row=3, column=0, padx=5, pady=2, sticky="w")
        entry_add_str = tk.Entry(frame_naming, textvariable=self.var_add_string, width=20); entry_add_str.grid(row=3, column=1, columnspan=2, sticky="w")
        entry_add_str.bind("<KeyRelease>", lambda e: self._master_preview_updater())
        tk.Radiobutton(frame_naming, text="前置", variable=self.var_add_position, value="prefix", command=self._master_preview_updater).grid(row=3, column=3, padx=5)
        tk.Radiobutton(frame_naming, text="後置", variable=self.var_add_position, value="suffix", command=self._master_preview_updater).grid(row=3, column=4, padx=5)
        
        tk.Label(frame_naming, text="搜尋字串:").grid(row=4, column=0, padx=5, pady=2, sticky="w")
        entry_search_str = tk.Entry(frame_naming, textvariable=self.var_search_string, width=20); entry_search_str.grid(row=4, column=1, columnspan=2, sticky="w")
        entry_search_str.bind("<KeyRelease>", lambda e: self._master_preview_updater())
        tk.Radiobutton(frame_naming, text="刪除", variable=self.var_search_mode, value="delete", command=self._master_preview_updater).grid(row=4, column=3, padx=5)
        tk.Radiobutton(frame_naming, text="取代為", variable=self.var_search_mode, value="replace", command=self._master_preview_updater).grid(row=4, column=4, padx=5)
        entry_replace_str = tk.Entry(frame_naming, textvariable=self.var_replace_string, width=20); entry_replace_str.grid(row=4, column=5, columnspan=2, padx=5, sticky="w")
        entry_replace_str.bind("<KeyRelease>", lambda e: self._master_preview_updater())

        frame_ext = tk.LabelFrame(main_frame, text="副檔名群組"); frame_ext.pack(fill="x", padx=10, pady=5)
        img_frame = ttk.Frame(frame_ext); img_frame.grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(img_frame, text="圖片:", variable=self.var_select_all_images, command=self._on_select_all_images_toggle).pack(side="left", padx=(5,10))
        for ext, var in self.img_ext_vars.items(): ttk.Checkbutton(img_frame, text=ext, variable=var, command=self._master_preview_updater).pack(side="left")
        ttk.Checkbutton(img_frame, text="etc", variable=self.var_img_etc, command=lambda: self._on_etc_toggle('img')).pack(side="left", padx=(10, 0))
        
        vid_frame = ttk.Frame(frame_ext); vid_frame.grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(vid_frame, text="影片:", variable=self.var_select_all_videos, command=self._on_select_all_videos_toggle).pack(side="left", padx=(5,10))
        for ext, var in self.vid_ext_vars.items(): ttk.Checkbutton(vid_frame, text=ext, variable=var, command=self._master_preview_updater).pack(side="left")
        ttk.Checkbutton(vid_frame, text="etc", variable=self.var_vid_etc, command=lambda: self._on_etc_toggle('vid')).pack(side="left", padx=(10, 0))
        
        frame_preview = tk.LabelFrame(main_frame, text="檔案預覽區"); frame_preview.pack(fill="both", expand=False, padx=10, pady=(5, 0))
        tree_container, self.file_tree = create_scrollable_treeview(frame_preview)
        self.file_tree.configure(height=10)
        tree_container.pack(fill="both", expand=False)
        
        columns = ("checked", "original", "new"); self.file_tree.configure(columns=columns, show="headings")
        self.file_tree.heading("checked", text="✔"); self.file_tree.heading("original", text="原檔案路徑"); self.file_tree.heading("new", text="新檔案路徑")
        self.file_tree.column("checked", width=40, anchor="center", stretch=False); self.file_tree.column("original", width=330); self.file_tree.column("new", width=330)
        self.file_tree.tag_configure('checked', foreground='blue'); self.file_tree.bind('<Button-1>', self._on_tree_click); self.file_tree.bind('<space>', self._on_space_press)
        
        exec_frame = ttk.Frame(main_frame); exec_frame.pack(fill="x", padx=10, pady=10); exec_frame.columnconfigure(1, weight=1)
        btn_frame = ttk.Frame(exec_frame); btn_frame.grid(row=0, column=0, sticky="w")
        ttk.Button(btn_frame, text="✔", command=self._toggle_selection_check, width=3).pack(side="left")
        ttk.Button(btn_frame, text="全選", command=self._select_all).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="清除", command=self._clear_all).pack(side="left")
        self.pbar = ttk.Progressbar(exec_frame); self.pbar.grid(row=0, column=1, sticky="ew", padx=10)
        self.btn_execute = ttk.Button(exec_frame, text="開始處理", command=self.execute_file_organizer); self.btn_execute.grid(row=0, column=2, padx=(10, 0))
        self.btn_cancel = ttk.Button(exec_frame, text="取消", command=self._on_cancel, state="disabled"); self.btn_cancel.grid(row=0, column=3, padx=(5, 0))
        
        for var in [self.var_digits_img, self.var_start_img, self.var_digits_vid, self.var_start_vid]: var.trace_add("write", lambda *args: self._master_preview_updater())
        self._on_mode_change()
        self._update_example_preview()

    def _update_example_preview(self):
        scope = self.var_flatten_scope.get()
        preview_text = ""
        if scope == "root_first":
            preview_text = "[預覽]: D:\\Root\\img001.jpg"
        elif scope == "top_level_first":
            preview_text = "[預覽]: D:\\Root\\Image\\img001.jpg"
        elif scope == "sub_level_first":
            preview_text = "[預覽]: D:\\Root\\Photo\\Cats\\img001.jpg"
        self.var_example_preview.set(preview_text)

    def _on_mode_change(self):
        self._master_preview_updater()

    def _get_settings_as_dict(self):
        return { 
            "mode": self.var_mode.get(), "flatten_scope": self.var_flatten_scope.get(),
            "rename_img_enabled": self.var_rename_img_enabled.get(), "prefix_img": self.var_prefix_img.get(), "digits_img": self.var_digits_img.get(), "start_img": self.var_start_img.get(), 
            "rename_vid_enabled": self.var_rename_vid_enabled.get(), "prefix_vid": self.var_prefix_vid.get(), "digits_vid": self.var_digits_vid.get(), "start_vid": self.var_start_vid.get(), 
            "add_string": self.var_add_string.get(), "add_position": self.var_add_position.get(), 
            "search_string": self.var_search_string.get(), "search_mode": self.var_search_mode.get(), "replace_string": self.var_replace_string.get() 
        }

    def _apply_settings_from_dict(self, settings_dict):
        for key, value in settings_dict.items():
            var_name = f"var_{key}"
            if hasattr(self, var_name):
                try: getattr(self, var_name).set(value)
                except tk.TclError: pass
        self._on_mode_change()
        self._update_example_preview()
        self._master_preview_updater()

    def _calculate_final_paths(self):
        root_folder = getattr(self.app, 'data_state', {}).get("root_folder")
        if not root_folder: return {}
        
        all_items_in_order = self.file_tree.get_children('')
        if not all_items_in_order: return {}
        
        item_id_to_src_map = {item_id: self.file_list_to_process[i] for i, item_id in enumerate(all_items_in_order)}
        items_to_process = {item_id for item_id in all_items_in_order if self.checked_state.get(item_id, True)}
        mode, flatten_scope = self.var_mode.get(), self.var_flatten_scope.get()

        # STAGE 1: Predict Final Home
        item_id_to_dest_folder = {}
        for item_id in all_items_in_order:
            src_path = item_id_to_src_map[item_id]
            dest_folder = os.path.dirname(src_path)
            if item_id in items_to_process and mode in ["flatten", "both"]:
                if flatten_scope == "root_first":
                    dest_folder = root_folder
                elif flatten_scope == "top_level_first":
                    relative_path = os.path.relpath(src_path, root_folder)
                    if os.sep in relative_path:
                        dest_folder = os.path.join(root_folder, relative_path.split(os.sep)[0])
                    else:
                        dest_folder = root_folder
                elif flatten_scope == "sub_level_first":
                    src_dir_rel = os.path.relpath(os.path.dirname(src_path), root_folder)
                    if src_dir_rel != '.':
                        parts = src_dir_rel.split(os.sep)
                        if len(parts) > 1:
                            dest_folder = os.path.join(root_folder, *parts[1:])
                        else:
                            dest_folder = root_folder
                    else:
                        dest_folder = root_folder
            item_id_to_dest_folder[item_id] = dest_folder

        # STAGE 2: Generate Ideal Name
        ideal_name_map = {}
        grouped_by_dest = defaultdict(list)
        for item_id in items_to_process:
            grouped_by_dest[item_id_to_dest_folder[item_id]].append(item_id)
        
        if mode in ["rename", "both"]:
            img_exts = {ext for ext, var in self.img_ext_vars.items() if var.get()}
            vid_exts = {ext for ext, var in self.vid_ext_vars.items() if var.get()}
            def get_cat(p):
                ext = os.path.splitext(p)[1].lower()
                if ext in img_exts: return 'img'
                if ext in vid_exts: return 'vid'
                return 'etc'
            for _, items_in_group in grouped_by_dest.items():
                img_count, vid_count = self.var_start_img.get(), self.var_start_vid.get()
                sorted_items = sorted(items_in_group, key=lambda i: natural_sort_key(item_id_to_src_map[i]))
                if self.var_rename_img_enabled.get():
                    p, d = self.var_prefix_img.get(), self.var_digits_img.get()
                    for item_id in [i for i in sorted_items if get_cat(item_id_to_src_map[i]) == 'img']:
                        ext = os.path.splitext(item_id_to_src_map[item_id])[1]
                        ideal_name_map[item_id] = f"{p}{img_count:0{d}d}{ext}"; img_count += 1
                if self.var_rename_vid_enabled.get():
                    p, d = self.var_prefix_vid.get(), self.var_digits_vid.get()
                    for item_id in [i for i in sorted_items if get_cat(item_id_to_src_map[i]) == 'vid']:
                        ext = os.path.splitext(item_id_to_src_map[item_id])[1]
                        ideal_name_map[item_id] = f"{p}{vid_count:0{d}d}{ext}"; vid_count += 1
        
        add_str, search_str = self.var_add_string.get(), self.var_search_string.get()
        if add_str or search_str:
            for item_id in items_to_process:
                base_name = ideal_name_map.get(item_id, os.path.basename(item_id_to_src_map[item_id]))
                name, ext = os.path.splitext(base_name)
                if add_str: name = f"{add_str}{name}" if self.var_add_position.get() == "prefix" else f"{name}{add_str}"
                if search_str:
                    if self.var_search_mode.get() == "delete": name = name.replace(search_str, "")
                    else: name = name.replace(search_str, self.var_replace_string.get())
                ideal_name_map[item_id] = f"{name}{ext}"

        # STAGE 3: Unified Conflict Mediation
        future_paths = set()
        final_path_map = {}
        for item_id in all_items_in_order:
            src_path = item_id_to_src_map[item_id]
            if item_id not in items_to_process:
                final_path_map[item_id] = src_path
                future_paths.add(src_path.lower())
                continue
            
            dest_folder = item_id_to_dest_folder[item_id]
            ideal_name = ideal_name_map.get(item_id, os.path.basename(src_path))
            base, ext = os.path.splitext(ideal_name)
            
            resolved_path = os.path.join(dest_folder, ideal_name)
            counter = 1
            while resolved_path.lower() in future_paths:
                resolved_path = os.path.join(dest_folder, f"{base}({counter}){ext}")
                counter += 1
            
            future_paths.add(resolved_path.lower())
            final_path_map[item_id] = resolved_path
            
        return final_path_map
    
    def _master_preview_updater(self, is_full_reload=False):
        try:
            p_img, d_img, s_img = self.var_prefix_img.get(), self.var_digits_img.get(), self.var_start_img.get()
            self.preview_img.config(text=f"預覽: {p_img}{s_img:0{d_img}d}")
            p_vid, d_vid, s_vid = self.var_prefix_vid.get(), self.var_digits_vid.get(), self.var_start_vid.get()
            self.preview_vid.config(text=f"預覽: {p_vid}{s_vid:0{d_vid}d}")
        except (tk.TclError, ValueError): pass
        root_folder = getattr(self.app, 'data_state', {}).get("root_folder", ".")
        if is_full_reload:
            self.file_tree.delete(*self.file_tree.get_children())
            self.checked_state.clear()
            for src in self.file_list_to_process:
                rel_path = os.path.relpath(src, root_folder) if root_folder != "." else src
                values = ('☑', rel_path, "")
                item_id = self.file_tree.insert("", "end", values=values, tags=('checked',))
                self.checked_state[item_id] = True
        final_path_map = self._calculate_final_paths()
        for item_id, final_path in final_path_map.items():
            rel_path = os.path.relpath(final_path, root_folder) if root_folder != "." else final_path
            self.file_tree.set(item_id, column="new", value=rel_path)

    def execute_file_organizer(self):
        final_path_map = self._calculate_final_paths()
        tasks_to_run = []
        for i, item_id in enumerate(self.file_tree.get_children('')):
            if self.checked_state.get(item_id, False):
                src_path = self.file_list_to_process[i]
                final_path = final_path_map.get(item_id, src_path)
                if src_path.lower() != final_path.lower(): tasks_to_run.append((src_path, final_path))
        if not tasks_to_run: messagebox.showinfo("提示", "沒有需要處理的檔案變更。"); return
        self.btn_execute.config(state="disabled"); self.btn_cancel.config(state="normal")
        self.pbar['value'] = 0; self.cancel_event.clear()
        root_folder = getattr(self.app, 'data_state', {}).get("root_folder")
        
        mode = self.var_mode.get()
        is_flatten_mode = mode in ["flatten", "both"]
        self.worker_thread = FileOrganizerWorker(tasks_to_run, is_flatten_mode, root_folder, self.ui_queue, self.cancel_event, self.app)
        self.worker_thread.start()

    def _on_select_all_images_toggle(self):
        is_checked = self.var_select_all_images.get();
        for var in self.img_ext_vars.values(): var.set(is_checked)
        self._master_preview_updater()
    def _on_select_all_videos_toggle(self):
        is_checked = self.var_select_all_videos.get();
        for var in self.vid_ext_vars.values(): var.set(is_checked)
        self._master_preview_updater()
    def _on_etc_toggle(self, clicked):
        if clicked == 'img' and self.var_img_etc.get() and self.var_vid_etc.get(): self.var_vid_etc.set(False)
        elif clicked == 'vid' and self.var_vid_etc.get() and self.var_img_etc.get(): self.var_img_etc.set(False)
        self._master_preview_updater()
    def receive_update(self, data_state): self.update_file_preview(data_state)
    def update_file_preview(self, data_state=None):
        if data_state is None: data_state = self.app.data_state if hasattr(self, 'app') and hasattr(self.app, 'data_state') else None
        self.file_list_to_process.clear()
        if data_state and data_state.get("root_folder"):
            all_files = sorted(data_state["all_files"], key=natural_sort_key)
            for file in all_files: self.file_list_to_process.append(file)
        self._master_preview_updater(is_full_reload=True)
    def _load_config(self, startup=False):
        slot = self.var_mem_slot.get() if not startup else "slot1"
        all_app_configs = self.app.load_app_config() if hasattr(self.app, 'load_app_config') else {}
        pane_configs = all_app_configs.get(self.pane_name, {})
        settings = pane_configs.get(slot)
        if settings:
            self._apply_settings_from_dict(settings)
            if not startup and hasattr(self.app, 'log'): self.app.log(f"FilePane: 已從 Slot {slot[-1]} 載入設定。")
        elif not startup: messagebox.showinfo("提示", f"Slot {slot[-1]} 沒有儲存的設定。")
    def _save_config(self):
        slot = self.var_mem_slot.get()
        if not hasattr(self.app, 'load_app_config'): messagebox.showerror("錯誤", "無法在獨立模式下儲存設定。"); return
        all_app_configs = self.app.load_app_config()
        if self.pane_name not in all_app_configs: all_app_configs[self.pane_name] = {}
        all_app_configs[self.pane_name][slot] = self._get_settings_as_dict()
        self.app.save_app_config(all_app_configs)
        self.app.log(f"FilePane: 設定已儲存至 Slot {slot[-1]}。")
    def _update_visual_check_state(self, item_ids, state):
        tag, symbol = (('checked',), '☑') if state else ((), '☐')
        for item_id in item_ids:
            values = list(self.file_tree.item(item_id, 'values')); values[0] = symbol
            self.file_tree.item(item_id, values=tuple(values), tags=tag)
    def _on_tree_click(self, event):
        region = self.file_tree.identify_region(event.x, event.y)
        if region != "cell" or self.file_tree.identify_column(event.x) != '#1': return
        item_id = self.file_tree.identify_row(event.y)
        if not item_id: return
        items_to_update = [item_id]
        new_state = not self.checked_state.get(item_id, False)
        if (event.state & 4) and self.last_clicked_item in self.file_tree.get_children(''):
            start_idx, end_idx = self.file_tree.index(self.last_clicked_item), self.file_tree.index(item_id)
            if start_idx > end_idx: start_idx, end_idx = end_idx, start_idx
            new_state = self.checked_state.get(self.last_clicked_item, False)
            items_to_update = self.file_tree.get_children('')[start_idx:end_idx+1]
        for itm in items_to_update: self.checked_state[itm] = new_state
        self._update_visual_check_state(items_to_update, new_state)
        self.last_clicked_item = item_id if len(items_to_update) == 1 else None
        self._master_preview_updater()
    def _batch_update_check_state(self, selected_items):
        if not selected_items: return
        target_state = not self.checked_state.get(selected_items[0], False)
        for item_id in selected_items: self.checked_state[item_id] = target_state
        self._update_visual_check_state(selected_items, target_state)
        self._master_preview_updater()
    def _on_space_press(self, event):
        selected_items = self.file_tree.selection()
        if selected_items: self._batch_update_check_state(selected_items); return "break"
    def _toggle_selection_check(self):
        selected_items = self.file_tree.selection()
        if not selected_items: messagebox.showinfo("提示", "請先在預覽區中選取(反藍)一個或多個項目。"); return
        self._batch_update_check_state(selected_items)
    def _set_all_checks(self, state: bool):
        all_items = self.file_tree.get_children('')
        for item_id in all_items: self.checked_state[item_id] = state
        self._update_visual_check_state(all_items, state)
        self._master_preview_updater()
    def _select_all(self): self._set_all_checks(True)
    def _clear_all(self): self._set_all_checks(False)
    def _on_cancel(self):
        if self.worker_thread and self.worker_thread.is_alive():
            if hasattr(self.app, 'log'): self.app.log("[檔案整理] 正在傳送取消訊號...")
            self.cancel_event.set(); self.btn_cancel.config(state="disabled")
    def _process_ui_queue(self):
        try:
            while not self.ui_queue.empty():
                kind, payload = self.ui_queue.get_nowait()
                if kind == "progress": self.pbar['value'] = payload
                elif kind == "done":
                    status_text = "任務已取消" if payload == "cancel" else "任務已完成"
                    if hasattr(self.app, 'update_status'): self.app.update_status(f"檔案整理：{status_text}")
                    self.btn_execute.config(state="normal"); self.btn_cancel.config(state="disabled")
        finally: self.after(100, self._process_ui_queue)

class FileOrganizerWorker(threading.Thread):
    def __init__(self, file_list, is_flatten, root_folder, ui_queue, cancel_event, app):
        super().__init__(daemon=True)
        self.file_list, self.is_flatten, self.root_folder = file_list, is_flatten, root_folder
        self.ui_queue, self.cancel_event, self.app = ui_queue, cancel_event, app
    def run(self):
        total_files, processed_count = len(self.file_list), 0
        for i, (src, dst) in enumerate(self.file_list):
            if self.cancel_event.is_set(): break
            if src.lower() != dst.lower():
                try:
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.move(src, dst); processed_count += 1
                except Exception as e: 
                    if hasattr(self.app, 'log'): self.app.log(f"❌ 無法處理檔案 {os.path.basename(src)}: {e}")
            progress = int((i + 1) * 100 / total_files) if total_files > 0 else 0
            self.ui_queue.put(("progress", progress))
        if self.is_flatten and self.root_folder and not self.cancel_event.is_set():
            try:
                for root, dirs, _ in os.walk(self.root_folder, topdown=False):
                    for d in dirs:
                        dir_path = os.path.join(root, d)
                        try:
                            os.rmdir(dir_path)
                        except OSError as e:
                            if hasattr(self.app, 'log'):
                                self.app.log(f"⚠️ 無法清理目錄 {os.path.basename(dir_path)}: {e}")
            except Exception as e: 
                if hasattr(self.app, 'log'): self.app.log(f"❌ 清理空目錄失敗: {e}")
        final_status = "cancel" if self.cancel_event.is_set() else "ok"
        if final_status == "ok":
            if hasattr(self.app, 'log'): self.app.log(f"✔ 檔案整理完成：共處理 {processed_count} 個檔案。")
            if hasattr(self.app, '_scan_folder'): threading.Thread(target=self.app._scan_folder, daemon=True).start()
        self.ui_queue.put(("done", final_status))

if __name__ == '__main__':
    root = ensure_tk_with_dnd()
    root.title("File Organizer Pane - Standalone Test")
    root.geometry("800x960")
    class MockApp:
        def __init__(self):
            self.root = root; self.app_dir = '.'
            self.data_state = { "root_folder": "", "all_files": [] }
            self.pane_instance = None
        def log(self, msg): print(f"[MOCK LOG] {msg}")
        def update_status(self, text): print(f"[MOCK STATUS] {text}")
        def load_app_config(self): print(f"[MOCK] Loading config..."); return {"file_pane":{}}
        def save_app_config(self, cfg): print(f"[MOCK] Saving config: {cfg}")
        def _on_drop(self, event):
            folder = event.data.strip('{}')
            if os.path.isdir(folder):
                self.data_state["root_folder"] = folder
                threading.Thread(target=self._scan_folder, daemon=True).start()
        def _scan_folder(self):
            self.data_state["all_files"] = [os.path.join(r, f) for r, _, fs in os.walk(self.data_state["root_folder"]) for f in fs]
            self.root.after(0, self.pane_instance.receive_update, self.data_state)
    mock_app = MockApp()
    frame_drag = tk.LabelFrame(root, text="[MOCK] Drop Zone"); frame_drag.pack(fill="x", padx=10, pady=10)
    label_drag = tk.Label(frame_drag, text="📂 Drop a folder here to test", height=4); label_drag.pack(fill="x", expand=True)
    label_drag.drop_target_register(DND_FILES); label_drag.dnd_bind("<<Drop>>", mock_app._on_drop)
    pane = FileOrganizerPane(root, mock_app); pane.pack(fill="both", expand=True)
    mock_app.pane_instance = pane
    root.mainloop()