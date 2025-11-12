import os
import sys
import time
import json
import queue
import shutil
import zipfile
import tempfile
import threading
import subprocess
import ctypes
import ctypes.wintypes as wt
from datetime import datetime, timezone
from tkinter import Tk, Label, filedialog, StringVar, messagebox, Entry, PhotoImage, N, S, E, W
from tkinter import ttk

# Optional: Pillow for normalizing images FFmpeg can't decode
try:
    from PIL import Image
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

# -------- Configuration --------
EST_FORMAT = "%d-%m-%Y, %H:%M"
ONLY_TIME_FMT = "%H:%M"
MAIN_EXTS = {".mp4", ".jpg", ".jpeg"}
OVERLAY_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
FIT_MODE = "cover"  # or "contain"
EXPORT_TIMEOUT_SEC = 180  # hard per-file timeout; if exceeded -> skip

# ----- Windows file time helpers -----
_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
CreateFileW = _KERNEL32.CreateFileW
CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE]
CreateFileW.restype = wt.HANDLE
SetFileTime = _KERNEL32.SetFileTime
SetFileTime.argtypes = [wt.HANDLE, wt.LPFILETIME, wt.LPFILETIME, wt.LPFILETIME]
SetFileTime.restype = wt.BOOL
CloseHandle = _KERNEL32.CloseHandle
CloseHandle.argtypes = [wt.HANDLE]
CloseHandle.restype = wt.BOOL

GENERIC_WRITE = 0x40000000
FILE_SHARE_NONE = 0
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value

def dt_to_filetime(dt_utc: datetime) -> wt.FILETIME:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    ticks = int((dt_utc - epoch).total_seconds() * 10_000_000)
    return wt.FILETIME(ticks & 0xFFFFFFFF, ticks >> 32)

def set_windows_times(path: str, created_dt_utc: datetime, modified_dt_utc: datetime, accessed_dt_utc: datetime):
    h = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_NONE, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
    if h == INVALID_HANDLE_VALUE:
        raise OSError("CreateFileW failed")
    try:
        c = dt_to_filetime(created_dt_utc)
        a = dt_to_filetime(accessed_dt_utc)
        m = dt_to_filetime(modified_dt_utc)
        if not SetFileTime(h, ctypes.byref(c), ctypes.byref(a), ctypes.byref(m)):
            raise OSError("SetFileTime failed")
    finally:
        CloseHandle(h)

def format_ui_dt(dt: datetime) -> str:
    return dt.astimezone().strftime(EST_FORMAT)

def format_only_time(dt: datetime) -> str:
    return dt.astimezone().strftime(ONLY_TIME_FMT)

# ----- FFmpeg/ffprobe location -----
def find_ffmpeg_binaries(root_folder: str):
    candidates = [
        shutil.which("ffmpeg"),
        shutil.which("ffprobe"),
        os.path.join(root_folder, "ffmpeg.exe"),
        os.path.join(root_folder, "ffprobe.exe"),
        os.path.join(root_folder, "ffmpeg", "bin", "ffmpeg.exe"),
        os.path.join(root_folder, "ffmpeg", "bin", "ffprobe.exe"),
        os.path.join(root_folder, "bin", "ffmpeg.exe"),
        os.path.join(root_folder, "bin", "ffprobe.exe"),
    ]
    ffmpeg = None
    ffprobe = None
    for c in candidates:
        if not c:
            continue
        b = os.path.basename(c).lower()
        if b in ("ffmpeg.exe", "ffmpeg") and os.path.isfile(c):
            ffmpeg = ffmpeg or c
        if b in ("ffprobe.exe", "ffprobe") and os.path.isfile(c):
            ffprobe = ffprobe or c
    return ffmpeg, ffprobe

