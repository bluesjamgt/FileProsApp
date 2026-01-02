# main.py
# version: 4.1.1 (Res 720x1080 & Fixed Layout Ratio)
__version__ = "4.1.1"

import os
import sys
import time
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog
from tkinterdnd2 import DND_FILES

# 引入各個模組
from file_pane import FileOrganizerPane
from folder_pane import FolderOrganizerPane
from image_pane import ImageProcessingPane
from video_pane import VideoOrganizerPane
from delete_pane import DeletePane
from utils import format_size, ensure_tk_with_dnd

sys.setrecursionlimit(2000)

class ModularOrganizerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"FilePros v{__version__} by Bluz J & Nai")
        
        # [修正 1] 解析度確認為 720x1080 (修長型)
        self.root.geometry("720x1080")
        
        self.app_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        self.config_path = os.path.join(self.app_dir, "config.json")

        self.data_state = { 
            "root_folder": "", 
            "all_files": [], "image_files": [], "video_files": [], "other_files": [], 
            "folders": [], "total_size": 0 
        }
        self.scan_queue = queue.Queue()
        
        self.panes = {}
        self.tab_buttons = {}

        self._build_ui()
        self.root.bind("<F5>", self._reload_folder)
        self.root.after(100, self._process_scan_queue)

    def load_app_config(self):
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            self.log(f"Error loading config file: {e}")
        return {}

    def save_app_config(self, all_configs):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(all_configs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"Error saving config file: {e}")

    def _build_ui(self):
        # 1. 拖曳區 (固定在頂部)
        frame_drag = tk.LabelFrame(self.root, text="[ 中央拖曳區 ]")
        frame_drag.pack(fill="x", padx=10, pady=(10,5))
        label_drag = tk.Label(frame_drag, text="📂", font=("Segoe UI Symbol", 28), height=1)
        label_drag.pack(fill="x", expand=True, padx=5, pady=5)
        label_drag.drop_target_register(DND_FILES)
        label_drag.dnd_bind("<<Drop>>", self._on_drop)

        # 2. 控制列 (固定在頂部)
        console_frame = ttk.Frame(self.root); console_frame.pack(fill="x", padx=10, pady=5)
        tab_bar = ttk.Frame(console_frame); tab_bar.pack(fill="x")
        
        btn_browse = ttk.Button(tab_bar, text="📂", command=self._browse_folder, width=3); btn_browse.pack(side="left", pady=(2,0), padx=(0,2))
        btn_reload = ttk.Button(tab_bar, text="🔃", command=self._reload_folder, width=3); btn_reload.pack(side="left", pady=(2,0), padx=(0,10))

        # [修正 2] 移除 PanedWindow，改回穩定的 Frame 佈局
        # 我們利用 pack 的順序來決定空間分配
        
        # 3. 狀態列 (最底部)
        footer_frame = ttk.Frame(self.root); footer_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 5))
        self.status_label = ttk.Label(footer_frame, text="狀態：待機"); self.status_label.pack(side="left")
        ttk.Label(footer_frame, text=f"Version: {__version__}").pack(side="right")

        # 4. 日誌區 (固定在底部，佔用較高空間)
        frame_log = tk.LabelFrame(self.root, text="共用日誌區")
        frame_log.pack(side="bottom", fill="x", padx=10, pady=5)

        # [修正 3] 日誌區高度設定
        # height=7 (視覺平衡調整)
        self.log_text = tk.Text(frame_log, height=7, state="disabled", wrap="none")
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar = tk.Scrollbar(frame_log, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scrollbar.set)

        # 5. 工作內容區 (佔用剩餘所有空間)
        # 這會自動把按鈕「頂」在日誌區的上方，不會被蓋住
        self.content_area = ttk.Frame(self.root)
        self.content_area.pack(side="top", fill="both", expand=True, padx=10)

        # --- 初始化 Pane ---
        self.panes["file"] = FileOrganizerPane(self.content_area, self)
        self.panes["folder"] = FolderOrganizerPane(self.content_area, self)
        self.panes["image"] = ImageProcessingPane(self.content_area, self)
        self.panes["video"] = VideoOrganizerPane(self.content_area, self)
        self.panes["delete"] = DeletePane(self.content_area, self, app_dir=self.app_dir)

        tabs_info = [
            ("file", "📁 檔案整理"), 
            ("folder", "📂 資料夾整理"), 
            ("image", "🎨 圖像處理"), 
            ("video", "🎬 影像處理"),
            ("delete", "💥 資料夾刪除")
        ]
        
        for key, text in tabs_info:
            # 使用 grid 來堆疊 pane
            pane = self.panes[key]
            pane.grid(row=0, column=0, sticky="nsew")
            
            button = ttk.Button(tab_bar, text=text, command=lambda p=pane: self._switch_tab(p))
            button.pack(side="left")
            self.tab_buttons[pane] = button
        
        # 讓 content_area 的 grid 能夠延展
        self.content_area.grid_rowconfigure(0, weight=1)
        self.content_area.grid_columnconfigure(0, weight=1)

        self._switch_tab(self.panes["file"])

    def _process_scan_queue(self):
        try:
            while not self.scan_queue.empty():
                msg_type, payload = self.scan_queue.get_nowait()
                if msg_type == "progress":
                    count = payload
                    dots = "." * (int(time.time() * 2) % 4)
                    self.update_status(f"掃描中，已發現 {count:,} 個檔案{dots}")
                elif msg_type == "done":
                    if payload: self.data_state.update(payload)
                    self._notify_panes()
        finally:
            self.root.after(100, self._process_scan_queue)

    def _on_drop(self, event):
        from utils import IMAGE_EXTS, VIDEO_EXTS
        paths = self.root.tk.splitlist(event.data)
        if not paths: return

        if len(paths) == 1 and os.path.isdir(paths[0]):
            folder = paths[0]
            self.data_state = { 
                "root_folder": folder, 
                "all_files": [], "image_files": [], "video_files": [], "other_files": [], 
                "folders": [], "total_size": 0 
            }
            self._notify_panes(clear_only=True)
            self.update_status(f"分析結構中... {folder}")
            self.root.update_idletasks()
            threading.Thread(target=self._scan_folder, daemon=True).start()
            return

        self.update_status("正在處理拖曳檔案...")
        all_files, img_files, vid_files, other_files = [], [], [], []
        folders = []
        total_size = 0

        for p in paths:
            if os.path.isfile(p):
                all_files.append(p)
                ext = os.path.splitext(p)[1].lower()
                if ext in IMAGE_EXTS: img_files.append(p)
                elif ext in VIDEO_EXTS: vid_files.append(p)
                else: other_files.append(p)
                try: total_size += os.path.getsize(p)
                except: pass
            elif os.path.isdir(p):
                folders.append(p)
                for r, _, fs in os.walk(p):
                    for f in fs:
                        f_path = os.path.join(r, f)
                        all_files.append(f_path)
                        try: total_size += os.path.getsize(f_path)
                        except: pass
                        ext = os.path.splitext(f)[1].lower()
                        if ext in IMAGE_EXTS: img_files.append(f_path)
                        elif ext in VIDEO_EXTS: vid_files.append(f_path)
                        else: other_files.append(f_path)
        
        if all_files:
            fake_root = os.path.dirname(paths[0]) if os.path.isfile(paths[0]) else paths[0]
            self.data_state = {
                "root_folder": fake_root,
                "all_files": all_files,
                "image_files": img_files,
                "video_files": vid_files,
                "other_files": other_files,
                "folders": folders,
                "total_size": total_size
            }
            self._notify_panes()
            if vid_files and not img_files:
                self._switch_tab(self.panes["video"])
                self.update_status(f"已載入 {len(vid_files)} 個影片 (自動切換至影像處理)")
            elif img_files and not vid_files:
                self._switch_tab(self.panes["image"])
                self.update_status(f"已載入 {len(img_files)} 個圖片 (自動切換至圖像處理)")
            else:
                self.update_status(f"已載入 {len(all_files)} 個項目")
        else:
            self.update_status("⚠️ 未偵測到支援的檔案類型。")

    def _scan_folder(self):
        from utils import IMAGE_EXTS, VIDEO_EXTS
        root_folder = self.data_state["root_folder"]
        all_files, img_files, vid_files, other_files, folders = [], [], [], [], []
        total_size = 0
        last_update_time = time.time()
        stack = [root_folder]
        try:
            while stack:
                current_dir = stack.pop()
                try:
                    with os.scandir(current_dir) as it:
                        for entry in it:
                            if entry.is_dir():
                                folders.append(entry.path); stack.append(entry.path)
                            elif entry.is_file():
                                f_path = entry.path; all_files.append(f_path)
                                try: total_size += entry.stat().st_size
                                except OSError: pass
                                ext = os.path.splitext(entry.name)[1].lower()
                                if ext in IMAGE_EXTS: img_files.append(f_path)
                                elif ext in VIDEO_EXTS: vid_files.append(f_path)
                                else: other_files.append(f_path)
                    if time.time() - last_update_time > 0.5:
                        self.scan_queue.put(("progress", len(all_files)))
                        last_update_time = time.time()
                except (PermissionError, OSError): continue

            final_data_state = { "all_files": all_files, "image_files": img_files, "video_files": vid_files, "other_files": other_files, "folders": folders, "total_size": total_size }
            self.scan_queue.put(("done", final_data_state))
        except Exception as e:
            self.log(f"掃描錯誤: {e}"); self.scan_queue.put(("done", {}))
            
    def _notify_panes(self, clear_only=False):
        if not clear_only and self.data_state["root_folder"]:
            pass
        for pane in self.panes.values():
            if hasattr(pane, 'receive_update'): pane.receive_update(self.data_state)
            
    def _switch_tab(self, target_pane):
        target_pane.tkraise()
        for pane, button in self.tab_buttons.items(): button.state(['!pressed', '!focus'])
        self.tab_buttons[target_pane].state(['pressed', 'focus'])

    def _browse_folder(self, event=None):
        folder = filedialog.askdirectory(title="選擇要處理的資料夾")
        if not folder: return
        class MockEvent:
            def __init__(self, data): self.data = data
        self._on_drop(MockEvent(f"{{{folder}}}"))

    def _reload_folder(self, event=None):
        folder = self.data_state.get("root_folder")
        if not folder or not os.path.isdir(folder): self.update_status("錯誤：沒有可重新載入的資料夾。"); return
        self.update_status(f"重新掃描中... {folder}"); self.root.update_idletasks()
        threading.Thread(target=self._scan_folder, daemon=True).start()

    def update_status(self, text: str): self.status_label.config(text=text)
    def log(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"[{time.strftime('%Y-%m-%d %H:%M')}] {message}\n")
        self.log_text.see("end"); self.log_text.config(state="disabled")

if __name__ == "__main__":
    root = ensure_tk_with_dnd()
    app = ModularOrganizerApp(root)
    root.mainloop()