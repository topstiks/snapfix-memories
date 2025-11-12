# 📸 snapfix-memories  
*A desktop tool to automatically repair and restore exported Snapchat Memories.*

---

### 🧩 Why This Exists

When you download your data from **Snapchat’s “My Data” portal**, your *Memories* come as a giant folder of **ZIP archives**.  
Each ZIP usually contains:
- a `*-main.mp4` or `*-main.jpg` file — the actual snap, and  
- a `*-overlay.png` image — the timestamp, text, or caption layer.

Unfortunately, these exports are messy:
- File names are inconsistent
- Some ZIPs have mismatched resolutions  
- Metadata (“Date Created”) is missing or wrong  | This is still WIP
- Not all memories are cleanly in 1 folder

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

#### 1. Requirements
- **Python 3.9+**
- **FFmpeg** binaries (`ffmpeg.exe` and `ffprobe.exe`)

> 🧩 FFmpeg is not bundled — you must download it yourself.  

Download FFmpeg here:  
➡️ [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html)

Extract and place:
- `ffmpeg.exe`  
- `ffprobe.exe`  
either:
- in the same folder as `snapfix_memories.py`, or  
- in a subfolder `ffmpeg/bin`, or  
- anywhere on your system PATH

Then install Pillow (used for certain image conversions):

```bash
pip install pillow
```

---

#### 2. Run the Tool

```bash
python snapfix_memories.py
```

Steps:
1. Click **Browse…** and choose your Snapchat export folder (where all the ZIPs are).  
2. Press **Start**.  
3. Wait for the process to complete — you’ll see a live progress bar and ETA.  
4. Find all your repaired files inside:
   ```
   Snapchat memories fixed/
   ```

---

### 🧠 How It Works

1. **ZIP Extraction**  
   Each archive is opened and the tool searches for `*-main` and `*-overlay` files.

2. **Format Detection**  
   Handles PNG, JPG, and even mislabeled WebP overlays.

3. **Overlay Process**  
   - For videos: the overlay image is looped for the entire duration (`-loop 1`, `-shortest`).  
   - For photos: FFmpeg merges layers once.

4. **Scaling & Cropping**  
   The overlay is scaled or cropped to perfectly fit the main file’s resolution.

5. **Timestamp Recovery**  
   The tool finds the **oldest** valid timestamp among:
   - Media’s embedded creation date  
   - ZIP entry modification date  
   - File system metadata  

   That time is then written to the new file’s “Created” and “Modified” fields.

6. **Timeout Safety**  
   Each file export is limited to **60 seconds** — if FFmpeg hangs, it’s skipped automatically. If this limit is too harsh on your device, then change the parameter EXPORT_TIMEOUT_SEC

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

snapfix-memories uses [**FFmpeg**](https://ffmpeg.org),  
an open-source multimedia framework under the **GNU LGPL 2.1** or **GPL v2+** (depending on the build).

**Notes:**
- FFmpeg is **not** included — users must download it separately.  
- This program only processes files you exported legally via Snapchat’s *My Data* request.  
- No Snapchat APIs, servers, or private endpoints are accessed.

> Distributing this tool with FFmpeg binaries may require compliance with FFmpeg’s license terms.  
> For personal use, this is generally fine.

---

### 🐞 Troubleshooting

| Problem | Likely Cause | Fix |
|----------|---------------|-----|
| “ffmpeg.exe not found” | Missing or misplaced FFmpeg binaries | Place `ffmpeg.exe` and `ffprobe.exe` in script folder or add to PATH |
| Overlay missing | Corrupted overlay or wrong image format | It will skip automatically; check `skipped_report.txt` |
| Wrong or missing date | File had no metadata | The script uses fallback (ZIP or system date) |
| Program hangs | A ZIP took too long (>60 s) | It’s automatically skipped and logged |

---

### 💡 Tips

- You can safely re-run the app; existing fixed files will be overwritten.  
- Delete the original ZIPs after verifying the “fixed” folder.  
- If you have large videos that always timeout, increase the constant  
  `EXPORT_TIMEOUT_SEC` near the top of the script.

---

### 🧑‍💻 License

This repository (excluding FFmpeg) is licensed under the **MIT License**.  
FFmpeg remains under its own license (LGPL/GPL).

---

**Project name:** `snapfix-memories`  
**Created by:** *Topstiks*  
📦 GitHub: [https://github.com/yourname/snapfix-memories](https://github.com/yourname/snapfix-memories)
