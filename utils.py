# utils.py
# version: 2.2.0
__version__ = "2.2.0"

import re
import tkinter as tk
from tkinter import ttk
from tkinterdnd2 import TkinterDnD

# 應用程式所支援的圖片副檔名白名單 (修改後會自動更新UI與掃描範圍)
# 潛在可用格式 (若要啟用，請剪下貼到上方列表。注意：部分格式可能需安裝額外Pillow插件):
#  '.heic', '.heif', '.avif', '.psd', '.jp2'
IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp', '.tiff', '.tif', '.ico']

# [修正] 補齊常見視訊格式，包含 avi
VIDEO_EXTS = ['.mp4', '.mov', '.mkv', '.webm', '.avi', '.wmv', '.flv', '.m4v']

def format_size(size_bytes):
    if size_bytes == 0: return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', str(s))]

def ensure_tk_with_dnd():
    try:
        root = TkinterDnD.Tk()
    except Exception as e:
        print(f"Error initializing TkinterDnD: {e}")
        root = tk.Tk()
    return root

def create_scrollable_treeview(parent_frame):
    container = ttk.Frame(parent_frame)
    scrollbar = ttk.Scrollbar(container)
    scrollbar.pack(side="right", fill="y")
    treeview = ttk.Treeview(container, yscrollcommand=scrollbar.set)
    scrollbar.config(command=treeview.yview)
    treeview.pack(side="left", fill="both", expand=True)
    return container, treeview