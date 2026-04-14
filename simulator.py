#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.prompt import Prompt
from rich.table import Table

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_ROOT = os.environ.get("ZERO_SIM_ROOT", "").strip()
if ENV_ROOT and Path(ENV_ROOT).exists():
    ROOT = Path(ENV_ROOT).resolve()
else:
    ROOT = SCRIPT_DIR

SETTINGS_FILE = ROOT / ".zero_sim_settings.json"
CLEAN_MARKER_FILE = ROOT / ".zero_sim_cleaned"
DEFAULT_SETTINGS = {"theme": "dark"}
console = Console()


def npm_command():
    if os.name == "nt":
        npm_cmd = shutil.which("npm.cmd")
        if npm_cmd:
            return [npm_cmd]
    npm = shutil.which("npm")
    if npm:
        return [npm]
    raise RuntimeError(
        "npm is not available in PATH. Install Node.js and reopen your terminal."
    )


def load_settings():
    if not SETTINGS_FILE.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(DEFAULT_SETTINGS)
        merged = dict(DEFAULT_SETTINGS)
        merged.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
        return merged
    except Exception:
        return dict(DEFAULT_SETTINGS)


def save_settings(settings):
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def theme_styles(settings):
    if settings.get("theme", "dark") == "light":
        return {"header": "bold blue", "option": "blue", "action": "black"}
    return {"header": "bold magenta", "option": "cyan", "action": "white"}


def initial_clone_cleanup():
    if CLEAN_MARKER_FILE.exists():
        return
    targets = [ROOT / "assets", ROOT / "LICENSE", ROOT / ".gitignore"]
    removed = []
    for target in targets:
        try:
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
                removed.append(target.name)
            elif target.is_file():
                target.unlink(missing_ok=True)
                removed.append(target.name)
        except Exception:
            pass
    CLEAN_MARKER_FILE.write_text("cleaned\n", encoding="utf-8")
    if removed:
        console.print(f"[yellow]Initial cleanup done:[/yellow] {', '.join(removed)}")


def run_step(title, cmd, cwd=None, quiet=True, input_text=None):
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
            try:
                completed = subprocess.run(
                    cmd,
                    cwd=cwd or ROOT,
                    input=input_text,
                    text=True,
                    capture_output=True,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    f"Command not found: {cmd[0]}. Install it and check your PATH."
                ) from exc
            progress.update(task, completed=1)
        if completed.returncode != 0:
            output = (completed.stdout or "") + "\n" + (completed.stderr or "")
            console.print(
                Panel(
                    output.strip() or "No command output",
                    title=f"Failed: {' '.join(cmd)}",
                    border_style="red",
                )
            )
            raise subprocess.CalledProcessError(completed.returncode, cmd)
        return completed
    console.print(f"[cyan]$ {' '.join(cmd)}[/cyan]")
    subprocess.run(cmd, cwd=cwd or ROOT, check=True)
    return None


def parse_appid(app_folder: str) -> str:
    fam = ROOT / app_folder / "application.fam"
    if not fam.exists():
        raise FileNotFoundError(f"Manifest not found: {fam}")
    text = fam.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r'appid\s*=\s*"([^"]+)"', text)
    if not match:
        raise RuntimeError("Cannot parse appid from application.fam")
    return match.group(1)


def detect_last_built_appid() -> str | None:
    outs = sorted([p for p in ROOT.glob("out_*") if p.is_dir()])
    for directory in reversed(outs):
        candidate = directory / directory.name.replace("out_", "", 1)
        if candidate.exists() and os.access(candidate, os.X_OK):
            return candidate.name
    return None


