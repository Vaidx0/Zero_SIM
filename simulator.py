#!/usr/bin/env python3
import argparse
import ctypes
import json
import os
import queue
import re
import shutil
import stat
import subprocess
import sys
import threading
from pathlib import Path

# ─── Try to boot the GUI; auto-install tkinter if missing, fall back to CLI ───
def _ensure_tkinter() -> bool:
    """Return True if tkinter is (or becomes) importable, False otherwise."""
    try:
        import tkinter  # noqa: F401
        return True
    except ImportError:
        pass

    # Only attempt auto-install on Linux/WSL where apt-get is available
    if shutil.which("apt-get") is None or shutil.which("sudo") is None:
        return False

    # Detect the exact python3.X-tk package name for the running interpreter
    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    pkg = f"python{ver}-tk"

    print(f"[Zero_Sim] tkinter not found – installing {pkg} …")
    result = subprocess.run(
        ["sudo", "apt-get", "install", "-y", pkg],
        text=True,
    )
    if result.returncode != 0:
        print(f"[Zero_Sim] apt-get failed (exit {result.returncode}). "
              "Try:  sudo apt-get install python3-tk")
        return False

    # Verify the install worked
    try:
        import tkinter  # noqa: F401
        print("[Zero_Sim] tkinter installed successfully.")
        return True
    except ImportError:
        return False


try:
    import tkinter as tk
    from tkinter import font as tkfont
    from tkinter import messagebox, simpledialog, ttk
    _HAS_TK = True
except ImportError:
    _HAS_TK = _ensure_tkinter()
    if _HAS_TK:
        # Successful auto-install: re-import for real
        import tkinter as tk
        from tkinter import font as tkfont
        from tkinter import messagebox, simpledialog, ttk

if not _HAS_TK:
    # Minimal stubs so module-level GUI class definitions don't raise NameError
    # when tkinter is absent.  None of this is ever *called* without _HAS_TK.
    class _Stub:
        """Placeholder that silently absorbs attribute look-ups."""
        def __getattr__(self, _):
            return _Stub()
        def __call__(self, *a, **kw):
            return _Stub()

    class tk:
        Tk        = object
        Frame     = _Stub
        Label     = _Stub
        Text      = _Stub
        Scrollbar = _Stub
        StringVar = _Stub
        Toplevel  = _Stub
        END       = "end"
        BOTH      = "both"
        LEFT      = "left"
        RIGHT     = "right"
        X         = "x"
        Y         = "y"
        W         = "w"
        WORD      = "word"
        NORMAL    = "normal"
        DISABLED  = "disabled"
        FLAT      = "flat"
        SUNKEN    = "sunken"
        RAISED    = "raised"
        RIDGE     = "ridge"

    ttk          = _Stub()
    messagebox   = _Stub()
    simpledialog = _Stub()

# ─── Paths / settings ─────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
ENV_ROOT   = os.environ.get("ZERO_SIM_ROOT", "").strip()
ROOT       = Path(ENV_ROOT).resolve() if ENV_ROOT and Path(ENV_ROOT).exists() else SCRIPT_DIR

SETTINGS_FILE     = ROOT / ".zero_sim_settings.json"
CLEAN_MARKER_FILE = ROOT / ".zero_sim_cleaned"
DEFAULT_SETTINGS  = {"theme": "light"}


# ═══════════════════════════════════════════════════════════════════════════════
#  CORE HELPERS  (shared by GUI and CLI)
# ═══════════════════════════════════════════════════════════════════════════════

def npm_command() -> list[str]:
    if os.name == "nt":
        cmd = shutil.which("npm.cmd")
        if cmd:
            return [cmd]
    cmd = shutil.which("npm")
    if cmd:
        return [cmd]
    raise RuntimeError("npm not found in PATH.  Install Node.js and reopen the terminal.")


def load_settings() -> dict:
    if not SETTINGS_FILE.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return dict(DEFAULT_SETTINGS)
    if not isinstance(data, dict):
        return dict(DEFAULT_SETTINGS)
    merged = dict(DEFAULT_SETTINGS)
    merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    return merged


