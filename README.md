# FileProsApp v4.1 - Professional File Organizer

A modular desktop application based on Python, featuring an architecture that separates the "Data Center" from the "Operation Panels." Designed to provide batch processing, format conversion, and automated naming solutions for complex file management workflows.

## Core Architecture

The system operates as a single main process where all functional modules share a central **Drop Zone** and **Global State**, ensuring consistency in operations and efficient data flow across modules.
* **Interface Optimization**: Optimized for modern screens with a 720x1080 vertical layout.

## Functional Modules

### 1. File Command Center
The core module for file naming and management, powered by a dual-layer logic engine.

* **Sequence Engine**:
    * Independent control for image and video files.
    * Supports custom prefixes, starting values, and zero-padding digits.
    * Features group processing capabilities, supporting independent counting for sub-directories or global continuous counting.
* **String Manipulation Engine**:
    * Adds prefixes/suffixes.
    * Supports keyword search, deletion, and replacement.
* **Scope Control**:
    * Features a **"Flatten"** function to reorganize file structures based on "Root First," "Top Level First," or "Sub Level First" logic.
* **Dual-Slot Memory**:
    * Provides Slot 1 / Slot 2 for quick saving and loading of current naming rule configurations.
* **Future Path Prediction**:
    * Calculates file conflicts in real-time during preview to automatically avoid duplicate filenames.

### 2. Video Processing Pane
A module introduced in v4.0, focused on batch conversion and processing of video files.

* **Format Conversion**: Supports mutual conversion between mainstream containers like MP4, MKV, MOV, GIF, and AVI.
* **Smart Encoding**:
    * **CRF (Constant Rate Factor)**: Offers visual quality factor adjustment from 14 to 38.
    * **NVENC Acceleration**: Supports NVIDIA hardware encoding acceleration (H.264/HEVC).
    * **10-bit Color Depth**: Supports High Dynamic Range imaging (requires NVENC).
    * **Auto-Fallback Mechanism**: Automatically switches back to CPU decoding when resizing is enabled to ensure filter accuracy.
* **Audio Processing**: Defaults to keeping the original audio track (Copy), with options to remove audio or transcode to AAC.

### 3. Image Processing
* **Format Conversion**: Supports batch conversion between JPG, PNG, and WEBP.
* **Resizing**:
    * Supports scaling by **Pixel** or **Percentage**.
    * Built-in **Aspect Ratio Lock** with presets for common ratios (16:9, 4:3, etc.).
    * Utilizes the high-quality **LANCZOS** resampling algorithm.
* **Output Management**: Supports overwriting original files, outputting to a `resized` sub-directory, or a custom path.

### 4. Folder Organizer
* Batch renaming for directory structures.
* Supports string addition, search, and replacement.
* **Deepest-First Processing**: Automatically processes the deepest sub-directories first to prevent index errors caused by path renaming.

### 5. Folder Deleter
* **I/O Optimization**: Uses independent threads and batch log writing to prevent interface freezing.
* **Safety Boundaries**: Hard-coded restrictions prevent the deletion of system root directories (e.g., C:\) and user home directories.
* **Progress Visualization**: Provides remaining item count and Estimated Time of Arrival (ETA).

## Project Structure

``text
FileProsApp/
│
├── 📜 README.md         # Technical Documentation
├── 🚀 main.py           # Application Entry Point
│
├── 📁 file_pane.py      # File Naming Module
├── 🎬 video_pane.py     # Video Processing Module
├── 🎨 image_pane.py     # Image Processing Module
├── 📂 folder_pane.py    # Folder Management Module
├── 💥 delete_pane.py    # Deletion & Cleanup Module
│
└── 🛠️ utils.py          # Shared Utilities Library

## Component Versions

| Component File | Version | Status |
| :--- | :--- | :--- |
| `main.py` | `4.1.1` | **Major Update** |
| `file_pane.py` | `2.9.6` | Stable |
| `video_pane.py`| `1.4.0` | **Feature-Rich** |
| `image_pane.py`| `2.5.1` | Updated |
| `folder_pane.py`| `2.2.0` | Stable |
| `delete_pane.py`| `2.0.1` | Maintenance |
| `utils.py` | `2.2.0` | Core Lib |

## Requirements

* **Python**: Version 3.8 or higher
* **System Packages**:
    * [FFmpeg](https://ffmpeg.org/) (Must be installed and added to the system PATH, or placed in the application root directory for video processing features)
* **Python Dependencies**:
    ```bash
    pip install Pillow tkinterdnd2
    ```

## Execution

1.  Ensure FFmpeg is correctly installed.
2.  Install the required Python dependencies mentioned above.
3.  Run the main program via terminal:
    ```bash
    python main.py
    ```