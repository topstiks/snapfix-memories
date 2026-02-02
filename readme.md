# 📸 snapfix-memories

*A desktop tool to automatically repair and restore exported Snapchat Memories.*

---

### 🧩 Why This Exists

When you download your data from **Snapchat’s “My Data” portal**, your *Memories* come as a giant folder of **ZIP archives**.
Each ZIP usually contains:

* a `*-main.mp4` or `*-main.jpg` file — the actual snap, and
* a `*-overlay.png` image — the timestamp, text, or caption layer.

Unfortunately, these exports are messy:

* File names are inconsistent
* Some ZIPs have mismatched resolutions
* Metadata (“Date Created”) is missing or wrong | This is still WIP
* Not all memories are cleanly in 1 folder

**snapfix-memories** cleans all that up — automatically.

---

### ⚙️ What It Does

✅ Extracts every ZIP file in your export folder
✅ Finds the matching `*-main` and `*-overlay` files
✅ Correctly overlays the image on top of the snap
✅ Works with both **videos (.mp4)** and **photos (.jpg)**
✅ Auto-rescales overlays to match the main file size
✅ Restores the **oldest available timestamp** | Timestamps are corrently in
✅ Copies loose `.mp4` / `.png` files too
✅ Saves everything neatly to

> `Snapchat memories fixed/`

---

### 🚀 Getting Started

You can use **snapfix-memories** in two ways:

* Run the **prebuilt executable** (recommended if you don’t want to use the command line)
* Run the **Python script** directly

---

## 🖱️ Option 1: Run the Windows executable (no CLI needed)

If you’re not comfortable with Python or the command line, this is the easiest option.

1. Download this repository.
2. Make sure `snapfix.exe` is located in the **root folder** of the repo.
3. Download **FFmpeg executables** (see section below).
4. Double-click `snapfix.exe` to start the program.

No Python installation is required when using the executable.

---

## 🧑‍💻 Option 2: Run via Python

### Requirements

* **Python 3.9+**
* **FFmpeg executables** (`ffmpeg.exe` and `ffprobe.exe`)

Install Pillow (used for certain image conversions):

```bash
pip install pillow
```

Run the script:

```bash
python snapfix_memories.py
```

---

### 🎞️ FFmpeg (important)

FFmpeg is required for merging overlays with videos and images.

Download FFmpeg from:
➡️ [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html)

⚠️ **Important:**

* You must download the **precompiled executables**, **not the source code**.
* On Windows, this usually means choosing a build labeled *Windows*, *static*, or *release*.

After downloading:

1. Extract the archive.
2. Locate these files:

   * `ffmpeg.exe`
   * `ffprobe.exe`
3. Place them in **one** of the following locations:

   * The same folder as `snapfix.exe` / `snapfix_memories.py`, or
   * A subfolder `ffmpeg/bin`, or
   * Anywhere on your system **PATH**

If FFmpeg is missing or misplaced, the program will fail to process media files.

---

### 🧠 How It Works

1. **ZIP Extraction**
   Each archive is opened and the tool searches for `*-main` and `*-overlay` files.

2. **Format Detection**
   Handles PNG, JPG, and even mislabeled WebP overlays.

3. **Overlay Process**

   * For videos: the overlay image is looped for the entire duration (`-loop 1`, `-shortest`).
   * For photos: FFmpeg merges layers once.

4. **Scaling & Cropping**
   The overlay is scaled or cropped to perfectly fit the main file’s resolution.

5. **Timestamp Recovery**
   The tool finds the **oldest** valid timestamp among:

   * Media’s embedded creation date
   * ZIP entry modification date
   * File system metadata

   That time is then written to the new file’s “Created” and “Modified” fields.

6. **Timeout Safety**
   Each file export is limited to **60 seconds** — if FFmpeg hangs, it’s skipped automatically. If this limit is too harsh on your device, then change the parameter `EXPORT_TIMEOUT_SEC`.

---

### 🧾 Output Example

```
📂 Snapchat memories fixed
 ├─ IMG_20200815_230055.mp4
 ├─ 2020-03-10_18-20-40.jpg
 ├─ snap_152939889.mp4
 └─ skipped_report.txt
```

`skipped_report.txt` lists ZIPs that were skipped (missing files, corrupt data, or timeout).

---

### ⚠️ Legal & Licensing

snapfix-memories uses **FFmpeg**,
an open-source multimedia framework under the **GNU LGPL 2.1** or **GPL v2+** (depending on the build).

**Notes:**

* FFmpeg is **not** included — users must download it separately.
* This program only processes files you exported legally via Snapchat’s *My Data* request.
* No Snapchat APIs, servers, or private endpoints are accessed.

> Distributing this tool with FFmpeg binaries may require compliance with FFmpeg’s license terms.
> For personal use, this is generally fine.

---

### 🧑‍💻 License

This repository (excluding FFmpeg) is licensed under the **MIT License**.
FFmpeg remains under its own license.

---

**Project name:** `snapfix-memories`
**Created by:** *Topstiks*