def save_settings(settings: dict) -> None:
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def clone_cleanup_once() -> None:
    if CLEAN_MARKER_FILE.exists():
        return
    for target in (ROOT / "assets", ROOT / "LICENSE", ROOT / ".gitignore"):
        try:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink(missing_ok=True)
        except Exception:
            pass
    CLEAN_MARKER_FILE.write_text("cleaned\n", encoding="utf-8")


def _is_executable_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.suffix.lower() in {".ttf", ".txt", ".json", ".o", ".a"}:
        return False
    if os.name == "nt":
        return path.suffix.lower() in {".exe", ".cmd", ".bat"} or path.name == path.stem
    mode = path.stat().st_mode
    return bool(mode & stat.S_IXUSR)


def locate_built_binary(appid: str) -> Path | None:
    out_dir = ROOT / f"out_{appid}"
    if not out_dir.exists():
        return None
    preferred = out_dir / appid
    if preferred.exists() and _is_executable_file(preferred):
        return preferred
    if os.name == "nt":
        pc = preferred.with_suffix(".cmd")
        if pc.exists():
            return pc
    for candidate in out_dir.iterdir():
        if _is_executable_file(candidate):
            return candidate
    return None


def detect_last_built_appid() -> str | None:
    for d in sorted((p for p in ROOT.glob("out_*") if p.is_dir()), reverse=True):
        appid = d.name.replace("out_", "", 1)
        if locate_built_binary(appid):
            return appid
    return None


def parse_appid(app_folder: str) -> str:
    fam = ROOT / app_folder / "application.fam"
    if not fam.exists():
        raise FileNotFoundError(f"Manifest not found: {fam}")
    text  = fam.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r'appid\s*=\s*"([^"]+)"', text)
    if not match:
        raise RuntimeError("Cannot parse appid from application.fam")
    return match.group(1)


def resolve_appid(target: str | None) -> str:
    if not target:
        auto = detect_last_built_appid()
        if auto:
            return auto
        raise RuntimeError("No built app found.  Run:  python simulator.py build <app_folder>")
    path = ROOT / target
    if path.is_dir() and (path / "application.fam").exists():
        return parse_appid(target)
    return target


