# video_pane.py
# version: 1.4.0 (Fix NVENC Quality Control & 10-bit Logic)
__version__ = "1.4.0"

import os
import sys
import queue
import threading
import time
import subprocess
import shutil
import re
import json
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    from utils import VIDEO_EXTS, format_size, create_scrollable_treeview, natural_sort_key, ensure_tk_with_dnd
except ImportError:
    # Fallback definitions for standalone testing
    VIDEO_EXTS = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v']
    def format_size(size_bytes):
        if size_bytes == 0: return "0 B"
        size_name = ("B", "KB", "MB", "GB", "TB")
        i = int(__import__("math").floor(__import__("math").log(size_bytes, 1024)))
        p = __import__("math").pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_name[i]}"
    def natural_sort_key(s):
        import re
        return [int(c) if c.isdigit() else c.lower() for c in re.split('([0-9]+)', s)]
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
    def ensure_tk_with_dnd():
        try: from tkinterdnd2 import TkinterDND; return TkinterDND.Tk()
        except ImportError: return tk.Tk()

def get_ffmpeg_path():
    if getattr(sys, 'frozen', False):
        bundled_path = os.path.join(sys._MEIPASS, 'ffmpeg.exe')
        if os.path.exists(bundled_path): return bundled_path
    local_path = os.path.join(os.getcwd(), 'ffmpeg.exe')
    if os.path.exists(local_path): return local_path
    return "ffmpeg"

