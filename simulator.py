#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Prompt
from rich.table import Table

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_ROOT = os.environ.get("ZERO_SIM_ROOT", "").strip()
ROOT = Path(ENV_ROOT).resolve() if ENV_ROOT and Path(ENV_ROOT).exists() else SCRIPT_DIR

SETTINGS_FILE = ROOT / ".zero_sim_settings.json"
CLEAN_MARKER_FILE = ROOT / ".zero_sim_cleaned"
DEFAULT_SETTINGS = {"theme": "dark"}
console = Console()


def npm_command() -> list[str]:
    if os.name == "nt":
        cmd = shutil.which("npm.cmd")
        if cmd:
            return [cmd]
    cmd = shutil.which("npm")
    if cmd:
        return [cmd]
    raise RuntimeError("npm not found in PATH. Install Node.js and reopen terminal.")


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


def theme_styles(settings: dict) -> dict:
    if settings.get("theme", "dark") == "light":
        return {
            "header": "bold #1f2937",
            "option": "#374151",
            "action": "#111827",
            "border": "#9ca3af",
        }
    return {
        "header": "bold #d1d5db",
        "option": "#9ca3af",
        "action": "#e5e7eb",
        "border": "#6b7280",
    }


def clear_terminal() -> None:
    # Rich clear is not always enough in WSL terminals.
    console.clear()
    os.system("cls" if os.name == "nt" else "clear")
    print("\033[2J\033[H", end="")


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


def run_step(title: str, cmd: list[str], quiet: bool = True, input_text: str | None = None) -> subprocess.CompletedProcess:
    if quiet:
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(title, total=None)
            completed = subprocess.run(
                cmd,
                cwd=ROOT,
                input=input_text,
                text=True,
                capture_output=True,
            )
            progress.update(task, completed=1)
    else:
        console.print(f"[cyan]$ {' '.join(cmd)}[/cyan]")
        completed = subprocess.run(
            cmd,
            cwd=ROOT,
            input=input_text,
            text=True,
            capture_output=True,
        )
        if completed.stdout:
            console.print(completed.stdout.rstrip())
        if completed.stderr:
            console.print(completed.stderr.rstrip())

    if completed.returncode != 0:
        output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip() or "No command output"
        console.print(Panel(output, title=f"Failed: {' '.join(cmd)}", border_style="red"))
        raise RuntimeError(f"Command failed with exit code {completed.returncode}: {' '.join(cmd)}")

    return completed


def parse_appid(app_folder: str) -> str:
    fam = ROOT / app_folder / "application.fam"
    if not fam.exists():
        raise FileNotFoundError(f"Manifest not found: {fam}")
    text = fam.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r'appid\s*=\s*"([^"]+)"', text)
    if not match:
        raise RuntimeError("Cannot parse appid from application.fam")
    return match.group(1)


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
        preferred_cmd = preferred.with_suffix(".cmd")
        if preferred_cmd.exists():
            return preferred_cmd
    for candidate in out_dir.iterdir():
        if _is_executable_file(candidate):
            return candidate
    return None


def detect_last_built_appid() -> str | None:
    for directory in sorted((p for p in ROOT.glob("out_*") if p.is_dir()), reverse=True):
        appid = directory.name.replace("out_", "", 1)
        if locate_built_binary(appid):
            return appid
    return None