# ----- Probing helpers -----
def ffprobe_stream(ffprobe_path: str, path: str):
    try:
        out = subprocess.check_output(
            [ffprobe_path, "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,width,height",
             "-of", "json", path],
            stderr=subprocess.STDOUT, text=True
        )
        data = json.loads(out)
        streams = data.get("streams") or []
        return streams[0] if streams else None
    except Exception:
        return None

def parse_ffprobe_creation_time(ffprobe_path: str, media_path: str):
    try:
        out = subprocess.check_output(
            [ffprobe_path, "-v", "error",
             "-show_entries", "format_tags=creation_time",
             "-of", "default=nw=1:nk=1",
             media_path],
            stderr=subprocess.STDOUT, text=True
        ).strip()
        if not out:
            return None
        s = out.replace(" ", "T")
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def zip_entry_dt_utc(zinfo: zipfile.ZipInfo) -> datetime:
    local = datetime(*zinfo.date_time)
    return local.astimezone(timezone.utc)

def choose_oldest_timestamp(zip_path: str, zf: zipfile.ZipFile, main_name: str, overlay_name: str, extracted_main: str, ffprobe_path: str):
    candidates = []
    if extracted_main.lower().endswith(".mp4"):
        ct = parse_ffprobe_creation_time(ffprobe_path, extracted_main)
        if ct:
            candidates.append(ct)
    try:
        candidates.append(zip_entry_dt_utc(zf.getinfo(main_name)))
    except KeyError:
        pass
    try:
        candidates.append(zip_entry_dt_utc(zf.getinfo(overlay_name)))
    except KeyError:
        pass
    try:
        st = os.stat(zip_path)
        candidates.append(datetime.fromtimestamp(st.st_mtime, tz=timezone.utc))
        candidates.append(datetime.fromtimestamp(st.st_ctime, tz=timezone.utc))
    except Exception:
        pass
    return min(candidates) if candidates else datetime.now(timezone.utc)

def normalize_with_pillow(src_path: str, tmpdir: str):
    if not PIL_AVAILABLE:
        return None, None
    try:
        with Image.open(src_path) as im:
            w, h = im.size
            if im.mode != "RGBA":
                im = im.convert("RGBA")
            out_path = os.path.join(tmpdir, "overlay_pillow.png")
            im.save(out_path, "PNG")
            return out_path, (w, h)
    except Exception:
        return None, None

def prepare_overlay(ffmpeg_path: str, ffprobe_path: str, overlay_path: str, tmpdir: str):
    s = ffprobe_stream(ffprobe_path, overlay_path)
    if s:
        codec = (s.get("codec_name") or "").lower()
        w, h = int(s.get("width", 0) or 0), int(s.get("height", 0) or 0)
        if w <= 0 or h <= 0:
            s = None
        elif codec == "webp":
            png_path = os.path.join(tmpdir, "overlay_converted.png")
            cmd = [ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
                   "-i", overlay_path, "-frames:v", "1", png_path]
            try:
                subprocess.check_call(cmd)
                return png_path, "png", (w, h)
            except subprocess.CalledProcessError:
                s = None

    if not s:
        norm_path, wh = normalize_with_pillow(overlay_path, tmpdir)
        if norm_path and wh:
            return norm_path, "png", wh
        return None, None, None

    return overlay_path, (s.get("codec_name") or "").lower(), (int(s.get("width", 0) or 0), int(s.get("height", 0) or 0))

def pick_tagged_files(zf: zipfile.ZipFile):
    names = zf.namelist()
    mains = [n for n in names if "-main" in os.path.basename(n).lower() and os.path.splitext(n.lower())[1] in MAIN_EXTS]
    overs = [n for n in names if "-overlay" in os.path.basename(n).lower() and os.path.splitext(n.lower())[1] in OVERLAY_EXTS]
    if not mains or not overs:
        return None, None
    def core_stem(p):
        b = os.path.basename(p)
        stem = os.path.splitext(b)[0].lower()
        for tag in ("-main", "_main", " main", "-overlay", "_overlay", " overlay"):
            stem = stem.replace(tag, "")
        return stem
    by_core = {}
    for m in mains:
        by_core.setdefault(core_stem(m), {})["main"] = m
    for o in overs:
        by_core.setdefault(core_stem(o), {})["overlay"] = o
    for _, pair in by_core.items():
        if "main" in pair and "overlay" in pair:
            return pair["main"], pair["overlay"]
    return mains[0], overs[0]

