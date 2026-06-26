#!/usr/bin/env python3
"""
Build script for MD Browser — packages server.py + index.html into a single
windowless Windows exe via the PyInstaller Python API (no pyinstaller CLI).

Usage:
    python build.py            # build windowless exe (no console popup)
    python build.py --console  # build with a console window (for debugging)

Output: dist/md-browser.exe
"""

import sys
import shutil
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()


def build(console=False):
    """Build the exe using PyInstaller's Python API."""
    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        print("[ERROR] PyInstaller is not installed.")
        print("        Install it with:  pip install pyinstaller")
        sys.exit(1)

    # Clean previous build artifacts
    for artifact in ["build", "dist", "md-browser.spec"]:
        p = PROJECT_DIR / artifact
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file():
            p.unlink(missing_ok=True)

    index_html = PROJECT_DIR / "index.html"
    if not index_html.exists():
        print(f"[ERROR] index.html not found at {index_html}")
        sys.exit(1)

    # Build the PyInstaller argument list.
    # --add-data "src;dest"  (separator is ';' on Windows, ':' on others)
    sep = ";" if sys.platform == "win32" else ":"
    args = [
        "--onefile",                         # single exe
        "--name", "md-browser",
        "--add-data", f"{index_html}{sep}.",
        "--clean",                           # clean PyInstaller cache
        "--noconfirm",                       # overwrite without asking
    ]

    if console:
        args.append("--console")             # show a terminal window (debug)
    else:
        args.append("--windowed")            # no console window (default)

    args.append(str(PROJECT_DIR / "server.py"))

    print("=" * 50)
    print("  Building MD Browser")
    print(f"  Mode: {'console' if console else 'windowless'}")
    print("=" * 50)
    print()

    pyi.run(args)

    exe = PROJECT_DIR / "dist" / ("md-browser.exe" if sys.platform == "win32" else "md-browser")
    print()
    if exe.exists():
        print("=" * 50)
        print("  Build successful!")
        print(f"  Output: {exe}")
        print()
        print("  Usage:")
        print("    Double-click md-browser.exe to start")
        print("    md-browser.exe [directory] [--port PORT]")
        print("=" * 50)
    else:
        print("[ERROR] Build failed — exe not found.")
        sys.exit(1)


if __name__ == "__main__":
    console = "--console" in sys.argv
    build(console=console)