class VideoOrganizerPane(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.pane_name = "video_pane"
        self.worker_thread = None
        self.ui_queue = queue.Queue()
        self.video_details_list = []
        self.cancel_event = threading.Event()
        self.last_summary = ""
        
        self.checked_state = {}
        self.last_clicked_item = None
        
        self.ffmpeg_exe = get_ffmpeg_path()
        self.ffmpeg_available = self._check_ffmpeg()

        self._setup_ui_variables()
        self._build_ui()
        self._load_config()

        if not self.ffmpeg_available:
            self.app.log(f"⚠️ 警告: 未偵測到 FFmpeg (嘗試路徑: {self.ffmpeg_exe})")
            self.app.update_status("⚠️ 錯誤: 找不到 FFmpeg，請安裝或將其放入程式目錄")
        
        self.after(100, self._process_ui_queue)

    def _check_ffmpeg(self):
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            subprocess.run([self.ffmpeg_exe, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, startupinfo=startupinfo)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            return False

    def _setup_ui_variables(self):
        self.var_format = tk.StringVar(value="MP4")
        self.var_crf = tk.IntVar(value=23) 
        self.var_preset = tk.StringVar(value="medium")
        self.var_audio_codec = tk.StringVar(value="Keep") 
        self.var_10bit = tk.BooleanVar(value=False)
        self.var_crf_desc = tk.StringVar(value="初始化中...")
        self.var_preset_desc = tk.StringVar(value="初始化中...")

        self.var_output_mode = tk.StringVar(value="subfolder") 
        self.var_output_dir = tk.StringVar()
        self.var_subfolder_name = tk.StringVar(value="converted")

        self.var_resize_enabled = tk.BooleanVar(value=False)
        self.var_resize_mode = tk.StringVar(value="百分比")
        self.var_width = tk.StringVar(value="100")
        self.var_height = tk.StringVar(value="100")
        self.var_keep_ratio = tk.BooleanVar(value=True)
        self.var_fps_limit = tk.StringVar(value="維持原始")

        self.var_warn_overwrite = tk.BooleanVar(value=True)
        self.var_notify_complete = tk.BooleanVar(value=True)
        self.var_select_all_videos = tk.BooleanVar(value=True)
        self.vid_ext_vars = {ext: tk.BooleanVar(value=True) for ext in VIDEO_EXTS}

        self._update_crf_info()
        self._update_preset_info()

    def _build_ui(self):
        main_frame = ttk.LabelFrame(self, text=f"影片壓縮工坊 v{__version__}")
        main_frame.pack(fill="both", expand=True, padx=5, pady=5)

        control_panel = ttk.Frame(main_frame)
        control_panel.pack(fill="x", pady=5, padx=5)
        control_panel.columnconfigure(0, weight=1)
        control_panel.columnconfigure(1, weight=1)

        left_frame = ttk.LabelFrame(control_panel, text="輸出格式與畫質")
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self._build_quality_controls(left_frame)

        right_frame = ttk.LabelFrame(control_panel, text="畫面調整與其他")
        right_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self._build_resize_controls(right_frame)

        out_frame = ttk.Frame(main_frame)
        out_frame.pack(fill="x", padx=10, pady=(5, 0))
        ttk.Label(out_frame, text="輸出位置:").pack(side="left")
        ttk.Radiobutton(out_frame, text="覆蓋原檔", variable=self.var_output_mode, value="overwrite", command=self._update_ui_state).pack(side="left", padx=5)
        ttk.Radiobutton(out_frame, text="存到子資料夾:", variable=self.var_output_mode, value="subfolder", command=self._update_ui_state).pack(side="left", padx=5)
        self.entry_subfolder = ttk.Entry(out_frame, textvariable=self.var_subfolder_name, width=10); self.entry_subfolder.pack(side="left")
        ttk.Radiobutton(out_frame, text="自訂目錄:", variable=self.var_output_mode, value="custom", command=self._update_ui_state).pack(side="left", padx=5)
        self.entry_custom_dir = ttk.Entry(out_frame, textvariable=self.var_output_dir, width=20); self.entry_custom_dir.pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(out_frame, text="..", command=self._browse_output_dir, width=3).pack(side="left", padx=(2,0))
        ttk.Button(out_frame, text="📂", command=self._open_output_dir, width=3).pack(side="left", padx=(2,0))

        settings_frame = ttk.Frame(main_frame)
        settings_frame.pack(fill="x", padx=10, pady=5)
        ttk.Checkbutton(settings_frame, text="覆蓋前警告", variable=self.var_warn_overwrite).pack(side="left")
        ttk.Checkbutton(settings_frame, text="完成後提示", variable=self.var_notify_complete).pack(side="left", padx=10)
        ttk.Button(settings_frame, text="儲存設定", command=self._save_config).pack(side="right")

        filter_frame = ttk.LabelFrame(main_frame, text="副檔名篩選")
        filter_frame.pack(fill="x", padx=10, pady=(0, 5))
        filter_inner = ttk.Frame(filter_frame)
        filter_inner.pack(fill="x", padx=5, pady=5)
        ttk.Checkbutton(filter_inner, text="影片類型:", variable=self.var_select_all_videos, command=self._toggle_all_exts).pack(side="left", padx=(0, 10))
        for ext in sorted(VIDEO_EXTS):
            if ext in self.vid_ext_vars:
                ttk.Checkbutton(filter_inner, text=ext, variable=self.vid_ext_vars[ext], command=self.receive_update).pack(side="left")

        preview_frame = ttk.LabelFrame(main_frame, text="檔案預覽列表")
        preview_frame.pack(fill="both", expand=True, padx=10, pady=(5, 0)) 
        tree_container, self.file_tree = create_scrollable_treeview(preview_frame)
        tree_container.pack(fill="both", expand=True) 
        
        cols = ("checked", "original", "new", "size", "status")
        self.file_tree.configure(columns=cols, show="headings")
        self.file_tree.heading("checked", text="✔"); self.file_tree.column("checked", width=40, anchor="center", stretch=False)
        self.file_tree.heading("original", text="原檔案路徑"); self.file_tree.column("original", width=250, anchor="w")
        self.file_tree.heading("new", text="新檔案名稱 (預覽)"); self.file_tree.column("new", width=250, anchor="w")
        self.file_tree.heading("size", text="檔案大小"); self.file_tree.column("size", width=100, anchor="e")
        self.file_tree.heading("status", text="狀態/備註"); self.file_tree.column("status", width=120, anchor="center")
        self.file_tree.tag_configure('checked', foreground='blue')
        self.file_tree.bind('<Button-1>', self._on_tree_click)
        self.file_tree.bind('<space>', self._on_space_press)

        exec_frame = ttk.Frame(main_frame)
        exec_frame.pack(fill="x", padx=10, pady=10)
        btn_box = ttk.Frame(exec_frame); btn_box.pack(side="left")
        ttk.Button(btn_box, text="✔", width=3, command=self._toggle_selection_check).pack(side="left")
        ttk.Button(btn_box, text="全選", command=self._select_all).pack(side="left", padx=5)
        ttk.Button(btn_box, text="清除", command=self._clear_all).pack(side="left")
        self.pbar = ttk.Progressbar(exec_frame); self.pbar.pack(side="left", fill="x", expand=True, padx=10)
        self.btn_run = ttk.Button(exec_frame, text="開始壓制", command=self._on_execute); self.btn_run.pack(side="left")
        self.btn_cancel = ttk.Button(exec_frame, text="取消", command=self._on_cancel, state="disabled"); self.btn_cancel.pack(side="left", padx=(5,0))
        
        self._update_ui_state()

    def _build_quality_controls(self, parent):
        f = ttk.Frame(parent); f.pack(fill="x", padx=5, pady=5)
        
        r1 = ttk.Frame(f); r1.pack(fill="x", pady=2)
        ttk.Label(r1, text="目標格式:").pack(side="left")
        ttk.Combobox(r1, textvariable=self.var_format, values=["MP4", "MKV", "MOV", "GIF", "AVI"], width=10, state="readonly").pack(side="left", padx=5)
        ttk.Checkbutton(r1, text="10-bit (高動態)", variable=self.var_10bit).pack(side="left", padx=5)
        
        r2 = ttk.Frame(f); r2.pack(fill="x", pady=(10, 0))
        ttk.Label(r2, text="視覺品質 (CRF/CQ):").pack(anchor="w")
        
        slider_container = ttk.Frame(f)
        slider_container.pack(fill="x", pady=(0, 0))
        self.scale_crf = ttk.Scale(slider_container, from_=14, to=38, variable=self.var_crf, orient="horizontal", command=self._on_crf_scale_move)
        self.scale_crf.pack(side="left", fill="x", expand=True)
        
        self.entry_crf = ttk.Entry(slider_container, textvariable=self.var_crf, width=4, justify="center", font=("Arial", 10, "bold"))
        self.entry_crf.pack(side="left", padx=5)
        self.entry_crf.bind("<KeyRelease>", self._on_crf_entry_input)

        tick_frame = tk.Frame(f, height=35) 
        tick_frame.pack(fill="x", pady=(0, 5))
        ticks = [(14, 0.0, "14"), (18, 0.166, "18"), (23, 0.375, "23"), (28, 0.583, "28"), (34, 0.833, "34")]
        for val, relx, text in ticks:
            adj_relx = 0.01 + (relx * 0.93)
            lbl = tk.Label(tick_frame, text=f"|\n{text}", font=("Arial", 7), fg="gray")
            lbl.place(relx=adj_relx, y=0, anchor="n")

        lbl_desc = ttk.Label(f, textvariable=self.var_crf_desc, foreground="#555", wraplength=320, justify="left")
        lbl_desc.pack(fill="x", pady=(0, 8))

        r3 = ttk.Frame(f); r3.pack(fill="x", pady=2)
        ttk.Label(r3, text="處理速度:").pack(side="left")
        cb_preset = ttk.Combobox(r3, textvariable=self.var_preset, values=["ultrafast", "superfast", "veryfast", "medium", "slow", "GPU (NVENC)"], width=12, state="readonly")
        cb_preset.pack(side="left", padx=5)
        cb_preset.bind("<<ComboboxSelected>>", self._update_preset_info)

        lbl_preset_info = ttk.Label(r3, textvariable=self.var_preset_desc, foreground="gray", font=("微軟正黑體", 8))
        lbl_preset_info.pack(side="left", padx=5)

        r4 = ttk.Frame(f); r4.pack(fill="x", pady=5)
        ttk.Label(r4, text="音訊處理:").pack(side="left")
        ttk.Combobox(r4, textvariable=self.var_audio_codec, values=["Keep", "AAC", "No Audio"], width=8, state="readonly").pack(side="left", padx=5)

    def _build_resize_controls(self, parent):
        f = ttk.Frame(parent); f.pack(fill="x", padx=5, pady=5)
        ttk.Checkbutton(f, text="啟用調整大小", variable=self.var_resize_enabled, command=self._update_ui_state).pack(anchor="w")
        
        r1 = ttk.Frame(f); r1.pack(fill="x", pady=2)
        ttk.Label(r1, text="模式:").pack(side="left")
        self.cb_resize_mode = ttk.Combobox(r1, textvariable=self.var_resize_mode, values=["百分比", "像素"], width=8, state="readonly")
        self.cb_resize_mode.pack(side="left", padx=5)
        self.cb_resize_mode.bind("<<ComboboxSelected>>", self._on_resize_mode_change)

        r2 = ttk.Frame(f); r2.pack(fill="x", pady=2)
        ttk.Label(r2, text="W:").pack(side="left")
        self.ent_w = ttk.Entry(r2, textvariable=self.var_width, width=6)
        self.ent_w.pack(side="left", padx=2)
        
        ttk.Label(r2, text="H:").pack(side="left")
        self.ent_h = ttk.Entry(r2, textvariable=self.var_height, width=6)
        self.ent_h.pack(side="left", padx=2)
        
        ttk.Checkbutton(f, text="保持比例 (自動計算)", variable=self.var_keep_ratio).pack(anchor="w", pady=2)
        
        r3 = ttk.Frame(f); r3.pack(fill="x", pady=5)
        ttk.Label(r3, text="FPS限制:").pack(side="left")
        self.cb_fps = ttk.Combobox(r3, textvariable=self.var_fps_limit, values=["維持原始", "30", "60", "24"], width=8, state="readonly")
        self.cb_fps.pack(side="left", padx=5)

    def _on_crf_scale_move(self, value):
        val = float(value)
        snapping_points = [14, 18, 23, 28, 34] 
        threshold = 0.6 
        snapped = False
        for p in snapping_points:
            if abs(val - p) < threshold:
                self.var_crf.set(p); snapped = True; break
        if not snapped: self.var_crf.set(int(val))
        self._update_crf_info()

    def _on_crf_entry_input(self, event):
        try:
            val = self.var_crf.get()
            if 14 <= val <= 38: self.scale_crf.set(val)
            self._update_crf_info()
        except tk.TclError: pass

    def _update_crf_info(self, event=None):
        try: val = self.var_crf.get()
        except: val = 23
        if val < 14: desc = "🦄 傳說級畫質 (近乎無損) | 檔案巨大"
        elif val <= 16: desc = "👑 視覺無損 (極致畫質) | 檔案較大"
        elif val <= 20: desc = "💎 高畫質 (推薦收藏) | 預估原檔 50%~80%"
        elif val <= 25: desc = "⚖️ 標準平衡 (預設) | 預估原檔 30%~50%"
        elif val <= 30: desc = "📉 有感壓縮 (傳輸用) | 預估原檔 15%~30%"
        else: desc = "💾 極限瘦身 (極小檔) | 預估原檔 <15%"
        self.var_crf_desc.set(desc)

    def _update_preset_info(self, event=None):
        val = self.var_preset.get()
        info_map = {
            "ultrafast": "ℹ 🚀 極速：最快，但檔案較大",
            "superfast": "ℹ ⚡ 超快：適合快速預覽",
            "veryfast": "ℹ 🐇 很快：常用的快速選項",
            "medium": "ℹ ⚖️ 平衡：推薦的預設值",
            "slow": "ℹ 🐢 高壓：最慢，但檔案最小",
            "GPU (NVENC)": "ℹ 🎮 硬體加速：使用 Nvidia 顯卡飆速"
        }
        self.var_preset_desc.set(info_map.get(val, ""))

    def _update_ui_state(self):
        state = "normal" if self.var_resize_enabled.get() else "disabled"
        self.cb_resize_mode.config(state=state)
        self.ent_w.config(state=state)
        self.ent_h.config(state=state)
        self.cb_fps.config(state=state)
        mode = self.var_output_mode.get()
        self.entry_subfolder.config(state="normal" if mode == "subfolder" else "disabled")
        self.entry_custom_dir.config(state="normal" if mode == "custom" else "disabled")
        self.update_preview()

    def _on_resize_mode_change(self, event=None):
        if self.var_resize_mode.get() == "百分比":
            self.var_width.set("100"); self.var_height.set("100")
        else:
            self.var_width.set("1920"); self.var_height.set("1080")

    def _toggle_all_exts(self):
        val = self.var_select_all_videos.get()
        for var in self.vid_ext_vars.values(): var.set(val)
        self.receive_update()

    def receive_update(self, data_state=None):
        if data_state is None: data_state = getattr(self.app, 'data_state', {})
        raw_videos = data_state.get("video_files", [])
        active_exts = {ext for ext, var in self.vid_ext_vars.items() if var.get()}
        filtered = [f for f in raw_videos if os.path.splitext(f)[1].lower() in active_exts]
        self.video_details_list = sorted(filtered, key=natural_sort_key)
        self.app.log(f"VideoPane: 載入 {len(self.video_details_list)} 個影片檔案。")
        self.update_preview(full_reload=True)

    def update_preview(self, full_reload=False):
        if full_reload:
            self.file_tree.delete(*self.file_tree.get_children())
            self.checked_state.clear()
        root_folder = getattr(self.app, 'data_state', {}).get("root_folder", ".")
        mode = self.var_output_mode.get()
        target_ext = "." + self.var_format.get().lower()

        for i, f_path in enumerate(self.video_details_list):
            try: size_str = format_size(os.path.getsize(f_path))
            except: size_str = "Unknown"
            fname = os.path.basename(f_path)
            base, _ = os.path.splitext(fname)
            new_fname = base + target_ext
            dest_dir = os.path.dirname(f_path)
            if mode == "subfolder": dest_dir = os.path.join(dest_dir, self.var_subfolder_name.get())
            elif mode == "custom": dest_dir = self.var_output_dir.get()
            try: display_orig = os.path.relpath(f_path, root_folder)
            except ValueError: display_orig = f_path
            display_new = new_fname
            if mode != "overwrite":
                 display_new = os.path.join(os.path.basename(dest_dir) if mode=="subfolder" else "Custom", new_fname)
            values = ("☑", display_orig, display_new, size_str, "待命")
            if full_reload:
                item = self.file_tree.insert("", "end", values=values, tags=('checked',))
                self.checked_state[item] = True
            else:
                children = self.file_tree.get_children()
                if i < len(children):
                    item = children[i]
                    current_values = list(self.file_tree.item(item, "values"))
                    current_values[2] = display_new
                    self.file_tree.item(item, values=current_values)

    def _get_settings_dict(self):
        return {
            "format": self.var_format.get(), "crf": self.var_crf.get(), "preset": self.var_preset.get(),
            "audio": self.var_audio_codec.get(), "output_mode": self.var_output_mode.get(),
            "subfolder": self.var_subfolder_name.get(), "custom_dir": self.var_output_dir.get(),
            "resize": self.var_resize_enabled.get(), "resize_mode": self.var_resize_mode.get(),
            "w": self.var_width.get(), "h": self.var_height.get(), "fps": self.var_fps_limit.get(),
            "exts": {k: v.get() for k, v in self.vid_ext_vars.items()},
            "10bit": self.var_10bit.get() 
        }

    def _load_config(self):
        cfg = self.app.load_app_config().get(self.pane_name, {})
        if not cfg: return
        try:
            self.var_format.set(cfg.get("format", "MP4"))
            self.var_crf.set(cfg.get("crf", 23))
            self.var_preset.set(cfg.get("preset", "medium"))
            audio_val = cfg.get("audio", "Keep")
            if audio_val == "copy": audio_val = "Keep"
            self.var_audio_codec.set(audio_val)
            self.var_output_mode.set(cfg.get("output_mode", "subfolder"))
            self.var_subfolder_name.set(cfg.get("subfolder", "converted"))
            self.var_output_dir.set(cfg.get("custom_dir", ""))
            self.var_resize_enabled.set(cfg.get("resize", False))
            self.var_resize_mode.set(cfg.get("resize_mode", "百分比"))
            self.var_width.set(cfg.get("w", "100"))
            self.var_height.set(cfg.get("h", "100"))
            self.var_fps_limit.set(cfg.get("fps", "維持原始"))
            self.var_10bit.set(cfg.get("10bit", False)) 
            exts = cfg.get("exts", {})
            for k, v in exts.items():
                if k in self.vid_ext_vars: self.vid_ext_vars[k].set(v)
        except Exception as e: self.app.log(f"VideoPane 設定載入部分失敗: {e}")
        self._update_crf_info(); self._update_preset_info(); self._update_ui_state()

    def _save_config(self):
        full_cfg = self.app.load_app_config()
        full_cfg[self.pane_name] = self._get_settings_dict()
        self.app.save_app_config(full_cfg)
        messagebox.showinfo("儲存", "影片處理設定已儲存！")

    def _on_execute(self):
        if not self.ffmpeg_available:
            messagebox.showerror("錯誤", "找不到 FFmpeg，無法執行。")
            return
        tasks = []
        children = self.file_tree.get_children()
        for i, item in enumerate(children):
            if self.checked_state.get(item, False) and i < len(self.video_details_list):
                tasks.append(self.video_details_list[i])
        if not tasks: messagebox.showwarning("提示", "未選擇任何檔案。"); return
        if self.var_output_mode.get() == "overwrite" and self.var_warn_overwrite.get():
             if not messagebox.askyesno("警告", "您選擇了【覆蓋原始檔案】！\n為了安全，系統將會把原始檔移動到 .temp 資料夾暫存。\n確定要繼續嗎？"): return
        self.btn_run.config(state="disabled"); self.btn_cancel.config(state="normal")
        self.cancel_event.clear()
        
        worker_settings = self._get_settings_dict()
        worker_settings["ffmpeg_path"] = self.ffmpeg_exe
        
        self.worker_thread = VideoWorker(tasks, worker_settings, self.ui_queue, self.cancel_event)
        self.worker_thread.start()

    def _on_cancel(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.cancel_event.set(); self.app.log("正在取消影片任務...")
            self.btn_cancel.config(state="disabled")

    def _process_ui_queue(self):
        try:
            while not self.ui_queue.empty():
                msg, payload = self.ui_queue.get_nowait()
                if msg == "progress": self.pbar['value'] = payload
                elif msg == "status": self.app.update_status(payload)
                elif msg == "log": self.app.log(payload)
                elif msg == "done":
                    (status_code, status_text), summary, temp_dirs_to_delete = payload
                    self.btn_run.config(state="normal"); self.btn_cancel.config(state="disabled"); self.pbar['value'] = 0
                    self.app.update_status(f"狀態：{status_text}")
                    self.app.log(f"\n{'-'*20}\n[影片處理] 總結報告:\n{summary}\n{'-'*20}\n")
                    if self.var_notify_complete.get():
                        title = "任務報告"
                        if status_code == "cancel":
                            msg = "影片處理任務已被使用者中斷。"
                            messagebox.showinfo(title, msg)
                            if temp_dirs_to_delete and messagebox.askyesno("清理確認", "任務已中斷，是否要刪除已產生的暫存備份 (.temp) 資料夾？"):
                                self._cleanup_temp_dirs(temp_dirs_to_delete)
                        else:
                            msg = f"影片處理任務已完成！\n\n{summary}"
                            messagebox.showinfo(title, msg)
                            self._cleanup_temp_dirs(temp_dirs_to_delete)
                    else:
                        if status_code == "ok": self._cleanup_temp_dirs(temp_dirs_to_delete)
        finally: self.after(100, self._process_ui_queue)

    def _cleanup_temp_dirs(self, dirs_to_delete):
        if not dirs_to_delete: return
        for temp_dir in dirs_to_delete:
            try:
                if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
            except Exception as e: self.app.log(f"警告: 無法自動刪除暫存資料夾 {temp_dir}: {e}")

    def _browse_output_dir(self):
        d = filedialog.askdirectory()
        if d: self.var_output_dir.set(d); self.var_output_mode.set("custom"); self._update_ui_state()

    def _open_output_dir(self):
        mode = self.var_output_mode.get()
        path_to_open = ""
        if mode == "custom": path_to_open = self.var_output_dir.get()
        elif mode == "subfolder":
            root = getattr(self.app, 'data_state', {}).get("root_folder", "")
            path_to_open = os.path.join(root, self.var_subfolder_name.get())
            if not os.path.exists(path_to_open): path_to_open = root
        elif mode == "overwrite":
            selected = self.file_tree.selection()
            if selected:
                try:
                    idx = self.file_tree.index(selected[0])
                    if idx < len(self.video_details_list): path_to_open = os.path.dirname(self.video_details_list[idx])
                except: pass
            if not path_to_open: path_to_open = getattr(self.app, 'data_state', {}).get("root_folder", "")
        if path_to_open and os.path.isdir(path_to_open): os.startfile(path_to_open)
        else: messagebox.showinfo("提示", f"無法開啟目錄: {path_to_open}")

    def _on_tree_click(self, event):
        region = self.file_tree.identify_region(event.x, event.y)
        if region != "cell" or self.file_tree.identify_column(event.x) != '#1': return
        item = self.file_tree.identify_row(event.y)
        if not item: return
        val = not self.checked_state.get(item, False)
        self.checked_state[item] = val
        self.file_tree.item(item, values=("☑" if val else "☐", *self.file_tree.item(item, "values")[1:]))
        if val: self.file_tree.item(item, tags=('checked',))
        else: self.file_tree.item(item, tags=())

    def _toggle_selection_check(self):
        for item in self.file_tree.selection():
             val = not self.checked_state.get(item, False)
             self.checked_state[item] = val
             self.file_tree.item(item, values=("☑" if val else "☐", *self.file_tree.item(item, "values")[1:]))
             if val: self.file_tree.item(item, tags=('checked',))
             else: self.file_tree.item(item, tags=())

    def _select_all(self):
        for item in self.file_tree.get_children(): 
            self.checked_state[item] = True
            self.file_tree.item(item, values=("☑", *self.file_tree.item(item, "values")[1:]), tags=('checked',))
    def _clear_all(self):
        for item in self.file_tree.get_children(): 
            self.checked_state[item] = False
            self.file_tree.item(item, values=("☐", *self.file_tree.item(item, "values")[1:]), tags=())
    def _on_space_press(self, e): self._toggle_selection_check()

class VideoWorker(threading.Thread):
    def __init__(self, tasks, settings, ui_queue, cancel_event):
        super().__init__(daemon=True)
        self.tasks = tasks; self.settings = settings; self.ui_queue = ui_queue; self.cancel_event = cancel_event
        self.total_original_size = 0
        self.total_processed_size = 0
        self.start_time = time.time()

    def run(self):
        total = len(self.tasks); success_count = 0
        created_temp_dirs = set()
        self.ui_queue.put(("log", f"開始處理 {total} 個影片任務..."))
        
        time_pattern = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        duration_pattern = re.compile(r"Duration: (\d+):(\d+):(\d+\.\d+)")

        for i, src_path in enumerate(self.tasks):
            if self.cancel_event.is_set(): break
            fname = os.path.basename(src_path)
            self.ui_queue.put(("status", f"正在處理 ({i+1}/{total}): {fname}"))
            
            try: self.total_original_size += os.path.getsize(src_path)
            except: pass

            dest_dir = os.path.dirname(src_path)
            mode = self.settings["output_mode"]
            if mode == "subfolder": dest_dir = os.path.join(dest_dir, self.settings["subfolder"])
            elif mode == "custom": dest_dir = self.settings["custom_dir"]
            if not os.path.exists(dest_dir): os.makedirs(dest_dir, exist_ok=True)
            target_ext = "." + self.settings["format"].lower()
            
            if mode == "overwrite":
                 temp_dir = os.path.join(dest_dir, ".temp")
                 if not os.path.exists(temp_dir):
                     os.makedirs(temp_dir)
                     if os.name == 'nt':
                         try:
                             import ctypes; FILE_ATTRIBUTE_HIDDEN = 0x02
                             ctypes.windll.kernel32.SetFileAttributesW(temp_dir, FILE_ATTRIBUTE_HIDDEN)
                         except: pass
                 created_temp_dirs.add(temp_dir)
                 final_dest_path = os.path.join(dest_dir, os.path.splitext(fname)[0] + target_ext)
                 temp_output = os.path.join(dest_dir, f"{os.path.splitext(fname)[0]}.temp{target_ext}")
                 dest_path = final_dest_path 
            else:
                 dest_path = os.path.join(dest_dir, os.path.splitext(fname)[0] + target_ext)
                 temp_output = dest_path

            cmd = self._build_ffmpeg_cmd(src_path, temp_output)
            
            try:
                startupinfo = None
                if os.name == 'nt': startupinfo = subprocess.STARTUPINFO(); startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                process = subprocess.Popen(
                    cmd, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    startupinfo=startupinfo, 
                    text=True, 
                    encoding='utf-8', 
                    errors='replace',
                    universal_newlines=True
                )
                
                total_duration_sec = 0
                start_time_real = time.time()
                
                while True:
                    if self.cancel_event.is_set(): process.terminate(); break
                    line = process.stderr.readline()
                    if not line and process.poll() is not None: break
                    
                    if line:
                        if "Duration:" in line and total_duration_sec == 0:
                            m = duration_pattern.search(line)
                            if m:
                                h, m, s = map(float, m.groups())
                                total_duration_sec = h*3600 + m*60 + s
                        
                        if "time=" in line:
                            m = time_pattern.search(line)
                            if m and total_duration_sec > 0:
                                h, m, s = map(float, m.groups())
                                current_sec = h*3600 + m*60 + s
                                
                                elapsed_real = time.time() - start_time_real
                                if elapsed_real > 0:
                                    speed_factor = current_sec / elapsed_real
                                    remaining_sec = (total_duration_sec - current_sec) / speed_factor
                                    eta_str = f"{int(remaining_sec//60)}分{int(remaining_sec%60)}秒"
                                    single_progress = (current_sec / total_duration_sec)
                                    total_progress = ((i + single_progress) / total) * 100
                                    
                                    self.ui_queue.put(("progress", int(total_progress)))
                                    status_msg = f"處理中 ({i+1}/{total}): {fname} | 進度 {int(single_progress*100)}% | 剩餘約 {eta_str} | 速度 {speed_factor:.1f}x"
                                    self.ui_queue.put(("status", status_msg))
                
                if process.returncode == 0 and not self.cancel_event.is_set():
                    if mode == "overwrite":
                        backup_path = os.path.join(temp_dir, fname)
                        if os.path.exists(src_path):
                            if os.path.exists(backup_path): 
                                try: os.remove(backup_path)
                                except: pass
                            shutil.move(src_path, backup_path)
                        if os.path.exists(temp_output):
                            shutil.move(temp_output, dest_path)
                    
                    try:
                        orig_size = 0
                        if mode == "overwrite": 
                            try: orig_size = os.path.getsize(os.path.join(temp_dir, fname))
                            except: pass
                        else:
                            orig_size = os.path.getsize(src_path)

                        new_size = os.path.getsize(dest_path)
                        self.total_processed_size += new_size
                        percent_change = ((new_size - orig_size) / orig_size) * 100 if orig_size > 0 else 0
                        self.ui_queue.put(("log", f"✔ 成功: {fname} ({format_size(orig_size)} ➜ {format_size(new_size)}, {percent_change:+.1f}%)"))
                    except: self.ui_queue.put(("log", f"✔ 成功: {fname}"))
                    success_count += 1
                else:
                    if not self.cancel_event.is_set(): self.ui_queue.put(("log", f"❌ 失敗: {fname}"))
                    if os.path.exists(temp_output): os.remove(temp_output)
            
            except Exception as e: self.ui_queue.put(("log", f"❌ 例外錯誤: {fname} - {e}"))
            self.ui_queue.put(("progress", int(((i+1)/total)*100)))

        end_time = time.time()
        duration = end_time - self.start_time
        total_change = ((self.total_processed_size - self.total_original_size) / self.total_original_size) * 100 if self.total_original_size > 0 else 0
        
        summary = (
            f"輸入檔案: {total}\n"
            f"成功處理: {success_count}\n"
            f"總輸入大小: {format_size(self.total_original_size)}\n"
            f"總輸出大小: {format_size(self.total_processed_size)}\n"
            f"總空間節省: {total_change:+.1f}%\n"
            f"總花費時間: {duration:.1f} 秒"
        )

        final_status = "cancel" if self.cancel_event.is_set() else "ok"
        final_msg = "任務已取消" if self.cancel_event.is_set() else "處理完成"
        self.ui_queue.put(("done", ((final_status, final_msg), summary, list(created_temp_dirs))))

    def _build_ffmpeg_cmd(self, src, dest):
        s = self.settings; ffmpeg_exe = s.get("ffmpeg_path", "ffmpeg")
        cmd = [ffmpeg_exe, "-y"]
        _, ext = os.path.splitext(src)
        
        # Exclude non-video formats from hardware acceleration
        if ext.lower() not in ['.gif', '.png', '.jpg', '.jpeg', '.bmp', '.webp']:
            cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])

        cmd.extend(["-i", src])
        
        if s["format"] == "GIF":
            cmd.extend(["-vf", f"fps={10 if s['fps']=='維持原始' else s['fps']},scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"])
            return cmd + [dest]
        
        video_codec = "libx264"; preset = s["preset"]
        is_gpu = preset == "GPU (NVENC)"; is_10bit = s.get("10bit", False)

        if is_gpu:
            if is_10bit: video_codec = "hevc_nvenc"; cmd.extend(["-pix_fmt", "p010le", "-profile:v", "main10"])
            else: video_codec = "h264_nvenc"; preset = "p4"
        elif is_10bit: cmd.extend(["-pix_fmt", "yuv420p10le", "-profile:v", "high10"])

        if is_gpu: cmd.extend(["-c:v", video_codec, "-rc", "constqp", "-qp", str(s["crf"]), "-preset", "p4" if preset == "p4" else preset])
        else: cmd.extend(["-c:v", video_codec, "-crf", str(s["crf"]), "-preset", preset])
        
        audio_setting = s["audio"]
        if audio_setting == "No Audio": cmd.append("-an")
        elif audio_setting == "AAC": cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        else: cmd.extend(["-c:a", "copy"])
        
        filters = []
        if s["fps"] != "維持原始": filters.append(f"fps={s['fps']}")
        
        if s["resize"]:
            # Resize incompatible with CUDA hwaccel output format; fallback to CPU decoding if resize needed
            if "-hwaccel" in cmd:
                if cmd[2] == "-hwaccel": del cmd[2:6] 

            if s["resize_mode"] == "百分比":
                try:
                    w_fac = float(s["w"]) / 100.0; h_fac = float(s["h"]) / 100.0
                    filters.append(f"scale=iw*{w_fac}:ih*{h_fac}")
                except: pass
            else:
                try:
                    w_digit = s["w"] if s["w"].isdigit() else "-2"
                    h_digit = s["h"] if s["h"].isdigit() else "-2"
                    if w_digit == "-2" and h_digit == "-2": w_digit = "1920"
                    filters.append(f"scale={w_digit}:{h_digit}")
                except: pass

        if filters: cmd.extend(["-vf", ",".join(filters)])
        cmd.append(dest)
        return cmd

if __name__ == "__main__":
    try: from utils import ensure_tk_with_dnd, VIDEO_EXTS
    except ImportError:
        VIDEO_EXTS = ['.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v']
        def ensure_tk_with_dnd():
            try: from tkinterdnd2 import TkinterDND; return TkinterDND.Tk()
            except ImportError: return tk.Tk()
    
    root = ensure_tk_with_dnd()
    root.title(f"Video Pane Standalone Test v{__version__}")
    root.geometry("800x950")

    class MockApp:
        def __init__(self, root_window):
            self.root = root_window; self.data_state = {"root_folder": "", "video_files": []}
            self.status_label = tk.Label(root_window, text="狀態：待機", bd=1, relief="sunken", anchor="w")
            self.status_label.pack(side="bottom", fill="x")
        def log(self, msg): print(f"[LOG] {msg}")
        def update_status(self, text): self.status_label.config(text=text); print(f"[STATUS] {text}")
        def load_app_config(self): return {}
        def save_app_config(self, cfg): print(f"[CONFIG] 設定已儲存: {cfg}")
    mock_app = MockApp(root)
    
    # Standalone drag & drop mock
    drop_frame = tk.LabelFrame(root, text="[獨立測試] 拖曳區")
    drop_frame.pack(fill="x", padx=10, pady=10)
    lbl_drop = tk.Label(drop_frame, text="📂 請將含有影片的資料夾拖曳至此", height=3, bg="#e0e0e0")
    lbl_drop.pack(fill="both", expand=True, padx=5, pady=5)
    
    def _on_drop_mock(event):
        paths = root.tk.splitlist(event.data)
        vid_files = []
        for p in paths:
             if os.path.isfile(p) and os.path.splitext(p)[1].lower() in VIDEO_EXTS: vid_files.append(p)
        if vid_files:
            mock_app.data_state = {"root_folder": os.path.dirname(vid_files[0]), "video_files": vid_files}
            pane.receive_update(mock_app.data_state)
            
    try:
        from tkinterdnd2 import DND_FILES
        lbl_drop.drop_target_register(DND_FILES); lbl_drop.dnd_bind("<<Drop>>", _on_drop_mock)
    except: pass

    pane = VideoOrganizerPane(root, mock_app)
    pane.pack(fill="both", expand=True)
    root.mainloop()