def missing_apt_packages(packages: list[str]) -> list[str]:
    missing = []
    for pkg in packages:
        result = subprocess.run(["dpkg", "-s", pkg],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
            missing.append(pkg)
    return missing


def ensure_unix_dependencies_tooling() -> None:
    for tool in ("dpkg", "apt-get", "sudo"):
        if shutil.which(tool) is None:
            raise RuntimeError("Linux dependency tools missing.  Run from WSL/Linux terminal.")


# ═══════════════════════════════════════════════════════════════════════════════
#  TASK RUNNER  – streams stdout/stderr to a queue consumed by the GUI log
# ═══════════════════════════════════════════════════════════════════════════════

class TaskRunner:
    """Runs blocking shell tasks in a background thread; pushes log lines to a queue."""

    def __init__(self, log_queue: "queue.Queue[str]"):
        self.q = log_queue

    def _put(self, text: str) -> None:
        self.q.put(text)

    def run_cmd(self, title: str, cmd: list[str], input_text: str | None = None) -> subprocess.CompletedProcess:
        self._put(f"\n▶  {title}")
        self._put(f"   $ {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=ROOT, input=input_text,
                                text=True, capture_output=True)
        for line in (result.stdout or "").splitlines():
            if line.strip():
                self._put("   " + line)
        for line in (result.stderr or "").splitlines():
            if line.strip():
                self._put("   " + line)
        if result.returncode != 0:
            raise RuntimeError(
                f"Command exited {result.returncode}: {' '.join(cmd)}\n"
                + ((result.stdout or "") + (result.stderr or "")).strip()
            )
        return result

    # ── actual tasks ──────────────────────────────────────────────────────────

    def task_deps(self) -> None:
        if not (ROOT / "package.json").exists():
            raise FileNotFoundError(f"package.json not found in {ROOT}.")
        self.run_cmd("Update git submodules",
                     ["git", "submodule", "update", "--init", "--recursive"])
        self.run_cmd("Install npm packages", [*npm_command(), "install"])
        ensure_unix_dependencies_tooling()
        apt_pkgs = [
            "build-essential","gcc","g++","make","pkg-config","jq","git","curl",
            "ca-certificates","nodejs","npm","python3","python3-pip","python3-rich",
            "libsdl2-dev","libsdl2-ttf-dev","libsdl2-image-dev","libsdl2-mixer-dev",
            "libbsd-dev","libbsd-dev:i386","gcc-multilib","g++-multilib","gdb","x11-apps",
        ]
        self.run_cmd("Enable i386 arch", ["sudo", "dpkg", "--add-architecture", "i386"])
        self.run_cmd("apt update",        ["sudo", "apt-get", "update"])
        missing = missing_apt_packages(apt_pkgs)
        if missing:
            self._put(f"   Missing packages: {' '.join(missing)}")
            self.run_cmd("Install apt packages",
                         ["sudo", "apt-get", "install", "-y", *missing])
        else:
            self._put("   ✓ All apt packages already installed.")
        self._put("\n✅  Dependencies ready.")

    def task_build(self, app_folder: str) -> None:
        app_path = ROOT / app_folder
        if not app_path.exists():
            raise FileNotFoundError(f"App folder not found: {app_path}")
        appid = parse_appid(app_folder)
        self._put(f"\n▶  Build  →  {app_folder}  (appid: {appid})")
        completed = self.run_cmd("Compile", [*npm_command(), "start"],
                                 input_text=f"{app_folder}\n")
        out_bin = locate_built_binary(appid)
        if not out_bin:
            build_log = ((completed.stdout or "") + (completed.stderr or "")).strip()
            if "cannot find -lbsd" in build_log:
                raise RuntimeError("Missing 32-bit libbsd.  Run deps first.")
            self._put("[yellow] Binary missing – retrying verbose…")
            self.run_cmd("Compile (verbose)", [*npm_command(), "start"],
                         input_text=f"{app_folder}\n")
            out_bin = locate_built_binary(appid)
        if not out_bin:
            raise FileNotFoundError(
                f"Build finished but binary not found in out_{appid}.")
        self._put(f"\n✅  Build complete  →  {out_bin}")

    def task_run(self, target: str | None) -> None:
        appid   = resolve_appid(target)
        bin_path = locate_built_binary(appid)
        if not bin_path:
            raise FileNotFoundError(
                f"Binary not found for '{appid}'.  Build first.")
        self._put(f"\n▶  Launching  {bin_path}")
        run_env = os.environ.copy()
        run_env["ZERO_SIM_THEME"] = load_settings().get("theme", "light")
        result = subprocess.run([str(bin_path)], cwd=ROOT, env=run_env,
                                text=True, capture_output=True)
        for line in (result.stdout or "").splitlines():
            self._put("   " + line)
        for line in (result.stderr or "").splitlines():
            self._put("   " + line)
        if result.returncode != 0:
            raise RuntimeError(f"Simulator exited with code {result.returncode}")
        self._put("\n✅  Simulator exited cleanly.")


# ═══════════════════════════════════════════════════════════════════════════════
#  GUI
# ═══════════════════════════════════════════════════════════════════════════════

# ── palette ───────────────────────────────────────────────────────────────────
C = {
    "bg":          "#0F1117",   # window background
    "surface":     "#1A1D23",   # panels / cards
    "surface2":    "#22262E",   # subtle inset / toolbar
    "border":      "#2E3340",   # dividers
    "accent":      "#3B6FE8",   # primary action blue
    "accent_h":    "#5484F5",   # hover (lighter for dark bg)
    "accent_text": "#FFFFFF",
    "danger":      "#E84545",
    "success":     "#22C55E",
    "warn":        "#F59E0B",
    "fg":          "#E2E8F0",   # primary text
    "fg2":         "#8B95A5",   # secondary text
    "log_bg":      "#080A0F",   # deep console
    "log_fg":      "#D4D9E3",
    "log_ok":      "#6EE7B7",
    "log_err":     "#F87171",
    "log_cmd":     "#93C5FD",
    "log_dim":     "#4B5563",
}


class ZeroSimApp(tk.Tk):

    def __init__(self):
        super().__init__()
        # Style must be set up on *this* Tk instance, not before it's created,
        # otherwise tkinter spawns a second blank root window.
        _style = ttk.Style(self)
        try:
            _style.theme_use("clam")
        except Exception:
            pass
        # Dark ttk overrides so Combobox / Scrollbar match the palette
        _style.configure("TCombobox",
                         fieldbackground=C["surface2"],
                         background=C["surface2"],
                         foreground=C["fg"],
                         selectbackground=C["accent"],
                         selectforeground=C["accent_text"],
                         arrowcolor=C["fg2"])
        _style.map("TCombobox",
                   fieldbackground=[("readonly", C["surface2"])],
                   foreground=[("readonly", C["fg"])])
        _style.configure("TScrollbar",
                         background=C["surface2"],
                         troughcolor=C["bg"],
                         arrowcolor=C["fg2"],
                         bordercolor=C["border"])

        self.title("Zero_Sim  ·  Runner")
        self.configure(bg=C["bg"])
        self.geometry("880x600")
        self.minsize(720, 480)
        self._apply_native_window_theme()

        self._settings   = load_settings()
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._runner     = TaskRunner(self._log_queue)
        self._busy       = False
        self._deps_completed = False
        self._build_completed = False

        self._build_ui()
        self._poll_log()

    def _apply_native_window_theme(self) -> None:
        """Apply native dark titlebar/borders on Windows when available."""
        if sys.platform != "win32":
            return
        try:
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            value = ctypes.c_int(1)
            # DWMWA_USE_IMMERSIVE_DARK_MODE = 20 on modern Windows builds.
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                20,
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        except Exception:
            # Non-fatal: keep default non-client rendering if unsupported.
            pass

    # ── layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── top bar ───────────────────────────────────────────────────────────
        topbar = tk.Frame(self, bg=C["surface"], height=56)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)

        # logo / title
        lbl = tk.Label(topbar, text="Zero_Sim", bg=C["surface"],
                       fg=C["fg"], font=("Helvetica Neue", 15, "bold"))
        lbl.pack(side="left", padx=20)

        sep = tk.Frame(topbar, bg=C["border"], width=1)
        sep.pack(side="left", fill="y", pady=10)

        # action buttons
        btn_defs = [
            ("1) ⬇  Dependencies", self._action_deps,   C["surface2"],  C["fg"]),
            ("2) ⚙  Build",        self._action_build,  C["accent"],    C["accent_text"]),
            ("3) ▶  Run",          self._action_run,    C["accent"],    C["accent_text"]),
        ]
        self._action_btns = []
        for label, cmd, bg, fg in btn_defs:
            b = self._make_btn(topbar, label, cmd, bg, fg)
            b.pack(side="left", padx=(10, 0), pady=12)
            self._action_btns.append(b)

        # settings gear on the right
        gear = self._make_btn(topbar, "⚙  Settings", self._action_settings,
                              C["surface2"], C["fg"])
        gear.pack(side="right", padx=18, pady=12)

        # ── thin separator ────────────────────────────────────────────────────
        tk.Frame(self, bg=C["border"], height=1).pack(fill="x")

        # ── status bar below topbar ───────────────────────────────────────────
        statusbar = tk.Frame(self, bg=C["surface2"], height=32)
        statusbar.pack(fill="x")
        statusbar.pack_propagate(False)

        self._status_dot  = tk.Label(statusbar, text="●", bg=C["surface2"],
                                     fg=C["success"], font=("Helvetica Neue", 10))
        self._status_dot.pack(side="left", padx=(14, 4))

        self._status_text = tk.Label(statusbar, text="Ready",
                                     bg=C["surface2"], fg=C["fg2"],
                                     font=("Helvetica Neue", 10))
        self._status_text.pack(side="left")

        self._spinner_lbl = tk.Label(statusbar, text="", bg=C["surface2"],
                                     fg=C["accent"], font=("Helvetica Neue", 10))
        self._spinner_lbl.pack(side="right", padx=14)

        # ── info cards row ────────────────────────────────────────────────────
        cards = tk.Frame(self, bg=C["bg"])
        cards.pack(fill="x", padx=16, pady=(12, 0))

        self._card_root   = self._make_card(cards, "Root", str(ROOT))
        self._card_appid  = self._make_card(cards, "Last Build",
                                            detect_last_built_appid() or "—")
        self._card_theme  = self._make_card(cards, "Theme",
                                            self._settings.get("theme", "light").title())

        for c in (self._card_root, self._card_appid, self._card_theme):
            c.pack(side="left", fill="x", expand=True, padx=(0, 10))

        # ── console ───────────────────────────────────────────────────────────
        console_frame = tk.Frame(self, bg=C["bg"])
        console_frame.pack(fill="both", expand=True, padx=16, pady=12)

        hdr = tk.Frame(console_frame, bg=C["bg"])
        hdr.pack(fill="x")

        tk.Label(hdr, text="Console  /  Log", bg=C["bg"],
                 fg=C["fg2"], font=("Helvetica Neue", 9, "bold")).pack(side="left")

        clear_btn = tk.Label(hdr, text="Clear", bg=C["bg"], fg=C["accent"],
                             font=("Helvetica Neue", 9), cursor="hand2")
        clear_btn.pack(side="right")
        clear_btn.bind("<Button-1>", lambda _: self._clear_log())

        # console text widget in a dark card
        log_card = tk.Frame(console_frame, bg=C["log_bg"],
                            highlightbackground=C["border"], highlightthickness=1)
        log_card.pack(fill="both", expand=True, pady=(6, 0))

        self._log = tk.Text(
            log_card,
            bg=C["log_bg"], fg=C["log_fg"],
            font=("Courier New", 10),
            wrap="word",
            relief="flat", bd=0,
            highlightthickness=0,
            padx=14, pady=12,
            state="disabled",
            cursor="arrow",
            insertbackground=C["fg"],
            selectbackground=C["accent"],
            selectforeground=C["accent_text"],
        )
        sb = ttk.Scrollbar(log_card, command=self._log.yview)
        self._log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log.pack(fill="both", expand=True)

        # colour tags
        self._log.tag_configure("ok",  foreground=C["log_ok"])
        self._log.tag_configure("err", foreground=C["log_err"])
        self._log.tag_configure("cmd", foreground=C["log_cmd"])
        self._log.tag_configure("dim", foreground=C["log_dim"])
        self._log.tag_configure("hdr", foreground="#E2E8F0",
                                font=("Courier New", 10, "bold"))

        self._log_write("Zero_Sim Runner  –  ready.", "hdr")
        self._log_write(f"Root: {ROOT}", "dim")

    # ── helpers ───────────────────────────────────────────────────────────────

    def _make_btn(self, parent, text, command, bg, fg) -> tk.Label:
        btn = tk.Label(parent, text=text, bg=bg, fg=fg,
                       font=("Helvetica Neue", 10, "bold"),
                       padx=14, pady=6, cursor="hand2",
                       relief="flat")
        btn.bind("<Button-1>",    lambda _: command())
        btn.bind("<Enter>",       lambda _, b=btn, c=bg: b.configure(
                                      bg=C["accent_h"] if bg == C["accent"] else C["border"]))
        btn.bind("<Leave>",       lambda _, b=btn, c=bg: b.configure(bg=bg))
        return btn

    def _make_card(self, parent, title: str, value: str) -> tk.Frame:
        card = tk.Frame(parent, bg=C["surface"],
                        highlightbackground=C["border"], highlightthickness=1)
        tk.Label(card, text=title, bg=C["surface"], fg=C["fg2"],
                 font=("Helvetica Neue", 8, "bold"),
                 padx=12).pack(anchor="w", pady=(8, 2))
        lbl = tk.Label(card, text=value, bg=C["surface"], fg=C["fg"],
                       font=("Helvetica Neue", 10),
                       padx=12, wraplength=220, justify="left")
        lbl.pack(anchor="w", pady=(0, 8))
        card._val_lbl = lbl          # type: ignore[attr-defined]
        return card

    def _update_card(self, card: tk.Frame, value: str):
        card._val_lbl.configure(text=value)  # type: ignore[attr-defined]

    # ── log ───────────────────────────────────────────────────────────────────

    def _log_write(self, text: str, tag: str = "") -> None:
        self._log.configure(state="normal")
        self._log.insert("end", text + "\n", tag)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _log_write_batch(self, items: list[tuple[str, str]]) -> None:
        if not items:
            return
        self._log.configure(state="normal")
        for text, tag in items:
            self._log.insert("end", text + "\n", tag)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _classify(self, line: str) -> str:
        if line.startswith("✅"):  return "ok"
        if line.startswith("▶"):   return "hdr"
        if line.startswith("   $"): return "cmd"
        if "error" in line.lower() or "failed" in line.lower() or line.startswith("❌"):
            return "err"
        if line.startswith("   "): return "dim"
        return ""

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _poll_log(self):
        pending: list[tuple[str, str]] = []
        try:
            # Batch log insertions to keep UI smooth while tasks stream output.
            for _ in range(250):
                line = self._log_queue.get_nowait()
                pending.append((line, self._classify(line)))
        except queue.Empty:
            pass
        self._log_write_batch(pending)
        self.after(33 if self._busy else 80, self._poll_log)

    # ── busy state ────────────────────────────────────────────────────────────

    _SPIN = ("◐", "◓", "◑", "◒")
    _spin_idx = 0

    def _set_busy(self, busy: bool, label: str = ""):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for b in self._action_btns:
            b.configure(cursor="watch" if busy else "hand2")

        if busy:
            self._status_text.configure(text=label)
            self._status_dot.configure(fg=C["warn"])
            self._animate_spinner()
        else:
            self._status_text.configure(text="Ready")
            self._status_dot.configure(fg=C["success"])
            self._spinner_lbl.configure(text="")
            self._update_card(self._card_appid,
                              detect_last_built_appid() or "—")

    def _animate_spinner(self):
        if not self._busy:
            return
        ZeroSimApp._spin_idx = (ZeroSimApp._spin_idx + 1) % 4
        self._spinner_lbl.configure(text=self._SPIN[ZeroSimApp._spin_idx])
        self.after(120, self._animate_spinner)

    # ── run task in thread ────────────────────────────────────────────────────

    def _run_task(self, label: str, fn):
        if self._busy:
            messagebox.showwarning("Busy", "Another task is already running.")
            return

        def _worker():
            try:
                fn()
            except Exception as exc:
                self._log_queue.put(f"\n❌  {exc}")
            finally:
                self.after(0, self._set_busy, False)

        self._set_busy(True, label)
        threading.Thread(target=_worker, daemon=True).start()

    # ── actions ───────────────────────────────────────────────────────────────

    def _action_deps(self):
        def _deps_task():
            self._runner.task_deps()
            self._deps_completed = True
            self._build_completed = False
        self._run_task("Installing dependencies…", _deps_task)

    def _action_build(self):
        if not self._deps_completed:
            messagebox.showwarning("Required order", "You must click Dependencies first.")
            return
        app = simpledialog.askstring("Build",
                                     "App folder name:",
                                     initialvalue="example_hello_world",
                                     parent=self)
        if not app:
            return

        app_name = app.strip()

        def _build_task():
            self._runner.task_build(app_name)
            self._build_completed = True

        self._run_task(f"Building {app_name}…", _build_task)

    def _action_run(self):
        if not self._deps_completed:
            messagebox.showwarning("Required order", "You must click Dependencies first.")
            return
        if not self._build_completed:
            messagebox.showwarning("Required order", "You must click Build before Run.")
            return
        last = detect_last_built_appid() or ""
        target = simpledialog.askstring("Run",
                                        "App id or folder (empty = last build):",
                                        initialvalue=last,
                                        parent=self)
        if target is None:
            return
        self._run_task("Running simulator…",
                       lambda: self._runner.task_run(target.strip() or None))

    def _action_settings(self):
        win = tk.Toplevel(self)
        win.title("Settings")
        win.configure(bg=C["surface"])
        win.geometry("340x200")
        win.resizable(False, False)

        tk.Label(win, text="Settings", bg=C["surface"], fg=C["fg"],
                 font=("Helvetica Neue", 13, "bold"),
                 padx=20).pack(anchor="w", pady=(16, 8))

        tk.Frame(win, bg=C["border"], height=1).pack(fill="x", padx=20)

        row = tk.Frame(win, bg=C["surface"])
        row.pack(fill="x", padx=20, pady=16)
        tk.Label(row, text="Theme:", bg=C["surface"], fg=C["fg2"],
                 font=("Helvetica Neue", 10), width=10, anchor="w").pack(side="left")

        theme_var = tk.StringVar(value=self._settings.get("theme", "light"))
        cb = ttk.Combobox(row, textvariable=theme_var,
                          values=["light", "dark"], state="readonly", width=14)
        cb.pack(side="left", padx=8)

        def _save():
            self._settings["theme"] = theme_var.get()
            save_settings(self._settings)
            self._update_card(self._card_theme, theme_var.get().title())
            win.destroy()

        tk.Frame(win, bg=C["border"], height=1).pack(fill="x", padx=20)

        btn_row = tk.Frame(win, bg=C["surface"])
        btn_row.pack(fill="x", padx=20, pady=16)

        cancel_b = tk.Label(btn_row, text="Cancel", bg=C["surface2"], fg=C["fg2"],
                            font=("Helvetica Neue", 10),
                            padx=14, cursor="hand2")
        cancel_b.pack(side="right", padx=(8, 0))
        cancel_b.bind("<Button-1>", lambda _: win.destroy())
        cancel_b.bind("<Enter>", lambda _: cancel_b.configure(fg=C["fg"]))
        cancel_b.bind("<Leave>", lambda _: cancel_b.configure(fg=C["fg2"]))

        save_b = tk.Label(btn_row, text="Save", bg=C["accent"], fg=C["accent_text"],
                          font=("Helvetica Neue", 10, "bold"),
                          padx=18, cursor="hand2")
        save_b.pack(side="right")
        save_b.bind("<Button-1>", lambda _: _save())
        save_b.bind("<Enter>", lambda _: save_b.configure(bg=C["accent_h"]))
        save_b.bind("<Leave>", lambda _: save_b.configure(bg=C["accent"]))

        # grab_set must come AFTER all widgets are packed and the window is
        # fully rendered; on WSL/X11 it can fail if called too early.
        win.update_idletasks()
        try:
            win.grab_set()
        except Exception:
            pass  # Non-fatal on some WSL/X11 setups – window still works


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI  (fallback / scripting)
# ═══════════════════════════════════════════════════════════════════════════════