def missing_apt_packages(packages):
    missing = []
    for pkg in packages:
        result = subprocess.run(["dpkg", "-s", pkg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0:
            missing.append(pkg)
    return missing


def ensure_unix_dependencies_tooling():
    for tool in ("dpkg", "apt-get", "sudo"):
        if shutil.which(tool) is None:
            raise RuntimeError(
                "Linux dependency tools are not available in this shell. "
                "Run this command from WSL/Linux terminal, or skip with build/run only."
            )


def cmd_deps(_args=None):
    console.rule("[bold cyan]Dependencies")
    if not (ROOT / "package.json").exists():
        raise FileNotFoundError(
            f"package.json not found in {ROOT}. Make sure ZERO_SIM_ROOT is correct or run from the cloned repo folder."
        )

    run_step("Updating git submodules", ["git", "submodule", "update", "--init", "--recursive"], quiet=True)
    run_step("Installing npm packages", [*npm_command(), "install"], quiet=True)
    ensure_unix_dependencies_tooling()

    apt_pkgs = [
        "build-essential",
        "gcc",
        "g++",
        "make",
        "pkg-config",
        "jq",
        "git",
        "curl",
        "ca-certificates",
        "nodejs",
        "npm",
        "python3",
        "python3-pip",
        "python3-rich",
        "libsdl2-dev",
        "libsdl2-ttf-dev",
        "libsdl2-image-dev",
        "libsdl2-mixer-dev",
        "libbsd-dev",
        "gdb",
        "x11-apps",
    ]
    missing = missing_apt_packages(apt_pkgs)
    if missing:
        console.print(f"[yellow]Missing apt packages ({len(missing)}):[/yellow] {' '.join(missing)}")
        run_step("Running apt update", ["sudo", "apt-get", "update"], quiet=False)
        run_step("Installing missing apt packages", ["sudo", "apt-get", "install", "-y", *missing], quiet=False)
    else:
        console.print("[green]All required apt packages are already installed.[/green]")

    console.print("[bold green]Dependencies ready.[/bold green]")


def cmd_build(args):
    app_folder = args.app
    app_path = ROOT / app_folder
    if not app_path.exists():
        raise FileNotFoundError(f"App folder not found: {app_path}")
    if not (ROOT / "package.json").exists():
        raise FileNotFoundError(
            f"package.json not found in {ROOT}. Clone the full Zero_Sim repository before building apps."
        )

    console.rule(f"[bold cyan]Build {app_folder}")
    run_step("Compiling app", [*npm_command(), "start"], input_text=f"{app_folder}\n", quiet=True)

    appid = parse_appid(app_folder)
    out_bin = ROOT / f"out_{appid}" / appid
    if not out_bin.exists():
        raise FileNotFoundError(f"Build finished but binary not found: {out_bin}")
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

    out_bin = ROOT / f"out_{target}" / target
    if out_bin.exists():
        return target

    return target


def cmd_run(args):
    appid = resolve_appid(args.target)
    bin_path = ROOT / f"out_{appid}" / appid
    if not bin_path.exists():
        raise FileNotFoundError(f"Binary not found: {bin_path}")
    console.rule("[bold cyan]Run Simulator")
    console.print(f"[green]Launching:[/green] {bin_path}")
    os.execv(str(bin_path), [str(bin_path)])


def interactive_menu():
    settings = load_settings()
    while True:
        console.clear()
        styles = theme_styles(settings)
        table = Table(title="Zero_Sim Runner", header_style=styles["header"])
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
                Prompt.ask("Press Enter to continue")
            elif choice == "2":
                app = Prompt.ask("App folder", default="example_hello_world").strip()
                class Args:
                    pass
                args = Args()
                args.app = app
                cmd_build(args)
                Prompt.ask("Press Enter to continue")
            elif choice == "3":
                target = Prompt.ask("App id or folder (empty=last build)", default="").strip() or None
                class Args:
                    pass
                args = Args()
                args.target = target
                cmd_run(args)
                return
            elif choice == "4":
                selected = Prompt.ask("Theme", choices=["dark", "light"], default=settings.get("theme", "dark"))
                settings["theme"] = selected
                save_settings(settings)
                console.print(f"[green]Theme set to {selected}.[/green]")
                Prompt.ask("Press Enter to continue")
            else:
                console.print("Bye")
                return
        except Exception as exc:
            console.print(Panel(str(exc), title="Error", border_style="red"))
            Prompt.ask("Press Enter to continue")


def main():
    initial_clone_cleanup()

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