def build_filter_numeric(mw: int, mh: int, ow: int, oh: int, mode: str):
    mw = max(1, int(mw)); mh = max(1, int(mh))
    ow = max(1, int(ow)); oh = max(1, int(oh))
    if mode == "cover":
        s = max(mw / ow, mh / oh)
        sw = max(1, int(round(ow * s)))
        sh = max(1, int(round(oh * s)))
        cx = max(0, (sw - mw) // 2)
        cy = max(0, (sh - mh) // 2)
        return f"[1:v]scale={sw}:{sh},crop={mw}:{mh}:{cx}:{cy},format=rgba[ov];[0:v][ov]overlay=0:0:format=auto"
    else:
        s = min(mw / ow, mh / oh)
        sw = max(1, int(round(ow * s)))
        sh = max(1, int(round(oh * s)))
        px = max(0, (mw - sw) // 2)
        py = max(0, (mh - sh) // 2)
        return f"[1:v]scale={sw}:{sh},format=rgba,pad={mw}:{mh}:{px}:{py}:color=0x00000000[ov];[0:v][ov]overlay=0:0:format=auto"

# -------- Robust FFmpeg runner with timeout --------
def run_ffmpeg(cmd, timeout: int):
    """
    Run FFmpeg/FFprobe with a hard timeout.
    Returns (ok: bool, stderr: str, timed_out: bool).
    Ensures process is terminated (and its children on Windows) on timeout.
    """
    creationflags = 0
    if os.name == "nt":
        # Create a new process group so we can kill the tree via taskkill /T
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags
        )
        try:
            out, err = proc.communicate(timeout=timeout)
            return proc.returncode == 0, err, False
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
            else:
                try:
                    proc.kill()
                except Exception:
                    pass
            return False, "Timed out", True
    except Exception as e:
        return False, str(e), False

# ----- FFmpeg runners -----
def overlay_video(ffmpeg_path: str, main_path: str, overlay_path: str, out_path: str,
                  creation_time_utc: datetime, mw: int, mh: int, ow: int, oh: int):
    iso_utc = creation_time_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    filter_complex = build_filter_numeric(mw, mh, ow, oh, FIT_MODE)
    cmd = [
        ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
        "-i", main_path,
        "-loop", "1", "-i", overlay_path,
        "-filter_complex", filter_complex,
        "-metadata", f"creation_time={iso_utc}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "copy",
        "-shortest",
        "-movflags", "+faststart",
        "-pix_fmt", "yuv420p",
        out_path,
    ]
    return run_ffmpeg(cmd, EXPORT_TIMEOUT_SEC)

def overlay_image(ffmpeg_path: str, main_path: str, overlay_path: str, out_path: str,
                  mw: int, mh: int, ow: int, oh: int):
    filter_complex = build_filter_numeric(mw, mh, ow, oh, FIT_MODE)
    cmd = [
        ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
        "-i", main_path,
        "-i", overlay_path,
        "-filter_complex", filter_complex,
        "-frames:v", "1",
        "-q:v", "2",
        out_path,
    ]
    return run_ffmpeg(cmd, EXPORT_TIMEOUT_SEC)

def passthrough_video(ffmpeg_path: str, main_path: str, out_path: str, creation_time_utc: datetime):
    iso_utc = creation_time_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    cmd = [
        ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
        "-i", main_path,
        "-metadata", f"creation_time={iso_utc}",
        "-c", "copy",
        "-movflags", "+faststart",
        out_path,
    ]
    return run_ffmpeg(cmd, EXPORT_TIMEOUT_SEC)

# Media-created for root files
def get_media_created_for_standalone(ffprobe_path: str, path: str):
    ext = os.path.splitext(path.lower())[1]
    if ext == ".mp4":
        dt = parse_ffprobe_creation_time(ffprobe_path, path)
        if dt:
            return dt
    if ext == ".png" and PIL_AVAILABLE:
        try:
            with Image.open(path) as im:
                txt = im.info
                for k in ("date", "creation_time", "creation time"):
                    if k in txt:
                        try:
                            val = txt[k].replace(" ", "T").replace("Z", "+00:00")
                            dt = datetime.fromisoformat(val)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            return dt.astimezone(timezone.utc)
                        except Exception:
                            pass
        except Exception:
            pass
    st = os.stat(path)
    return datetime.fromtimestamp(max(st.st_ctime, st.st_mtime), tz=timezone.utc)

# ----- GUI App -----
class App:
    def __init__(self, root):
        # Styling
        style = ttk.Style(root)
        for theme in ("vista", "clam", "default"):
            try:
                style.theme_use(theme)
                break
            except Exception:
                continue
        style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Sub.TLabel", font=("Segoe UI", 10))
        style.configure("Status.TLabel", font=("Consolas", 10))
        style.configure("TButton", padding=8)
        style.configure("TEntry", padding=6)
        style.configure("TProgressbar", thickness=16)

        # Title / repo name
        self.app_name = "snapfix-memories"
        root.title(self.app_name)

        # Icon
        self._icon_img = None
        try:
            script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            icon_path = os.path.join(script_dir, "src", "icon.png")
            if os.path.exists(icon_path):
                self._icon_img = PhotoImage(file=icon_path)
                root.iconphoto(True, self._icon_img)
        except Exception:
            pass

        # Layout
        root.columnconfigure(0, weight=1)
        header = ttk.Frame(root, padding=(12, 10, 12, 6))
        header.grid(row=0, column=0, sticky=E+W)
        ttk.Label(header, text="snapfix-memories", style="Header.TLabel").grid(row=0, column=1, sticky=W)
        ttk.Label(header, text="Overlay ZIP contents, fix formats, and preserve original timestamps", style="Sub.TLabel").grid(row=1, column=1, sticky=W)

        panel = ttk.Frame(root, padding=(12, 8, 12, 12))
        panel.grid(row=1, column=0, sticky=E+W)
        panel.columnconfigure(1, weight=1)
        ttk.Label(panel, text="Folder:").grid(row=0, column=0, sticky=W, padx=(0, 6))
        self.folder_var = StringVar(value="")
        self.folder_entry = ttk.Entry(panel, textvariable=self.folder_var, width=70)
        self.folder_entry.grid(row=0, column=1, sticky=E+W, padx=(0, 6))
        ttk.Button(panel, text="Browse…", command=self.choose_folder).grid(row=0, column=2)

        row2 = ttk.Frame(root, padding=(12, 0, 12, 0))
        row2.grid(row=2, column=0, sticky=E+W)
        row2.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(row2, orient="horizontal", mode="determinate", maximum=100)
        self.progress.grid(row=0, column=0, sticky=E+W)
        self.pct_var = StringVar(value="0%")
        ttk.Label(row2, textvariable=self.pct_var, width=5, anchor=E).grid(row=0, column=1, padx=(6, 0))

        status_frame = ttk.Frame(root, padding=(12, 6, 12, 10))
        status_frame.grid(row=3, column=0, sticky=E+W)
        self.status_var = StringVar(value="Select a root folder with .zip files")
        self.eta_var = StringVar(value="")
        ttk.Label(status_frame, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=0, sticky=W)
        ttk.Label(status_frame, textvariable=self.eta_var, style="Status.TLabel").grid(row=1, column=0, sticky=W)

        btns = ttk.Frame(root, padding=(12, 0, 12, 12))
        btns.grid(row=4, column=0, sticky=E+W)
        btns.columnconfigure(0, weight=1)
        self.btn_start = ttk.Button(btns, text="Start", command=self.start_processing, state="disabled")
        self.btn_start.grid(row=0, column=1, padx=(0, 6))
        self.btn_cancel = ttk.Button(btns, text="Cancel", command=self.cancel, state="disabled")
        self.btn_cancel.grid(row=0, column=2)

        # Internals
        self.folder = None
        self.output_dir = None
        self.ffmpeg_path = None
        self.ffprobe_path = None
        self.queue = queue.Queue()
        self.worker = None
        self.cancel_flag = threading.Event()
        self.skipped_list = []
        self._progress_max = 1

    def choose_folder(self):
        folder = filedialog.askdirectory(title="Choose root folder (with .zip files)")
        if folder:
            self.folder = folder
            self.folder_var.set(folder)
            self.ffmpeg_path, self.ffprobe_path = find_ffmpeg_binaries(self.folder)
            if not self.ffmpeg_path or not self.ffprobe_path:
                messagebox.showwarning(
                    "FFmpeg",
                    "ffmpeg.exe or ffprobe.exe not found.\n"
                    "Place them in this folder (or ffmpeg\\bin / bin) or add to PATH."
                )
            self.btn_start.config(state="normal")

    def start_processing(self):
        self.folder = self.folder_var.get().strip()
        if not self.folder or not os.path.isdir(self.folder):
            messagebox.showerror("Error", "Folder is invalid.")
            return
        if not self.ffmpeg_path or not self.ffprobe_path:
            self.ffmpeg_path, self.ffprobe_path = find_ffmpeg_binaries(self.folder)
            if not self.ffmpeg_path or not self.ffprobe_path:
                messagebox.showerror("Error", "FFmpeg not found. Provide ffmpeg.exe and ffprobe.exe.")
                return

        self.output_dir = os.path.join(self.folder, "Snapchat memories fixed")
        os.makedirs(self.output_dir, exist_ok=True)

        self.skipped_list = []

        self.btn_start.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.progress["value"] = 0
        self.pct_var.set("0%")
        self.eta_var.set("")
        self.cancel_flag.clear()
        self.worker = threading.Thread(target=self._process_thread, daemon=True)
        self.worker.start()
        self.after_poll()

    def cancel(self):
        self.cancel_flag.set()

    def after_poll(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg.get("kind")
                if kind == "progress":
                    total = max(1, msg["total"])
                    done = msg["done"]
                    self._progress_max = total
                    self.progress["maximum"] = total
                    self.progress["value"] = done
                    pct = int(round((done / total) * 100))
                    self.pct_var.set(f"{pct}%")
                    self.status_var.set(msg["text"])
                    if msg.get("eta_finish"):
                        self.eta_var.set(f"Estimated finish: {format_only_time(msg['eta_finish'])}")
                elif kind == "done":
                    self.status_var.set(msg["text"])
                    self.eta_var.set("")
                    self.btn_start.config(state="normal")
                    self.btn_cancel.config(state="disabled")
                    if self.skipped_list:
                        report_path = os.path.join(self.output_dir, "skipped_report.txt")
                        try:
                            with open(report_path, "w", encoding="utf-8") as f:
                                f.write("Skipped ZIP files and reasons:\n")
                                for line in self.skipped_list:
                                    f.write(f"- {line}\n")
                        except Exception:
                            pass
                        joined = "\n".join(f"- {s}" for s in self.skipped_list[:50])
                        more = "" if len(self.skipped_list) <= 50 else f"\n(+{len(self.skipped_list)-50} more in skipped_report.txt)"
                        messagebox.showinfo(self.app_name, f"{msg['text']}\n\nSkipped:\n{joined}{more}")
                    else:
                        messagebox.showinfo(self.app_name, msg["text"])
                elif kind == "warn":
                    self.status_var.set(msg["text"])
                elif kind == "error":
                    messagebox.showerror(self.app_name, msg["text"])
        except queue.Empty:
            pass
        if self.worker and self.worker.is_alive():
            self.progress.after(200, self.after_poll)

    def _process_thread(self):
        start = time.time()
        entries = os.listdir(self.folder)
        zips = [f for f in entries if f.lower().endswith(".zip")]
        total = len(zips)
        if total == 0:
            self.queue.put({"kind": "error", "text": "No .zip files found."})
            self.queue.put({"kind": "done", "text": "Finished (nothing to do)."})
            return

        done = 0
        successes = 0
        failures = 0
        skipped = 0
        durations = []

        for z in zips:
            if self.cancel_flag.is_set():
                self.queue.put({"kind": "done", "text": f"Canceled. Completed {done}/{total} files."})
                return

            zip_path = os.path.join(self.folder, z)
            step_start = time.time()
            self.queue.put({"kind": "progress", "total": total, "done": done, "text": f"Processing: {z} ({done+1}/{total})"})

            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    main_name, overlay_name = pick_tagged_files(zf)
                    if not main_name or not overlay_name:
                        skipped += 1
                        self.skipped_list.append(f"{z} (missing -main/-overlay files)")
                        raise RuntimeError("Missing -main/-overlay files")

                    with tempfile.TemporaryDirectory() as td:
                        zf.extract(main_name, td)
                        zf.extract(overlay_name, td)
                        main_real = os.path.join(td, main_name)
                        overlay_real = os.path.join(td, overlay_name)
                        if os.path.isdir(main_real) or os.path.isdir(overlay_real):
                            skipped += 1
                            self.skipped_list.append(f"{z} (directory paths inside ZIP)")
                            raise RuntimeError("Unexpected directory path inside ZIP")

                        flat_main = os.path.join(td, os.path.basename(main_name))
                        flat_overlay = os.path.join(td, os.path.basename(overlay_name))
                        if main_real != flat_main:
                            os.makedirs(os.path.dirname(flat_main), exist_ok=True)
                            shutil.move(main_real, flat_main)
                        if overlay_real != flat_overlay:
                            os.makedirs(os.path.dirname(flat_overlay), exist_ok=True)
                            shutil.move(overlay_real, flat_overlay)

                        ms = ffprobe_stream(self.ffprobe_path, flat_main)
                        if not ms:
                            skipped += 1
                            self.skipped_list.append(f"{z} (cannot read main: {os.path.basename(flat_main)})")
                            raise RuntimeError("Main probe failed")
                        mw, mh = int(ms.get("width", 0) or 0), int(ms.get("height", 0) or 0)
                        if mw <= 0 or mh <= 0:
                            skipped += 1
                            self.skipped_list.append(f"{z} (main has invalid dimensions)")
                            raise RuntimeError("Main invalid size")

                        usable_overlay, overlay_codec, overlay_wh = prepare_overlay(self.ffmpeg_path, self.ffprobe_path, flat_overlay, td)
                        oldest_utc = choose_oldest_timestamp(zip_path, zf, main_name, overlay_name, flat_main, self.ffprobe_path)

                        zip_stem = os.path.splitext(z)[0]
                        main_ext = os.path.splitext(os.path.basename(flat_main).lower())[1]
                        out_name = f"{zip_stem}{'.mp4' if main_ext == '.mp4' else '.jpg' if main_ext in {'.jpg', '.jpeg'} else main_ext}"
                        out_path = os.path.join(self.output_dir, out_name)

                        if usable_overlay and overlay_wh:
                            ow, oh = overlay_wh
                            if main_ext == ".mp4":
                                ok, log, timed_out = overlay_video(self.ffmpeg_path, flat_main, usable_overlay, out_path, oldest_utc, mw, mh, ow, oh)
                            elif main_ext in {".jpg", ".jpeg"}:
                                ok, log, timed_out = overlay_image(self.ffmpeg_path, flat_main, usable_overlay, out_path, mw, mh, ow, oh)
                            else:
                                skipped += 1
                                self.skipped_list.append(f"{z} (unsupported main extension)")
                                ok, log, timed_out = True, "", False
                                raise RuntimeError("Unsupported main")
                            if timed_out:
                                skipped += 1
                                self.skipped_list.append(f"{z} (timeout > {EXPORT_TIMEOUT_SEC}s)")
                                # best-effort cleanup of partial
                                try:
                                    if os.path.exists(out_path):
                                        os.remove(out_path)
                                except Exception:
                                    pass
                                raise RuntimeError("Timeout")
                        else:
                            if main_ext == ".mp4":
                                ok, log, timed_out = passthrough_video(self.ffmpeg_path, flat_main, out_path, oldest_utc)
                            elif main_ext in {".jpg", ".jpeg"}:
                                try:
                                    shutil.copyfile(flat_main, out_path)
                                    ok, log, timed_out = True, "", False
                                except Exception as e:
                                    ok, log, timed_out = False, str(e), False
                            else:
                                skipped += 1
                                self.skipped_list.append(f"{z} (unsupported main extension)")
                                ok, log, timed_out = True, "", False
                            if timed_out:
                                skipped += 1
                                self.skipped_list.append(f"{z} (timeout > {EXPORT_TIMEOUT_SEC}s)")
                                try:
                                    if os.path.exists(out_path):
                                        os.remove(out_path)
                                except Exception:
                                    pass
                                raise RuntimeError("Timeout")

                        if not ok:
                            failures += 1
                            self.queue.put({"kind": "warn", "text": f"FFmpeg failed: {z}"})
                        else:
                            try:
                                set_windows_times(out_path, oldest_utc, oldest_utc, oldest_utc)
                            except Exception:
                                pass
                            successes += 1

            except Exception:
                pass
            finally:
                done += 1
                durations.append(max(0.01, time.time() - step_start))
                eta = self._estimate_finish(start, durations, done, total)
                self.queue.put({"kind": "progress", "total": total, "done": done,
                                "text": f"Done: {done}/{total} • OK: {successes} • Failed: {failures} • Skipped: {skipped}",
                                "eta_finish": eta})

        # Also process root-level standalone .mp4 and .png (not inside zips)
        for f in entries:
            fp = os.path.join(self.folder, f)
            if not os.path.isfile(fp):
                continue
            name_lower = f.lower()
            if name_lower.endswith(".zip"):
                continue
            if name_lower.endswith(".mp4") or name_lower.endswith(".png"):
                try:
                    created = get_media_created_for_standalone(self.ffprobe_path, fp)
                    dst = os.path.join(self.output_dir, f)
                    if name_lower.endswith(".mp4"):
                        ok, _, timed_out = passthrough_video(self.ffmpeg_path, fp, dst, created)
                        if (not ok) or timed_out:
                            # If passthrough hangs (rare), copy as last resort
                            try:
                                shutil.copyfile(fp, dst)
                            except Exception:
                                pass
                    else:
                        shutil.copyfile(fp, dst)
                    try:
                        set_windows_times(dst, created, created, created)
                    except Exception:
                        pass
                except Exception:
                    pass

        summary = (f"Finished {format_ui_dt(datetime.now())}. "
                   f"ZIPs processed: {total}, OK: {successes}, Failed: {failures}, Skipped: {len(self.skipped_list)}. "
                   f"Output: {self.output_dir}")
        self.queue.put({"kind": "done", "text": summary})

    def _estimate_finish(self, started_epoch, durations, done, total):
        if done == 0:
            return None
        avg = sum(durations) / len(durations)
        remaining = max(0, total - done)
        eta_sec = remaining * avg
        finish_ts = started_epoch + sum(durations) + eta_sec
        return datetime.fromtimestamp(finish_ts)

def main():
    root = Tk()
    app = App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
