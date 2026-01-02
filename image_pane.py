# image_pane.py
# version: 2.6.0 (Cleaned & Exif Support)
__version__ = "2.6.0"

import os
import json
import queue
import threading
import time
import shutil
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinterdnd2 import DND_FILES

try:
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = None
except ImportError:
    messagebox.showerror("缺少函式庫", "此功能需要 Pillow 函式庫。\n請使用 'pip install Pillow' 來安裝。")
    Image, ImageOps = None, None

# 保持與 file_pane.py 的一致性，同時確保獨立執行能力
try:
    from utils import IMAGE_EXTS, format_size, ensure_tk_with_dnd, natural_sort_key, create_scrollable_treeview
except ImportError:
    IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.ico']
    def format_size(size_bytes):
        if size_bytes == 0: return "0 B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(__import__("math").floor(__import__("math").log(size_bytes, 1024)))
        p = __import__("math").pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"
    def natural_sort_key(s, _re=__import__("re")):
        return [int(c) if c.isdigit() else c.lower() for c in _re.split('([0-9]+)', s)]
    def ensure_tk_with_dnd():
        try: from tkinterdnd2 import TkinterDND; return TkinterDND.Tk()
        except ImportError: return tk.Tk()
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

class ImageProcessingPane(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.pane_name = "image_pane"
        self.worker_thread = None
        self.ui_queue = queue.Queue()
        self.image_details_list = []
        self.original_aspect_ratio = 16 / 9.0
        self.cancel_event = threading.Event()
        self.last_summary = ""
        
        self.checked_state = {}
        self.last_clicked_item = None

        self._setup_ui_variables()
        
        # Extension filters
        self.img_ext_vars = {ext: tk.BooleanVar(value=True) for ext in IMAGE_EXTS}
        if '.gif' in self.img_ext_vars:
            self.img_ext_vars['.gif'].set(False) 
        self.var_select_all_images = tk.BooleanVar(value=False)

        self._build_ui()
        self._load_config()
        self.after(100, self._process_ui_queue)

    def _setup_ui_variables(self):
        self.var_format = tk.StringVar(value="維持原格式")
        self.var_quality = tk.IntVar(value=95)
        self.var_max_quality_detail = tk.BooleanVar(value=False)
        self.var_keep_exif = tk.BooleanVar(value=False) # New: Exif support
        
        self.var_output_mode = tk.StringVar(value="overwrite")
        self.var_output_dir = tk.StringVar()
        
        self.var_resize_enabled = tk.BooleanVar(value=False)
        self.var_resize_mode = tk.StringVar(value="百分比")
        self.var_width = tk.StringVar(value="100")
        self.var_height = tk.StringVar(value="100")
        self.var_keep_ratio = tk.BooleanVar(value=True)
        self.var_scale_rule = tk.StringVar(value="僅縮小，不放大")
        self.var_aspect_ratio = tk.StringVar(value="原始")
        
        self.var_warn_overwrite = tk.BooleanVar(value=True)
        self.var_notify_complete = tk.BooleanVar(value=True)

    def _build_ui(self):
        main_frame = ttk.LabelFrame(self, text=f"圖像處理 v{__version__}")
        main_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        control_panel = ttk.Frame(main_frame)
        control_panel.pack(fill="x", pady=5)
        control_panel.columnconfigure(0, weight=1)
        control_panel.columnconfigure(1, weight=1)

        self._create_output_widgets(control_panel)
        self._create_resize_widgets(control_panel)
        self._create_settings_widgets(control_panel)
        self._create_extension_filter_widgets(main_frame)

        frame_preview = ttk.LabelFrame(main_frame, text="檔案預覽區")
        frame_preview.pack(fill="both", expand=True, padx=10, pady=5)
        
        tree_container, self.file_tree = create_scrollable_treeview(frame_preview)
        tree_container.pack(fill="both", expand=True)

        columns = ("checked", "original_path", "new_path", "dimensions", "size")
        self.file_tree.configure(columns=columns, show="headings")
        self.file_tree.heading("checked", text="✔")
        self.file_tree.heading("original_path", text="原檔案路徑")
        self.file_tree.heading("new_path", text="新檔案路徑 (預覽)")
        self.file_tree.heading("dimensions", text="尺寸")
        self.file_tree.heading("size", text="檔案大小")
        self.file_tree.column("checked", width=40, anchor="center", stretch=False)
        self.file_tree.column("original_path", width=200, anchor="w")
        self.file_tree.column("new_path", width=200, anchor="w")
        self.file_tree.column("dimensions", width=120, anchor="center")
        self.file_tree.column("size", width=120, anchor="e")
        self.file_tree.tag_configure('checked', foreground='blue')
        self.file_tree.bind('<Button-1>', self._on_tree_click)
        self.file_tree.bind('<space>', self._on_space_press)

        exec_frame = ttk.Frame(main_frame)
        exec_frame.pack(fill="x", padx=10, pady=10)
        exec_frame.columnconfigure(1, weight=1)

        btn_frame = ttk.Frame(exec_frame); btn_frame.grid(row=0, column=0, sticky="w")
        ttk.Button(btn_frame, text="✔", command=self._toggle_selection_check, width=3).pack(side="left")
        ttk.Button(btn_frame, text="全選", command=self._select_all).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="清除", command=self._clear_all).pack(side="left")

        self.pbar = ttk.Progressbar(exec_frame); self.pbar.grid(row=0, column=1, sticky="ew", padx=10)
        self.btn_execute = ttk.Button(exec_frame, text="開始處理", command=self._on_execute); self.btn_execute.grid(row=0, column=2, padx=(10, 0))
        self.btn_cancel = ttk.Button(exec_frame, text="取消", command=self._on_cancel, state="disabled"); self.btn_cancel.grid(row=0, column=3, padx=(5, 0))

    def _create_output_widgets(self, parent):
        frame = ttk.LabelFrame(parent, text="輸出設定")
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        frame.columnconfigure(1, weight=1)
        
        ttk.Label(frame, text="目標格式:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        self.combo_format = ttk.Combobox(frame, textvariable=self.var_format, values=["維持原格式", "JPG", "PNG", "WEBP"], state="readonly")
        self.combo_format.grid(row=0, column=1, columnspan=2, sticky="ew", padx=5, pady=2)
        self.combo_format.bind("<<ComboboxSelected>>", self.update_preview)
        
        ttk.Label(frame, text="JPEG/WEBP 品質:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        self.scale_quality = ttk.Scale(frame, from_=1, to=100, orient="horizontal", variable=self.var_quality, command=lambda e: self.var_quality.set(int(float(e))))
        self.scale_quality.grid(row=1, column=1, sticky="ew", padx=5, pady=2)
        self.label_quality = ttk.Label(frame, textvariable=self.var_quality, width=4)
        self.label_quality.grid(row=1, column=2, padx=(5,0))
        
        # Quality & Exif options
        self.chk_max_quality = ttk.Checkbutton(frame, text="保留最大色彩細節 (檔案較大)", variable=self.var_max_quality_detail)
        self.chk_max_quality.grid(row=2, column=1, columnspan=2, sticky="w", padx=5, pady=0)
        
        self.chk_keep_exif = ttk.Checkbutton(frame, text="保留相機資訊 (Exif)", variable=self.var_keep_exif)
        self.chk_keep_exif.grid(row=3, column=1, columnspan=2, sticky="w", padx=5, pady=0)

        ttk.Label(frame, text="輸出位置:").grid(row=4, column=0, sticky="w", padx=5, pady=2)
        output_frame = ttk.Frame(frame)
        output_frame.grid(row=4, column=1, columnspan=2, sticky="ew", padx=5, pady=2)
        ttk.Radiobutton(output_frame, text="覆蓋原始檔案", variable=self.var_output_mode, value="overwrite", command=self.update_preview).pack(anchor="w")
        ttk.Radiobutton(output_frame, text="儲存到 'resized' 子資料夾", variable=self.var_output_mode, value="resized", command=self.update_preview).pack(anchor="w")
        ttk.Radiobutton(output_frame, text="儲存到自訂資料夾:", variable=self.var_output_mode, value="custom", command=self.update_preview).pack(anchor="w")
        
        custom_dir_frame = ttk.Frame(frame)
        custom_dir_frame.grid(row=5, column=1, columnspan=2, sticky="ew", padx=5, pady=(0,5))
        self.entry_output_dir = ttk.Entry(custom_dir_frame, textvariable=self.var_output_dir)
        self.entry_output_dir.pack(side="left", fill="x", expand=True)
        ttk.Button(custom_dir_frame, text="瀏覽", command=self._browse_output_dir, width=6).pack(side="left", padx=(5,0))
        ttk.Button(custom_dir_frame, text="開啟", command=self._open_output_dir, width=6).pack(side="left", padx=(5,0))

    def _create_resize_widgets(self, parent):
        frame = ttk.LabelFrame(parent, text="調整大小")
        frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        
        self.chk_resize_enabled = ttk.Checkbutton(frame, text="啟用調整大小", variable=self.var_resize_enabled, command=self._toggle_resize_widgets)
        self.chk_resize_enabled.grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=2)
        
        ttk.Label(frame, text="模式:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        self.combo_resize_mode = ttk.Combobox(frame, textvariable=self.var_resize_mode, values=["百分比", "像素"], state="readonly", width=12)
        self.combo_resize_mode.grid(row=1, column=1, sticky="ew", padx=5, pady=2)
        self.combo_resize_mode.bind("<<ComboboxSelected>>", self._on_resize_mode_change)
        
        ttk.Label(frame, text="寬度:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        self.entry_width = ttk.Entry(frame, textvariable=self.var_width, width=14)
        self.entry_width.grid(row=2, column=1, sticky="ew", padx=5, pady=2)
        self.entry_width.bind("<KeyRelease>", lambda e: self._on_dimension_change(e, "width"))
        
        ttk.Label(frame, text="高度:").grid(row=3, column=0, sticky="w", padx=5, pady=2)
        self.entry_height = ttk.Entry(frame, textvariable=self.var_height, width=14)
        self.entry_height.grid(row=3, column=1, sticky="ew", padx=5, pady=2)
        self.entry_height.bind("<KeyRelease>", lambda e: self._on_dimension_change(e, "height"))
        
        self.chk_keep_ratio = ttk.Checkbutton(frame, text="保持比例", variable=self.var_keep_ratio)
        self.chk_keep_ratio.grid(row=4, column=0, columnspan=2, sticky="w", padx=5, pady=2)
        
        ttk.Label(frame, text="比例:").grid(row=5, column=0, sticky="w", padx=5, pady=2)
        ratios = ["原始", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "16:10", "1:1"]
        self.combo_ratio = ttk.Combobox(frame, textvariable=self.var_aspect_ratio, values=ratios, state="readonly", width=12)
        self.combo_ratio.grid(row=5, column=1, sticky="ew", padx=5, pady=2)
        self.combo_ratio.bind("<<ComboboxSelected>>", self._on_aspect_ratio_change)
        
        ttk.Label(frame, text="縮放規則:").grid(row=6, column=0, sticky="w", padx=5, pady=2)
        self.combo_scale_rule = ttk.Combobox(frame, textvariable=self.var_scale_rule, values=["放大或縮小", "僅縮小，不放大"], state="readonly", width=12)
        self.combo_scale_rule.grid(row=6, column=1, sticky="ew", padx=5, pady=2)
        self._toggle_resize_widgets()

    def _create_settings_widgets(self, parent):
        frame = ttk.LabelFrame(parent, text="提示與設定")
        frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=(0, 5), pady=5)
        ttk.Checkbutton(frame, text="覆蓋前彈出警告", variable=self.var_warn_overwrite).pack(side="left", padx=5)
        ttk.Checkbutton(frame, text="完成後彈出提示", variable=self.var_notify_complete).pack(side="left", padx=5)
        ttk.Button(frame, text="儲存設定", command=self._save_config).pack(side="right", padx=5)

    def _create_extension_filter_widgets(self, parent):
        frame = ttk.LabelFrame(parent, text="副檔名篩選")
        frame.pack(fill="x", padx=10, pady=(0, 5))
        img_frame = ttk.Frame(frame)
        img_frame.pack(fill="x", padx=5, pady=(5, 7))
        ttk.Checkbutton(img_frame, text="圖片類型:", variable=self.var_select_all_images, command=self._on_select_all_images_toggle).pack(side="left", padx=(0,10))
        for ext in IMAGE_EXTS: 
            if ext in self.img_ext_vars:
                var = self.img_ext_vars[ext]
                ttk.Checkbutton(img_frame, text=ext, variable=var, command=self.receive_update).pack(side="left")

    def _on_select_all_images_toggle(self):
        is_checked = self.var_select_all_images.get()
        for var in self.img_ext_vars.values(): var.set(is_checked)
        self.receive_update()

    def _update_select_all_checkbox_state(self):
        all_checked = all(var.get() for ext, var in self.img_ext_vars.items() if ext in IMAGE_EXTS)
        self.var_select_all_images.set(all_checked)

    def _get_settings_as_dict(self):
        settings = { 
            "format": self.var_format.get(), "quality": self.var_quality.get(), 
            "max_quality_detail": self.var_max_quality_detail.get(), 
            "keep_exif": self.var_keep_exif.get(), # Save exif setting
            "output_mode": self.var_output_mode.get(), "output_dir": self.var_output_dir.get(), 
            "resize_enabled": self.var_resize_enabled.get(), "resize_mode": self.var_resize_mode.get(), 
            "width": self.var_width.get(), "height": self.var_height.get(), 
            "keep_ratio": self.var_keep_ratio.get(), "aspect_ratio": self.var_aspect_ratio.get(), 
            "scale_rule": self.var_scale_rule.get(), "warn_overwrite": self.var_warn_overwrite.get(), 
            "notify_complete": self.var_notify_complete.get() 
        }
        settings['img_exts'] = {ext: var.get() for ext, var in self.img_ext_vars.items()}
        return settings
    
    def _apply_settings_from_dict(self, settings_dict):
        ext_settings = settings_dict.get('img_exts', {})
        for ext, value in ext_settings.items():
            if ext in self.img_ext_vars: self.img_ext_vars[ext].set(value)
        self._update_select_all_checkbox_state()

        for key, value in settings_dict.items():
            if key == 'img_exts': continue 
            var_name = f"var_{key}";
            if hasattr(self, var_name):
                try: getattr(self, var_name).set(value)
                except tk.TclError: pass
        self._toggle_resize_widgets()
        self.update_preview()

    def _load_config(self, startup=False):
        all_configs = self.app.load_app_config()
        pane_settings = all_configs.get(self.pane_name, self._get_settings_as_dict())
        self._apply_settings_from_dict(pane_settings)
        if not startup: self.app.log("ImagePane: 設定已載入。")
    
    def _save_config(self):
        all_configs = self.app.load_app_config()
        all_configs[self.pane_name] = self._get_settings_as_dict()
        self.app.save_app_config(all_configs)
        self.app.log("ImagePane: 設定已儲存。")
    
    def receive_update(self, data_state=None):
        if data_state is None: data_state = getattr(self.app, 'data_state', {})
        image_files = data_state.get("image_files", [])
        
        selected_exts = {ext for ext, var in self.img_ext_vars.items() if var.get()}
        filtered_files = [f for f in image_files if os.path.splitext(f)[1].lower() in selected_exts]

        self.image_details_list.clear()
        sorted_files = sorted(filtered_files, key=natural_sort_key)
        
        for f_path in sorted_files:
            details = {"path": f_path, "dims": "N/A", "size": 0}
            try:
                details["size"] = os.path.getsize(f_path)
                with Image.open(f_path) as img: details["dims"] = f"{img.width}x{img.height}"
            except Exception as e: self.app.log(f"無法讀取圖片資訊: {os.path.basename(f_path)} - {e}")
            self.image_details_list.append(details)
        
        if self.image_details_list:
            try:
                with Image.open(self.image_details_list[0]['path']) as img: self.original_aspect_ratio = img.width / img.height
            except Exception: self.original_aspect_ratio = 16 / 9.0
        
        self.update_preview(is_full_reload=True)
        self.app.log(f"圖像處理：篩選後共 {len(self.image_details_list)} 個圖片檔案。")
        
    def update_preview(self, event=None, is_full_reload=False):
            root_folder = getattr(self.app, 'data_state', {}).get("root_folder", ".")
            if is_full_reload:
                self.file_tree.delete(*self.file_tree.get_children())
                self.checked_state.clear()
            
            # Conflict detection logic (Future Path Prediction)
            future_paths = set()
            item_ids = self.file_tree.get_children('')
            for i, item_id in enumerate(item_ids):
                if not self.checked_state.get(item_id, False):
                    future_paths.add(self.image_details_list[i]["path"].lower())

            for i, details in enumerate(self.image_details_list):
                f_path = details["path"]
                base, ext = os.path.splitext(os.path.basename(f_path))
                target_format = self.var_format.get()
                new_ext = ext.lower() if target_format == "維持原格式" else "." + target_format.lower()
                
                output_mode = self.var_output_mode.get()
                dest_folder = os.path.dirname(f_path)

                if output_mode == "resized": dest_folder = os.path.join(dest_folder, "resized")
                elif output_mode == "custom": dest_folder = self.var_output_dir.get() or dest_folder
                
                final_name = f"{base}{new_ext}"
                final_path = os.path.join(dest_folder, final_name)
                
                # Resolve conflicts
                counter = 1
                base_name, ext_name = os.path.splitext(final_name)
                while final_path.lower() in future_paths:
                    final_name = f"{base_name}({counter}){ext_name}"
                    final_path = os.path.join(dest_folder, final_name)
                    counter += 1
                
                if self.checked_state.get(self.file_tree.get_children('')[i] if i < len(self.file_tree.get_children('')) else None, True):
                    future_paths.add(final_path.lower())

                original_rel_path = os.path.relpath(f_path, root_folder) if root_folder and os.path.commonpath([f_path, root_folder]) == root_folder else os.path.basename(f_path)
                new_rel_path = os.path.relpath(final_path, root_folder) if root_folder and os.path.commonpath([final_path, root_folder]) == root_folder else os.path.basename(final_path)
                values = ('☑', original_rel_path, new_rel_path, details["dims"], format_size(details["size"]))

                if is_full_reload:
                    item_id = self.file_tree.insert("", "end", values=values, tags=('checked',))
                    self.checked_state[item_id] = True
                else:
                    try:
                        item_id = self.file_tree.get_children('')[i]
                        if self.checked_state.get(item_id, False):
                            self.file_tree.set(item_id, column="new_path", value=new_rel_path)
                        else:
                            self.file_tree.set(item_id, column="new_path", value=original_rel_path)
                    except IndexError: pass

    def _toggle_resize_widgets(self):
        state = "normal" if self.var_resize_enabled.get() else "disabled"
        parent_frame = self.chk_resize_enabled.master
        def set_state_recursive(widget):
            if widget != self.chk_resize_enabled:
                try: widget.config(state=state)
                except tk.TclError: pass
            for child in widget.winfo_children(): set_state_recursive(child)
        set_state_recursive(parent_frame)
        
    def _on_resize_mode_change(self, event=None):
        if self.var_resize_mode.get() == "百分比": self.var_width.set("100"); self.var_height.set("100")
        else: self.var_width.set("1920"); self.var_height.set("1080"); self._on_aspect_ratio_change()
        
    def _on_aspect_ratio_change(self, event=None): self._on_dimension_change(event, "height")
    
    def _on_dimension_change(self, event, changed_field):
            if not (self.var_keep_ratio.get() and self.var_resize_mode.get() == "像素" and self.var_aspect_ratio.get() != "原始"): return
            ratio_map = { "16:9": 16/9.0, "9:16": 9/16.0, "4:3": 4/3.0, "3:4": 3/4.0, "3:2": 3/2.0, "2:3": 2/3.0, "16:10": 16/10.0, "1:1": 1.0 }
            aspect_ratio = ratio_map.get(self.var_aspect_ratio.get())
            if not aspect_ratio: return

            try:
                if changed_field == "width":
                    w_str = self.var_width.get()
                    if w_str.isdigit(): self.var_height.set(str(int(int(w_str) / aspect_ratio)))
                elif changed_field == "height":
                    h_str = self.var_height.get()
                    if h_str.isdigit(): self.var_width.set(str(int(int(h_str) * aspect_ratio)))
            except (ValueError, ZeroDivisionError): pass
            
    def _on_execute(self):
        # 1. Path Calculation
        final_path_map = {}
        future_paths = set()
        item_ids = self.file_tree.get_children('')

        for i, item_id in enumerate(item_ids):
            if i >= len(self.image_details_list): continue
            details = self.image_details_list[i]
            f_path = details["path"]
            
            if not self.checked_state.get(item_id, True):
                future_paths.add(f_path.lower())
                final_path_map[f_path] = f_path
                continue

            base, ext = os.path.splitext(os.path.basename(f_path))
            target_format = self.var_format.get()
            new_ext = ext.lower() if target_format == "維持原格式" else "." + target_format.lower()
            output_mode = self.var_output_mode.get()
            dest_folder = os.path.dirname(f_path)

            if output_mode == "resized": dest_folder = os.path.join(dest_folder, "resized")
            elif output_mode == "custom": dest_folder = self.var_output_dir.get() or dest_folder

            ideal_name = f"{base}{new_ext}"
            final_path = os.path.join(dest_folder, ideal_name)
            counter = 1
            base_name, ext_name = os.path.splitext(ideal_name)

            while final_path.lower() in future_paths:
                final_name = f"{base_name}({counter}){ext_name}"
                final_path = os.path.join(dest_folder, final_name)
                counter += 1
                
            future_paths.add(final_path.lower())
            final_path_map[f_path] = final_path

        # 2. Task Packaging
        tasks_to_run = []
        for i, item_id in enumerate(item_ids):
            if i >= len(self.image_details_list): continue
            if self.checked_state.get(item_id, False):
                original_path = self.image_details_list[i]['path']
                task_info = {
                    "details": self.image_details_list[i],
                    "final_path": final_path_map.get(original_path, original_path)
                }
                tasks_to_run.append(task_info)

        if not tasks_to_run: messagebox.showwarning("注意", "沒有勾選任何可處理的檔案。"); return
            
        if self.var_output_mode.get() == "overwrite" and self.var_warn_overwrite.get():
            if not messagebox.askyesno("重大警告", f"您選擇了【覆蓋原始檔案】！\n此操作將修改 {len(tasks_to_run)} 個檔案且無法復原，確定要繼續嗎？"): return
        
        settings = self._get_settings_as_dict()
        if settings["resize_enabled"]:
            w_str, h_str = settings["width"], settings["height"]
            if (not w_str.isdigit() and w_str != "") or (not h_str.isdigit() and h_str != ""):
                messagebox.showerror("輸入錯誤", "寬度或高度必須是有效的數字，或留白以自動計算。"); return

        self.btn_execute.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.pbar['value'] = 0
        self.cancel_event.clear()
        
        # 3. Worker Execution
        self.worker_thread = ImageWorker(tasks_to_run, settings, self.ui_queue, self.cancel_event)
        self.worker_thread.start()

    def _on_cancel(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.app.log("[圖像處理] 正在傳送取消訊號..."); self.cancel_event.set()
            self.btn_cancel.config(state="disabled")
            
    def _process_ui_queue(self):
            try:
                while not self.ui_queue.empty():
                    kind, payload = self.ui_queue.get_nowait()
                    if kind == "progress": self.pbar['value'] = payload
                    elif kind == "status": self.app.update_status(payload)
                    elif kind == "log": self.app.log(f"[圖像處理] {payload}")
                    elif kind == "summary": self.last_summary = payload
                    elif kind == "done":
                        (status_code, status_text), summary, temp_dirs_to_delete = payload
                        self.app.update_status(f"狀態：{status_text}")
                        self.app.log(f"\n{'-'*20}\n[圖像處理] 總結報告:\n{summary}\n{'-'*20}\n")

                        if self.var_notify_complete.get():
                            title = "任務報告"
                            if status_code == "cancel":
                                msg = "圖像處理任務已被使用者中斷。"
                                messagebox.showinfo(title, msg)
                                if temp_dirs_to_delete and messagebox.askyesno("清理確認", "任務已中斷，是否要刪除已產生的暫存備份 (.temp) 資料夾？"):
                                    self._cleanup_temp_dirs(temp_dirs_to_delete)
                            else:
                                msg = f"圖像處理任務已完成！\n\n{summary}"
                                messagebox.showinfo(title, msg)
                                self._cleanup_temp_dirs(temp_dirs_to_delete)
                        else:
                            if status_code == "ok": self._cleanup_temp_dirs(temp_dirs_to_delete)
                        
                        self.btn_execute.config(state="normal"); self.btn_cancel.config(state="disabled")
            finally: self.after(100, self._process_ui_queue)
                
    def _cleanup_temp_dirs(self, dirs_to_delete):
        if not dirs_to_delete: return
        for temp_dir in dirs_to_delete:
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                self.app.log(f"警告: 無法自動刪除暫存資料夾 {temp_dir}: {e}")

    def _browse_output_dir(self):
        path = filedialog.askdirectory(title="選擇自訂輸出資料夾")
        if path: self.var_output_dir.set(path); self.var_output_mode.set("custom"); self.update_preview()
        
    def _open_output_dir(self):
        path = self.var_output_dir.get()
        if path and os.path.isdir(path): os.startfile(path)
        else: messagebox.showwarning("注意", "自訂輸出路徑無效或不存在。")

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

    def _batch_update_check_state(self, selected_items):
        if not selected_items: return
        target_state = not self.checked_state.get(selected_items[0], False)
        for item_id in selected_items: self.checked_state[item_id] = target_state
        self._update_visual_check_state(selected_items, target_state)
        
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
    def _select_all(self): self._set_all_checks(True)
    def _clear_all(self): self._set_all_checks(False)

class ImageWorker(threading.Thread):
    def __init__(self, tasks_to_run, settings, ui_queue, cancel_event):
        super().__init__(daemon=True)
        self.tasks = tasks_to_run
        self.settings = settings
        self.ui_queue = ui_queue
        self.cancel_event = cancel_event
        self.total_original_size = 0
        self.total_processed_size = 0
        self.processed_count = 0
        self.start_time = time.time()

    def run(self):
        total_files = len(self.tasks)
        created_temp_dirs = set()

        for i, task_info in enumerate(self.tasks):
            if self.cancel_event.is_set(): break
            
            details = task_info["details"]
            output_path = task_info["final_path"]
            filepath, original_size = details["path"], details["size"]
            self.total_original_size += original_size
            
            try:
                is_overwrite_mode = self.settings["output_mode"] == "overwrite"
                backup_path = filepath

                if is_overwrite_mode:
                    parent_dir = os.path.dirname(filepath)
                    temp_dir = os.path.join(parent_dir, ".temp")
                    if not os.path.exists(temp_dir):
                        os.makedirs(temp_dir)
                        if os.name == 'nt':
                            try:
                                import ctypes; FILE_ATTRIBUTE_HIDDEN = 0x02
                                ctypes.windll.kernel32.SetFileAttributesW(temp_dir, FILE_ATTRIBUTE_HIDDEN)
                            except Exception: pass
                    created_temp_dirs.add(temp_dir)
                    backup_target_path = os.path.join(temp_dir, os.path.basename(filepath))
                    if os.path.exists(filepath): shutil.move(filepath, backup_target_path)
                    backup_path = backup_target_path

                with Image.open(backup_path) as img:
                    # Capture Exif before any operations
                    exif_data = img.info.get('exif')
                    
                    img = ImageOps.exif_transpose(img)
                    
                    if self.settings["resize_enabled"]:
                        w, h = img.size
                        sw, sh = w, h
                        resize_mode = self.settings["resize_mode"]
                        w_str = self.settings["width"]
                        h_str = self.settings["height"]
                        
                        try:
                            if resize_mode == "像素":
                                sw_val = int(w_str) if w_str.isdigit() else 0
                                sh_val = int(h_str) if h_str.isdigit() else 0
                                if self.settings["keep_ratio"] and w > 0 and h > 0:
                                    ratio = w / h
                                    if sw_val > 0 and sh_val <=0: sh_val = int(sw_val / ratio)
                                    elif sh_val > 0 and sw_val <=0: sw_val = int(sh_val * ratio)
                                sw, sh = sw_val, sh_val
                            elif resize_mode == "百分比":
                                percent_w = int(w_str) if w_str.isdigit() else 0
                                percent_h = int(h_str) if h_str.isdigit() else 0
                                if self.settings["keep_ratio"]:
                                    if percent_w > 0 and percent_h <= 0: percent_h = percent_w
                                    elif percent_h > 0 and percent_w <= 0: percent_w = percent_h
                                if percent_w <= 0: percent_w = 100
                                if percent_h <= 0: percent_h = 100
                                sw, sh = int(w * percent_w / 100), int(h * percent_h / 100)
                        except (ValueError, TypeError, ZeroDivisionError): sw, sh = w, h
                        
                        if not (sw > 0 and sh > 0): sw, sh = w, h
                        if self.settings["scale_rule"] == "僅縮小，不放大" and (sw > w or sh > h): sw, sh = w, h
                        if (sw, sh) != (w, h): img = img.resize((sw, sh), Image.Resampling.LANCZOS)
                    
                    save_options = {}
                    target_format_str = self.settings["format"]
                    output_format_name = img.format or "JPEG" if target_format_str == "維持原格式" else target_format_str

                    if output_format_name.upper() in ["JPEG", "JPG"]:
                        save_options['quality'] = self.settings["quality"]
                        if self.settings["quality"] >= 95 and self.settings["max_quality_detail"]: save_options['subsampling'] = 0
                        if img.mode in ("RGBA", "P"): img = img.convert("RGB")
                    elif output_format_name.upper() == "WEBP":
                        save_options['quality'] = self.settings["quality"]
                    
                    # Inject Exif if requested and available
                    if self.settings["keep_exif"] and exif_data:
                         save_options['exif'] = exif_data

                    os.makedirs(os.path.dirname(output_path), exist_ok=True)
                    img.save(output_path, **save_options)
                    
                    new_size = os.path.getsize(output_path)
                    self.total_processed_size += new_size
                    self.processed_count += 1
                    percent_change = ((new_size - original_size) / original_size) * 100 if original_size > 0 else 0
                    self.ui_queue.put(("log", f"成功: {os.path.basename(filepath)} ({format_size(original_size)} -> {format_size(new_size)}, {percent_change:+.1f}%)"))

            except Exception as e:
                self.ui_queue.put(("log", f"❌ 失敗: {os.path.basename(filepath)} - {e}"))
                if is_overwrite_mode and os.path.exists(backup_path):
                    try:
                        shutil.move(backup_path, filepath)
                        self.ui_queue.put(("log", f"還原: 已成功還原原始檔案 {os.path.basename(filepath)}"))
                    except Exception as move_back_e:
                        self.ui_queue.put(("log", f"嚴重錯誤: 無法還原檔案 {os.path.basename(filepath)}: {move_back_e}"))
            finally:
                self._update_status(i + 1, total_files, self.start_time)
        
        end_time = time.time()
        duration = end_time - self.start_time
        total_percent_change = ((self.total_processed_size - self.total_original_size) / self.total_original_size) * 100 if self.total_original_size > 0 else 0
        summary = (
            f"輸入檔案: {total_files}\n"
            f"成功處理: {self.processed_count}\n"
            f"總輸入大小: {format_size(self.total_original_size)}\n"
            f"總輸出大小: {format_size(self.total_processed_size)}\n"
            f"總大小比例: {total_percent_change:+.1f}%\n"
            f"總花費時間: {duration:.2f} 秒"
        )
        final_status_tuple = ("cancel", "任務已中斷 (備份未刪除)") if self.cancel_event.is_set() else ("ok", "完成")
        payload = (final_status_tuple, summary, list(created_temp_dirs))
        self.ui_queue.put(("done", payload))

    def _update_status(self, current, total, start_time):
        now = time.time()
        if now - getattr(self, 'last_update_time', 0) > 0.1:
            self.last_update_time = now
            elapsed = now - self.start_time
            speed = current / elapsed if elapsed > 0 else 0
            remaining_items = total - current
            eta_str = "..."
            if speed > 0:
                eta = remaining_items / speed
                eta_str = f"{int(eta // 60)} 分 {int(eta % 60)} 秒" if eta > 60 else f"{eta:.1f} 秒"
            self.ui_queue.put(("progress", int((current / total) * 100)))
            self.ui_queue.put(("status", f"處理中... ({current}/{total}, 剩餘 {remaining_items:,} 個, 預計 {eta_str})"))

if __name__ == '__main__':
    root = ensure_tk_with_dnd()
    root.title("Image Processing Pane - Standalone Test")
    root.geometry("800x850")
    class MockApp:
        def __init__(self):
            self.root = root; self.app_dir = '.'
            self.data_state = {}
            self.status_label = tk.Label(root, text="Mock Status...")
            self.status_label.pack(side="bottom", fill="x")
        def log(self, msg): print(f"[MOCK LOG] {msg}")
        def update_status(self, text): self.status_label.config(text=text); print(f"[MOCK STATUS] {text}")
        def load_app_config(self): 
            try:
                with open("mock_config.json", "r") as f: return json.load(f)
            except FileNotFoundError: return {}
        def save_app_config(self, cfg): 
            with open("mock_config.json", "w") as f: json.dump(cfg, f, indent=2)
        def _on_drop(self, event):
            folder = event.data.strip("{}")
            if os.path.isdir(folder):
                self.data_state = {"root_folder": folder}
                threading.Thread(target=self._scan_folder, daemon=True).start()
        def _scan_folder(self):
            image_files = []
            root_folder = self.data_state.get("root_folder")
            if not root_folder: return
            for r, _, f_list in os.walk(root_folder):
                for f in f_list:
                    if os.path.splitext(f)[1].lower() in IMAGE_EXTS: 
                        image_files.append(os.path.join(r, f))
            self.data_state["image_files"] = image_files
            self.root.after(0, self._notify_panes)
        def _notify_panes(self):
            if hasattr(self, 'pane_instance'): self.pane_instance.receive_update(self.data_state)
    mock_app = MockApp()
    frame_drag = tk.LabelFrame(root, text="[MOCK] Drop Zone for Standalone Test"); frame_drag.pack(fill="x", padx=10, pady=10)
    label_drag = tk.Label(frame_drag, text="📂 Drop a folder of images here", height=4); label_drag.pack(fill="x", expand=True)
    label_drag.drop_target_register(DND_FILES); label_drag.dnd_bind("<<Drop>>", mock_app._on_drop)
    pane = ImageProcessingPane(root, mock_app); pane.pack(fill="both", expand=True)
    mock_app.pane_instance = pane
    root.mainloop()