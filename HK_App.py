"""
HK Rally Helper (GUI) - Enhanced Executable App Style
"""

import base64
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import cv2
import numpy as np

from HK_License import ensure_license

# --------------------------------------------------------------------- paths
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "hk_config.json"
BUTTON_DIR = ROOT / "buttons"
LOG_PATH = ROOT / "hk_helper.log"
DETECTION_IMAGE = ROOT / "hk_last_detection.png"

SCALES = [0.5 + 0.1 * i for i in range(11)]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

ADB_CANDIDATES = [
    r"D:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer\nx_device\12.0\shell\adb.exe",
    r"C:\Program Files (x86)\Netease\MuMuPlayer\nx_device\12.0\shell\adb.exe",
    r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
    r"C:\Program Files\BlueStacks\HD-Adb.exe",
    str(Path.home() / "AppData/Local/Android/Sdk/platform-tools/adb.exe"),
    r"C:\platform-tools\adb.exe",
]

# ------------------------------------------------------------------- logging
FINISHED = object()
log_queue = queue.Queue()
log = logging.getLogger("HK")
log.setLevel(logging.INFO)


class _QueueHandler(logging.Handler):
    def emit(self, record):
        log_queue.put(self.format(record))


_qh = _QueueHandler()
_qh.setFormatter(logging.Formatter("%(asctime)s | %(message)s", "%H:%M:%S"))
log.addHandler(_qh)
try:
    _fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    log.addHandler(_fh)
except OSError:
    pass