class _CliLog(queue.Queue):
    """Drains immediately to stdout."""
    def put(self, item, *a, **kw):
        print(item)


def cli_run_step(title, cmd, input_text=None):
    print(f"\n▶  {title}")
    print(f"   $ {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=ROOT, input=input_text,
                       text=True, capture_output=True)
    if r.stdout: print(r.stdout.rstrip())
    if r.stderr: print(r.stderr.rstrip())
    if r.returncode != 0:
        raise RuntimeError(f"Exited {r.returncode}: {' '.join(cmd)}")
    return r


def cmd_deps(_args=None):
    runner = TaskRunner(_CliLog())
    runner.task_deps()


def cmd_build(args):
    runner = TaskRunner(_CliLog())
    runner.task_build(args.app)


def cmd_run(args):
    runner = TaskRunner(_CliLog())
    runner.task_run(getattr(args, "target", None))


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    clone_cleanup_once()

    # ── GUI mode ──────────────────────────────────────────────────────────────
    if len(sys.argv) == 1:
        if _HAS_TK:
            app = ZeroSimApp()
            app.mainloop()
        else:
            print("tkinter not available – falling back to CLI.")
            print("Usage: python simulator.py {deps|build <app>|run [target]}")
        return

    # ── CLI mode ──────────────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(description="Zero_Sim helper")
    sub    = parser.add_subparsers(dest="cmd", required=True)

    p_deps = sub.add_parser("deps",  help="Install/check dependencies")
    p_deps.set_defaults(func=cmd_deps)

    p_build = sub.add_parser("build", help="Build an app folder")
    p_build.add_argument("app", help="App folder name")
    p_build.set_defaults(func=cmd_build)

    p_run = sub.add_parser("run", help="Run simulator")
    p_run.add_argument("target", nargs="?", help="App id or folder")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as exc:
        print(f"\n❌  {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()