def missing_apt_packages(packages: list[str]) -> list[str]:
    missing = []
    for pkg in packages:
        result = subprocess.run(["dpkg", "-s", pkg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
            missing.append(pkg)
    return missing


def ensure_unix_dependencies_tooling() -> None:
    for tool in ("dpkg", "apt-get", "sudo"):
        if shutil.which(tool) is None:
            raise RuntimeError("Linux dependency tools missing. Run from WSL/Linux terminal.")


def cmd_deps(_args=None) -> None:
    console.rule("[bold cyan]Dependencies")
    if not (ROOT / "package.json").exists():
        raise FileNotFoundError(f"package.json not found in {ROOT}. Repository seems incomplete.")

    run_step("Updating git submodules", ["git", "submodule", "update", "--init", "--recursive"], quiet=True)
    run_step("Installing npm packages", [*npm_command(), "install"], quiet=True)
    ensure_unix_dependencies_tooling()

    apt_pkgs = [
        "build-essential", "gcc", "g++", "make", "pkg-config", "jq", "git", "curl", "ca-certificates",
        "nodejs", "npm", "python3", "python3-pip", "python3-rich", "libsdl2-dev", "libsdl2-ttf-dev",
        "libsdl2-image-dev", "libsdl2-mixer-dev", "libbsd-dev", "libbsd-dev:i386", "gcc-multilib", "g++-multilib", "gdb", "x11-apps",
    ]
    run_step("Enable i386 architecture", ["sudo", "dpkg", "--add-architecture", "i386"], quiet=False)
    run_step("Running apt update", ["sudo", "apt-get", "update"], quiet=False)

    missing = missing_apt_packages(apt_pkgs)
    if missing:
        console.print(f"[yellow]Missing apt packages ({len(missing)}):[/yellow] {' '.join(missing)}")
        run_step("Installing missing apt packages", ["sudo", "apt-get", "install", "-y", *missing], quiet=False)
    else:
        console.print("[green]All required apt packages are already installed.[/green]")

    console.print("[bold green]Dependencies ready.[/bold green]")


def cmd_build(args) -> None:
    app_folder = args.app
    app_path = ROOT / app_folder
    if not app_path.exists():
        raise FileNotFoundError(f"App folder not found: {app_path}")

    appid = parse_appid(app_folder)
    console.rule(f"[bold cyan]Build {app_folder}")
    completed = run_step("Compiling app", [*npm_command(), "start"], quiet=True, input_text=f"{app_folder}\n")

    out_bin = locate_built_binary(appid)
    if not out_bin:
        build_log = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
        if build_log:
            lines = build_log.splitlines()
            if len(lines) > 120:
                build_log = "\n".join(lines[-120:])
            console.print(Panel(build_log, title="Build output", border_style="yellow"))
        if "cannot find -lbsd" in build_log:
            raise RuntimeError("Missing 32-bit libbsd during link. Run: python simulator.py deps (in WSL)")
        # Retry once in verbose mode to expose full compiler errors.
        console.print("[yellow]Binary missing after build, retrying with verbose logs...[/yellow]")
        run_step("Compiling app (verbose)", [*npm_command(), "start"], quiet=False, input_text=f"{app_folder}\n")
        out_bin = locate_built_binary(appid)

    if not out_bin:
        raise FileNotFoundError(
            f"Build finished but binary not found in out_{appid}. Check the build logs above for compile errors."
        )

    console.print(f"[bold green]Build complete[/bold green]: {out_bin}")


def resolve_appid(target: str | None) -> str:
    if not target:
        auto = detect_last_built_appid()
        if auto:
            return auto
        raise RuntimeError("No built app found. Run: python simulator.py build <app_folder>")

    path = ROOT / target
    if path.is_dir() and (path / "application.fam").exists():
        return parse_appid(target)

    return target


def cmd_run(args) -> None:
    appid = resolve_appid(args.target)
    bin_path = locate_built_binary(appid)
    if not bin_path:
        raise FileNotFoundError(f"Binary not found for appid '{appid}'. Build first with: python simulator.py build <app_folder>")
    console.rule("[bold cyan]Run Simulator")
    console.print(f"[green]Launching:[/green] {bin_path}")
    run_env = os.environ.copy()
    run_env["ZERO_SIM_THEME"] = load_settings().get("theme", "dark")
    subprocess.run([str(bin_path)], cwd=ROOT, env=run_env, check=True)


def interactive_menu() -> None:
    settings = load_settings()
    while True:
        clear_terminal()
        styles = theme_styles(settings)
        table = Table(title="Zero_Sim Runner", header_style=styles["header"], border_style=styles["border"])
        table.add_column("Option", style=styles["option"], width=8)
        table.add_column("Action", style=styles["action"])
        table.add_row("1", "Install dependencies")
        table.add_row("2", "Build an app")
        table.add_row("3", "Run simulator")
        table.add_row("4", "Settings")
        table.add_row("5", "Quit")
        console.print(table)

        choice = Prompt.ask("Select", choices=["1", "2", "3", "4", "5"], default="3")
        try:
            if choice == "1":
                cmd_deps(None)
            elif choice == "2":
                app = Prompt.ask("App folder", default="example_hello_world").strip()
                class Args: pass
                args = Args()
                args.app = app
                cmd_build(args)
            elif choice == "3":
                target = Prompt.ask("App id or folder (empty=last build)", default="").strip() or None
                class Args: pass
                args = Args()
                args.target = target
                cmd_run(args)
            elif choice == "4":
                selected = Prompt.ask("Theme", choices=["dark", "light"], default=settings.get("theme", "dark"))
                settings["theme"] = selected
                save_settings(settings)
                console.print(f"[green]Theme set to {selected}.[/green]")
            else:
                console.print("Bye")
                return
            Prompt.ask("Press Enter to continue")
        except Exception as exc:
            console.print(Panel(str(exc), title="Error", border_style="red"))
            Prompt.ask("Press Enter to continue")


def main() -> None:
    clone_cleanup_once()

    if len(os.sys.argv) == 1:
        interactive_menu()
        return

    parser = argparse.ArgumentParser(description="Zero_Sim helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_deps = sub.add_parser("deps", help="Install/check dependencies")
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
        console.print(Panel(str(exc), title="Error", border_style="red"))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