# ------------------------------------------------------------------- helpers
def imread_color(path):
    try:
        data = np.fromfile(str(path), np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except OSError:
        return None


def imwrite_png(path, image):
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("Could not encode image.")
    Path(path).write_bytes(buf.tobytes())


def find_adb(explicit=""):
    candidates = []
    if explicit:
        candidates.append(explicit)
    candidates += [str(ROOT / "adb.exe"), str(ROOT / "platform-tools" / "adb.exe")]
    if os.environ.get("HK_ADB"):
        candidates.append(os.environ["HK_ADB"])
    on_path = shutil.which("adb")
    if on_path:
        candidates.append(on_path)
    candidates += ADB_CANDIDATES
    seen = set()
    for c in candidates:
        key = c.lower()
        if key in seen or not Path(c).is_file():
            continue
        seen.add(key)
        try:
            subprocess.run([c, "version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           stdin=subprocess.DEVNULL, timeout=5, check=True,
                           creationflags=NO_WINDOW)
            return c
        except Exception:
            continue
    return None


class Adb:
    def __init__(self, exe, serial=""):
        self.exe = exe
        self.serial = serial

    def run(self, *args, timeout=15, use_serial=True, check=True):
        cmd = [self.exe]
        if use_serial and self.serial:
            cmd += ["-s", self.serial]
        cmd += list(args)
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           stdin=subprocess.DEVNULL, timeout=timeout,
                           creationflags=NO_WINDOW)
        if check and p.returncode != 0:
            raise RuntimeError(p.stderr.decode("utf-8", "replace").strip() or "ADB command failed")
        return p.stdout

    def devices(self):
        out = self.run("devices", timeout=10, use_serial=False).decode("utf-8", "replace")
        found = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                found.append(parts[0])
        return found

    def screenshot(self):
        data = self.run("exec-out", "screencap", "-p", timeout=20)
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("Could not decode the screenshot. Check the selected device.")
        return frame

    def tap(self, x, y):
        self.run("shell", "input", "tap", str(int(x)), str(int(y)), timeout=10)


def best_match(frame, template):
    fh, fw = frame.shape[:2]
    th0, tw0 = template.shape[:2]
    best = (0.0, None, None, None)
    for s in SCALES:
        tw, th = int(tw0 * s), int(th0 * s)
        if tw < 8 or th < 8 or tw > fw or th > fh:
            continue
        interp = cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC
        resized = cv2.resize(template, (tw, th), interpolation=interp)
        res = cv2.matchTemplate(frame, resized, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        if score > best[0]:
            best = (float(score), (loc[0] + tw // 2, loc[1] + th // 2), (tw, th), loc)
    return best


def save_detection(frame, match, label):
    score, _, (w, h), (x, y) = match
    shot = frame.copy()
    cv2.rectangle(shot, (x, y), (x + w, y + h), (0, 255, 0), 3)
    cv2.putText(shot, f"{label} {score:.2f}", (x, max(20, y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    try:
        imwrite_png(DETECTION_IMAGE, shot)
    except OSError:
        pass


# -------------------------------------------------------------------- config
def default_config():
    cfg = {"adb": "", "serial": "", "live": False, "threshold": 0.82,
           "poll": 1.0, "loop_pause": 2.0, "loops": 0, "items": [], "steps": []}
    BUTTON_DIR.mkdir(exist_ok=True)
    found = []
    for name, legacy in (("Join", "join_button.png"), ("March", "march_screen.png")):
        src = ROOT / legacy
        if src.is_file():
            shutil.copy(src, BUTTON_DIR / legacy)
            cfg["items"].append({"name": name, "kind": "image", "file": f"buttons/{legacy}"})
            found.append(name)
    if found == ["Join", "March"]:
        cfg["steps"] = [
            {"type": "tap", "item": "Join", "timeout": 0, "on_timeout": "restart", "delay": 1.2},
            {"type": "tap", "item": "March", "timeout": 30, "on_timeout": "restart", "delay": 2.0},
        ]
    return cfg


def load_config():
    if CONFIG_PATH.is_file():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for k, v in {"adb": "", "serial": "", "live": False, "threshold": 0.82,
                         "poll": 1.0, "loop_pause": 2.0, "loops": 0,
                         "items": [], "steps": []}.items():
                cfg.setdefault(k, v)
            return cfg
        except (OSError, ValueError):
            pass
    return default_config()


def describe_item(item):
    if item["kind"] == "point":
        return f'{item["name"]}   [fixed point {item["x"]}, {item["y"]}]'
    return f'{item["name"]}   [button image / crop]'


def describe_step(i, step):
    if step["type"] == "wait":
        return f'{i}.  [Wait] {step.get("seconds", 1)} s'
    t = float(step.get("timeout", 0))
    look = "until found" if t <= 0 else f"up to {t:g} s"
    fail = "restart cycle" if step.get("on_timeout", "restart") == "restart" else "skip step"
    return (f'{i}.  [Automation Action] Tap [{step["item"]}]  -  look {look}, if missing: {fail}, '
            f'then wait {step.get("delay", 0):g} s')


# -------------------------------------------------------------------- engine
class Stop(Exception):
    pass


class Engine(threading.Thread):
    def __init__(self, adb, items, steps, live, threshold, poll, loop_pause, loops):
        super().__init__(daemon=True)
        self.adb, self.items, self.steps = adb, items, steps
        self.live, self.threshold = live, threshold
        self.poll, self.loop_pause, self.loops = poll, loop_pause, loops
        self.templates = {}
        self._stop_flag = threading.Event()
        self._run_flag = threading.Event()
        self._run_flag.set()

    def pause(self):
        self._run_flag.clear()

    def resume(self):
        self._run_flag.set()

    def stop(self):
        self._stop_flag.set()
        self._run_flag.set()

    @property
    def paused(self):
        return not self._run_flag.is_set()

    def _check(self):
        if self._stop_flag.is_set():
            raise Stop()
        if not self._run_flag.is_set():
            log.info("Paused via Switch/Control.")
            while not self._run_flag.wait(0.2):
                if self._stop_flag.is_set():
                    raise Stop()
            log.info("Resumed via Switch/Control.")
        if self._stop_flag.is_set():
            raise Stop()

    def _sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self._check()
            time.sleep(min(0.1, max(0.0, end - time.time())))

    def _tap(self, pos, label):
        if self.live:
            self.adb.tap(*pos)
            log.info("LIVE TAP: Tapped '%s' at %s", label, pos)
        else:
            log.info("DRY RUN: Simulated tap on '%s' at %s", label, pos)

    def _prepare(self):
        if not self.steps:
            return "The workflow is empty. Please add custom automation steps."
        for st in self.steps:
            if st["type"] != "tap":
                continue
            item = self.items.get(st["item"])
            if not item:
                return f'Automation action uses button/target "{st["item"]}" which no longer exists.'
            if item["kind"] == "image" and item["name"] not in self.templates:
                tpl = imread_color(ROOT / item["file"])
                if tpl is None:
                    return f'Image template for "{item["name"]}" is missing: {item["file"]}'
                self.templates[item["name"]] = tpl
        return None

    def _tap_step(self, idx, step):
        name = step["item"]
        item = self.items[name]
        delay = float(step.get("delay", 0))
        if item["kind"] == "point":
            log.info("Step %d: executing custom point tap [%s]", idx, name)
            self._tap((item["x"], item["y"]), name)
            self._sleep(delay)
            return True

        tpl = self.templates[name]
        timeout = float(step.get("timeout", 0))
        end = time.time() + timeout if timeout > 0 else None
        last_note = 0.0
        log.info("Step %d: looking for target/crop [%s]", idx, name)
        while True:
            self._check()
            frame = self.adb.screenshot()
            m = best_match(frame, tpl)
            if m[1] and m[0] >= self.threshold:
                log.info("[%s] found: score=%.3f at %s", name, m[0], m[1])
                if not self.live:
                    save_detection(frame, m, name)
                    log.info("Test Mode (Dry Run): match saved to %s. No real taps fired.", DETECTION_IMAGE.name)
                self._tap(m[1], name)
                self._sleep(delay)
                return True
            if end and time.time() >= end:
                log.warning("[%s] not found within timeout %g s.", name, timeout)
                return False
            if time.time() - last_note > 10:
                log.info("Waiting for [%s] (best score %.2f)...", name, m[0])
                last_note = time.time()
            self._sleep(self.poll)

    def run(self):
        self._dry_done = False
        try:
            err = self._prepare()
            if err:
                log.error(err)
                return
            log.info("Engine Started - Mode: %s", "LIVE (Real Taps Active)" if self.live else "TEST / DRY RUN (Safe, No Taps)")
            completed = 0
            while True:
                try:
                    restart = False
                    for i, step in enumerate(self.steps, 1):
                        self._check()
                        if step["type"] == "wait":
                            secs = float(step.get("seconds", 1))
                            log.info("Step %d: wait %g s", i, secs)
                            self._sleep(secs)
                            continue
                        ok = self._tap_step(i, step)
                        if not ok and step.get("on_timeout", "restart") == "restart":
                            restart = True
                            break
                    if not restart:
                        completed += 1
                        log.info("Automation loops completed: %d", completed)
                        if self.loops and completed >= self.loops:
                            log.info("Reached cycle target limit (%d).", self.loops)
                            break
                    self._sleep(self.loop_pause)
                except Stop:
                    raise
                except Exception as exc:
                    log.error("Execution exception: %s", exc)
                    self._sleep(3)
        except Stop:
            log.info("Automation stopped.")
        except Exception as exc:
            log.exception("Fatal engine error: %s", exc)
        finally:
            log_queue.put(FINISHED)


# ------------------------------------------------------------------- dialogs
class Selector(tk.Toplevel):
    def __init__(self, parent, adb, frame, kind):
        super().__init__(parent)
        self.title("1. Calibrate Target / Crop")
        self.transient(parent)
        self.grab_set()
        self.adb, self.frame, self.kind = adb, frame, kind
        self.result = None
        self._start = None
        self._sel = None

        text = ("Drag a box tightly around the target button/crop area, then press Save."
                if kind == "image" else "Click the exact click coordinates, then press Save.")
        ttk.Label(self, text=text).pack(padx=8, pady=(8, 4))
        self.canvas = tk.Canvas(self, highlightthickness=0, cursor="crosshair")
        self.canvas.pack(padx=8, pady=4)
        bar = ttk.Frame(self)
        bar.pack(pady=8)
        ttk.Button(bar, text="Retake Screenshot", command=self._retake).pack(side="left", padx=4)
        ttk.Button(bar, text="Save Calibration", command=self._save).pack(side="left", padx=4)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self._show()

    def _show(self):
        h, w = self.frame.shape[:2]
        self.scale = min(1.0, 1100 / w, 620 / h)
        view = (cv2.resize(self.frame, None, fx=self.scale, fy=self.scale,
                           interpolation=cv2.INTER_AREA) if self.scale < 1 else self.frame)
        ok, buf = cv2.imencode(".png", view)
        self.photo = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        self.canvas.config(width=view.shape[1], height=view.shape[0])
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self._sel, self._shape = None, None

    def _retake(self):
        try:
            self.frame = self.adb.screenshot()
            self._show()
        except Exception as exc:
            messagebox.showerror("HK", str(exc), parent=self)

    def _press(self, e):
        self._start = (e.x, e.y)
        if self.kind == "point":
            self._sel = (e.x, e.y)
            self.canvas.delete("mark")
            self.canvas.create_oval(e.x - 8, e.y - 8, e.x + 8, e.y + 8, outline="#ff2d2d", width=3, tags="mark")

    def _drag(self, e):
        if self.kind != "image" or not self._start:
            return
        self.canvas.delete("mark")
        x0, y0 = self._start
        self.canvas.create_rectangle(x0, y0, e.x, e.y, outline="#00e000", width=2, tags="mark")
        self._sel = (x0, y0, e.x, e.y)

    def _release(self, e):
        self._drag(e)

    def _save(self):
        if not self._sel:
            messagebox.showinfo("HK", "Please make a selection first.", parent=self)
            return
        if self.kind == "point":
            x, y = self._sel
            self.result = (int(x / self.scale), int(y / self.scale))
        else:
            x0, y0, x1, y1 = (int(v / self.scale) for v in self._sel)
            x0, x1 = sorted((max(0, x0), max(0, x1)))
            y0, y1 = sorted((max(0, y0), max(0, y1)))
            if x1 - x0 < 8 or y1 - y0 < 8:
                messagebox.showinfo("HK", "Selection area is too small.", parent=self)
                return
            self.result = self.frame[y0:y1, x0:x1].copy()
        self.destroy()


class NewItemDialog(tk.Toplevel):
    def __init__(self, parent, existing):
        super().__init__(parent)
        self.title("2. Add New Click / Automation Target")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.existing = {n.lower() for n in existing}
        self.result = None
        self.name_var = tk.StringVar()
        self.kind_var = tk.StringVar(value="image")
        f = ttk.Frame(self, padding=12)
        f.pack()
        ttk.Label(f, text="Automation / Click Function Name:").grid(row=0, column=0, sticky="w")
        e = ttk.Entry(f, textvariable=self.name_var, width=30)
        e.grid(row=0, column=1, pady=4)
        e.focus_set()
        ttk.Radiobutton(f, text="Image Crop / Button Match (Dynamic location)", variable=self.kind_var, value="image").grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Radiobutton(f, text="Fixed Screen Point (Static coordinate click)", variable=self.kind_var, value="point").grid(row=2, column=0, columnspan=2, sticky="w")
        bar = ttk.Frame(f)
        bar.grid(row=3, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(bar, text="Capture from Screen...", command=self._ok).pack(side="left", padx=4)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        self.bind("<Return>", lambda _e: self._ok())

    def _ok(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showinfo("HK", "Please enter a unique name.", parent=self)
            return
        if name.lower() in self.existing:
            messagebox.showinfo("HK", "An automation function with this name already exists.", parent=self)
            return
        self.result = (name, self.kind_var.get())
        self.destroy()


class StepDialog(tk.Toplevel):
    TAP, WAIT = "Tap function / target", "Wait"

    def __init__(self, parent, item_names, step=None):
        super().__init__(parent)
        self.title("Configure Step Action")
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.result = None
        self.names = item_names
        step = step or {"type": "tap", "item": item_names[0] if item_names else "",
                        "timeout": 0, "on_timeout": "restart", "delay": 1.0}
        self.type_var = tk.StringVar(value=self.TAP if step["type"] == "tap" else self.WAIT)
        self.item_var = tk.StringVar(value=step.get("item", ""))
        self.timeout_var = tk.StringVar(value=str(step.get("timeout", 0)))
        self.fail_var = tk.StringVar(
            value="restart cycle" if step.get("on_timeout", "restart") == "restart" else "skip step")
        self.delay_var = tk.StringVar(value=str(step.get("delay", 1.0)))
        self.secs_var = tk.StringVar(value=str(step.get("seconds", 2)))

        f = ttk.Frame(self, padding=12)
        f.pack()
        ttk.Label(f, text="Action Type:").grid(row=0, column=0, sticky="w", pady=3)
        cb = ttk.Combobox(f, textvariable=self.type_var, state="readonly", values=[self.TAP, self.WAIT], width=26)
        cb.grid(row=0, column=1, pady=3)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._toggle())

        ttk.Label(f, text="Select Automation Target:").grid(row=1, column=0, sticky="w", pady=3)
        self.item_cb = ttk.Combobox(f, textvariable=self.item_var, state="readonly", values=item_names, width=26)
        self.item_cb.grid(row=1, column=1, pady=3)
        ttk.Label(f, text="Timeout (s, 0 = wait indefinitely):").grid(row=2, column=0, sticky="w", pady=3)
        self.timeout_sp = ttk.Spinbox(f, from_=0, to=3600, textvariable=self.timeout_var, width=8)
        self.timeout_sp.grid(row=2, column=1, sticky="w", pady=3)
        ttk.Label(f, text="On Timeout:").grid(row=3, column=0, sticky="w", pady=3)
        self.fail_cb = ttk.Combobox(f, textvariable=self.fail_var, state="readonly", values=["restart cycle", "skip step"], width=14)
        self.fail_cb.grid(row=3, column=1, sticky="w", pady=3)
        ttk.Label(f, text="Delay After Tap (s):").grid(row=4, column=0, sticky="w", pady=3)
        self.delay_sp = ttk.Spinbox(f, from_=0, to=600, increment=0.1, textvariable=self.delay_var, width=8)
        self.delay_sp.grid(row=4, column=1, sticky="w", pady=3)
        ttk.Label(f, text="Wait Seconds:").grid(row=5, column=0, sticky="w", pady=3)
        self.secs_sp = ttk.Spinbox(f, from_=0, to=3600, increment=0.5, textvariable=self.secs_var, width=8)
        self.secs_sp.grid(row=5, column=1, sticky="w", pady=3)

        bar = ttk.Frame(f)
        bar.grid(row=6, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(bar, text="OK", command=self._ok).pack(side="left", padx=4)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="left", padx=4)
        self._toggle()

    def _toggle(self):
        tap = self.type_var.get() == self.TAP
        for w in (self.item_cb, self.timeout_sp, self.fail_cb, self.delay_sp):
            w.config(state=("readonly" if w in (self.item_cb, self.fail_cb) else "normal") if tap else "disabled")
        self.secs_sp.config(state="disabled" if tap else "normal")

    def _ok(self):
        try:
            if self.type_var.get() == self.WAIT:
                self.result = {"type": "wait", "seconds": max(0.0, float(self.secs_var.get()))}
            else:
                if not self.item_var.get() or self.item_var.get() not in self.names:
                    messagebox.showinfo("HK", "Select a valid named automation target first.", parent=self)
                    return
                self.result = {
                    "type": "tap", "item": self.item_var.get(),
                    "timeout": max(0.0, float(self.timeout_var.get())),
                    "on_timeout": "restart" if self.fail_var.get() == "restart cycle" else "skip",
                    "delay": max(0.0, float(self.delay_var.get())),
                }
        except ValueError:
            messagebox.showinfo("HK", "Please enter valid numeric parameters.", parent=self)
            return
        self.destroy()


# ------------------------------------------------------------------ main app
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HK Rally Helper - 4 Options Control Panel")
        self.geometry("980x760")
        self.minsize(880, 640)
        self.cfg = load_config()
        self.engine = None
        self.report_callback_exception = lambda *a: log.error("UI error: %s", a[1])
        self._build()
        self._refresh_lists()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_log)
        self.after(300, self._auto_detect)

    def _build(self):
        pad = {"padx": 8, "pady": 4}
        top = ttk.LabelFrame(self, text="Device & General Settings")
        top.pack(fill="x", **pad)
        ttk.Label(top, text="ADB Path:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.adb_var = tk.StringVar(value=self.cfg["adb"])
        ttk.Entry(top, textvariable=self.adb_var, width=54).grid(row=0, column=1, sticky="we")
        ttk.Button(top, text="Auto-detect", command=self._auto_detect).grid(row=0, column=2, padx=6)
        ttk.Label(top, text="Device Serial:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.dev_var = tk.StringVar(value=self.cfg["serial"])
        self.dev_cb = ttk.Combobox(top, textvariable=self.dev_var, width=28)
        self.dev_cb.grid(row=1, column=1, sticky="w")
        ttk.Button(top, text="Refresh", command=self._refresh_devices).grid(row=1, column=2, padx=6)
        top.columnconfigure(1, weight=1)

        opts = ttk.Frame(top)
        opts.grid(row=2, column=0, columnspan=3, sticky="w", padx=6, pady=(2, 6))
        
        # 3. Test & 4. Live execution mode selections
        self.live_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="3. Test Mode (Dry Run) / 4. Live Taps Switch (Checked = REAL Taps)",
                        variable=self.live_var, command=self._on_live).pack(side="left")
        ttk.Label(opts, text="   Threshold:").pack(side="left")
        self.thr_var = tk.DoubleVar(value=self.cfg["threshold"])
        ttk.Spinbox(opts, from_=0.50, to=0.99, increment=0.01, width=5, textvariable=self.thr_var).pack(side="left")
        ttk.Label(opts, text="   Cycles Limit:").pack(side="left")
        self.loops_var = tk.IntVar(value=self.cfg["loops"])
        ttk.Spinbox(opts, from_=0, to=99999, width=6, textvariable=self.loops_var).pack(side="left")

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, **pad)
        mid.columnconfigure(0, weight=2)
        mid.columnconfigure(1, weight=3)
        mid.rowconfigure(0, weight=1)

        # 1. Calibrate & 2. Add New Automation Panel
        bp = ttk.LabelFrame(mid, text="1. Calibrate / 2. Add New Automation Targets")
        bp.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.item_list = tk.Listbox(bp, exportselection=False, activestyle="none")
        self.item_list.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        bcol = ttk.Frame(bp)
        bcol.pack(side="left", fill="y", padx=6, pady=6)
        tk.Button(bcol, text="+ Add", font=("Segoe UI", 10, "bold"), bg="#2e7d32", fg="white",
                  command=self._add_item).pack(pady=(0, 6))
        ttk.Button(bcol, text="Delete", command=self._delete_item).pack()

        # Workflow execution mapping
        wp = ttk.LabelFrame(mid, text="Workflow Steps Sequence")
        wp.grid(row=0, column=1, sticky="nsew")
        self.step_list = tk.Listbox(wp, exportselection=False, activestyle="none")
        self.step_list.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        self.step_list.bind("<Double-Button-1>", lambda _e: self._edit_step())
        wcol = ttk.Frame(wp)
        wcol.pack(side="left", fill="y", padx=6, pady=6)
        tk.Button(wcol, text="+ Step", font=("Segoe UI", 10, "bold"), bg="#2e7d32", fg="white",
                  command=self._add_step).pack(pady=(0, 6))
        for text, cmd in (("Edit", self._edit_step), ("Up", lambda: self._move_step(-1)),
                          ("Down", lambda: self._move_step(1)), ("Remove", self._remove_step)):
            ttk.Button(wcol, text=text, command=cmd).pack(pady=2)

        # Run / Pause / Stop control panel switch
        ctl = ttk.Frame(self)
        ctl.pack(fill="x", **pad)
        
        self.start_btn = tk.Button(ctl, text="Start Engine", width=12, bg="#1565c0", fg="white",
                                   font=("Segoe UI", 10, "bold"), command=self._start)
        self.start_btn.pack(side="left", padx=4)
        
        # Run or Pause switch button
        self.pause_resume_btn = tk.Button(ctl, text="Pause / Resume", width=14, bg="#ef6c00", fg="white",
                                          font=("Segoe UI", 10, "bold"), command=self._toggle_pause_resume,
                                          state="disabled")
        self.pause_resume_btn.pack(side="left", padx=4)
        
        self.stop_btn = tk.Button(ctl, text="Stop", width=10, bg="#c62828", fg="white",
                                  font=("Segoe UI", 10, "bold"), command=self._stop,
                                  state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        
        self.status_var = tk.StringVar(value="Status: Idle (Ready)")
        ttk.Label(ctl, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).pack(side="left", padx=16)

        lf = ttk.LabelFrame(self, text="Terminal Log Feed")
        lf.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(lf, height=8, state="disabled", wrap="word")
        sb = ttk.Scrollbar(lf, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True, padx=(6, 0), pady=6)

    def _auto_detect(self):
        exe = find_adb(self.adb_var.get().strip())
        if exe:
            self.adb_var.set(exe)
            self._refresh_devices()

    def _refresh_devices(self):
        exe = find_adb(self.adb_var.get().strip())
        if not exe:
            return
        try:
            adb = Adb(exe)
            adb.run("start-server", use_serial=False, check=False)
            cur = self.dev_var.get().strip()
            if ":" in cur:
                adb.run("connect", cur, use_serial=False, check=False, timeout=10)
            devs = adb.devices()
            self.dev_cb["values"] = devs
            if devs and cur not in devs:
                self.dev_var.set(devs[0])
            log.info("Active devices found: %s", ", ".join(devs) if devs else "none")
        except Exception as exc:
            log.error("Device refresh error: %s", exc)

    def _get_adb(self):
        exe = find_adb(self.adb_var.get().strip())
        if not exe:
            messagebox.showerror("HK", "adb.exe not found.")
            return None
        self.adb_var.set(exe)
        serial = self.dev_var.get().strip()
        try:
            adb = Adb(exe, serial)
            if ":" in serial:
                adb.run("connect", serial, use_serial=False, check=False, timeout=10)
            devs = adb.devices()
        except Exception as exc:
            messagebox.showerror("HK", f"ADB error:\n{exc}")
            return None
        if not devs:
            messagebox.showerror("HK", "No active Android device detected.")
            return None
        if serial not in devs:
            if len(devs) == 1:
                serial = devs[0]
                self.dev_var.set(serial)
            else:
                return None
        adb.serial = serial
        return adb

    def _on_live(self):
        if self.live_var.get() and not messagebox.askyesno(
                "HK", "Switch to option 4: LIVE Taps mode?\n\nReal taps will now be sent to your game device."):
            self.live_var.set(False)

    def _add_item(self):
        dlg = NewItemDialog(self, [i["name"] for i in self.cfg["items"]])
        self.wait_window(dlg)
        if not dlg.result:
            return
        name, kind = dlg.result
        adb = self._get_adb()
        if not adb:
            return
        try:
            frame = adb.screenshot()
        except Exception as exc:
            messagebox.showerror("HK", f"Screenshot failed:\n{exc}")
            return
        sel = Selector(self, adb, frame, kind)
        self.wait_window(sel)
        if sel.result is None:
            return
        if kind == "point":
            x, y = sel.result
            self.cfg["items"].append({"name": name, "kind": "point", "x": x, "y": y})
        else:
            BUTTON_DIR.mkdir(exist_ok=True)
            base = re.sub(r"[^\w\-]+", "_", name).strip("_") or "button"
            path, n = BUTTON_DIR / f"{base}.png", 1
            while path.exists():
                n += 1
                path = BUTTON_DIR / f"{base}_{n}.png"
            imwrite_png(path, sel.result)
            self.cfg["items"].append({"name": name, "kind": "image", "file": f"buttons/{path.name}"})
        log.info("Successfully added new automation target/calibration: '%s'", name)
        self._save()
        self._refresh_lists()

    def _delete_item(self):
        sel = self.item_list.curselection()
        if not sel:
            return
        item = self.cfg["items"][sel[0]]
        if any(s.get("item") == item["name"] for s in self.cfg["steps"]):
            messagebox.showinfo("HK", f'Target "{item["name"]}" is currently used in the workflow steps.')
            return
        if not messagebox.askyesno("HK", f'Delete target "{item["name"]}"?'):
            return
        if item["kind"] == "image":
            try:
                (ROOT / item["file"]).unlink()
            except OSError:
                pass
        del self.cfg["items"][sel[0]]
        self._save()
        self._refresh_lists()

    def _names(self):
        return [i["name"] for i in self.cfg["items"]]

    def _add_step(self):
        dlg = StepDialog(self, self._names())
        self.wait_window(dlg)
        if dlg.result:
            sel = self.step_list.curselection()
            at = sel[0] + 1 if sel else len(self.cfg["steps"])
            self.cfg["steps"].insert(at, dlg.result)
            self._save()
            self._refresh_lists(select_step=at)

    def _edit_step(self):
        sel = self.step_list.curselection()
        if not sel:
            return
        dlg = StepDialog(self, self._names(), self.cfg["steps"][sel[0]])
        self.wait_window(dlg)
        if dlg.result:
            self.cfg["steps"][sel[0]] = dlg.result
            self._save()
            self._refresh_lists(select_step=sel[0])

    def _move_step(self, d):
        sel = self.step_list.curselection()
        if not sel:
            return
        i, j = sel[0], sel[0] + d
        steps = self.cfg["steps"]
        if 0 <= j < len(steps):
            steps[i], steps[j] = steps[j], steps[i]
            self._save()
            self._refresh_lists(select_step=j)

    def _remove_step(self):
        sel = self.step_list.curselection()
        if sel:
            del self.cfg["steps"][sel[0]]
            self._save()
            self._refresh_lists(select_step=max(0, sel[0] - 1))

    def _refresh_lists(self, select_step=None):
        self.item_list.delete(0, "end")
        for it in self.cfg["items"]:
            self.item_list.insert("end", describe_item(it))
        self.step_list.delete(0, "end")
        for i, st in enumerate(self.cfg["steps"], 1):
            self.step_list.insert("end", describe_step(i, st))
        if select_step is not None and self.cfg["steps"]:
            self.step_list.selection_set(min(select_step, len(self.cfg["steps"]) - 1))

    def _start(self):
        if self.engine and self.engine.is_alive():
            return
        if not self.cfg["steps"]:
            messagebox.showinfo("HK", "Workflow is empty. Please add workflow steps first.")
            return
        adb = self._get_adb()
        if not adb:
            return
        try:
            threshold = float(self.thr_var.get())
            loops = int(self.loops_var.get())
        except (ValueError, tk.TclError):
            return
        self._save()
        items = {i["name"]: i for i in self.cfg["items"]}
        self.engine = Engine(adb, items, list(self.cfg["steps"]), self.live_var.get(),
                             threshold, float(self.cfg["poll"]), 2.0, loops)
        self.engine.start()
        self._set_running(True)

    def _toggle_pause_resume(self):
        if not self.engine or not self.engine.is_alive():
            return
        if self.engine.paused:
            self.engine.resume()
            self.pause_resume_btn.config(text="Pause", bg="#ef6c00")
            mode_str = "Live Taps" if self.engine.live else "Test Mode (Dry Run)"
            self.status_var.set(f"Status: Running ({mode_str})")
        else:
            self.engine.pause()
            self.pause_resume_btn.config(text="Resume", bg="#2e7d32")
            self.status_var.set("Status: Paused")

    def _stop(self):
        if self.engine and self.engine.is_alive():
            self.engine.stop()
            self.status_var.set("Status: Stopping...")

    def _set_running(self, running):
        self.start_btn.config(state="disabled" if running else "normal")
        self.pause_resume_btn.config(state="normal" if running else "disabled", text="Pause", bg="#ef6c00")
        self.stop_btn.config(state="normal" if running else "disabled")
        if running:
            mode_str = "Live Taps" if self.live_var.get() else "Test Mode (Dry Run)"
            self.status_var.set(f"Status: Running ({mode_str})")
        else:
            self.status_var.set("Status: Idle (Ready)")

    def _poll_log(self):
        try:
            while True:
                msg = log_queue.get_nowait()
                if msg is FINISHED:
                    self._set_running(False)
                    continue
                self.log_text.config(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.config(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    def _save(self):
        self.cfg["adb"] = self.adb_var.get().strip()
        self.cfg["serial"] = self.dev_var.get().strip()
        try:
            self.cfg["threshold"] = float(self.thr_var.get())
            self.cfg["loops"] = int(self.loops_var.get())
        except (ValueError, tk.TclError):
            pass
        try:
            CONFIG_PATH.write_text(json.dumps(self.cfg, indent=2), encoding="utf-8")
        except OSError as exc:
            log.error("Save config error: %s", exc)

    def _on_close(self):
        if self.engine and self.engine.is_alive():
            self.engine.stop()
        self._save()
        self.destroy()


if __name__ == "__main__":
    if ensure_license():
        App().mainloop()