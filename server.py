#!/usr/bin/env python3
"""
Markdown File Browser - Lightweight local server
Usage: python server.py [--port PORT] [--host HOST] [directory]
Example: python server.py --port 8080
         python server.py ../001-network-protocols
"""

import os
import re
import sys
import json
import socket
import atexit
import argparse
import webbrowser
import threading
import ctypes
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from pathlib import Path

DEFAULT_PORT = 8080

# When packaged with --windowed, sys.stdout/stderr/stdin are None. Redirect
# log output to a file so startup info and errors are still recoverable, and
# surface fatal errors via a Windows message box (no console to print to).
LOG_FILE = None
if sys.stdout is None:
    try:
        LOG_FILE = open(Path.home() / "md-browser.log", "a", encoding="utf-8")
    except Exception:
        LOG_FILE = None


def log(message=""):
    """Write to stdout if available, otherwise to the log file."""
    line = str(message) + "\n"
    if sys.stdout is not None:
        sys.stdout.write(line)
        sys.stdout.flush()
    elif LOG_FILE is not None:
        try:
            LOG_FILE.write(line)
            LOG_FILE.flush()
        except Exception:
            pass


def alert(message, title="MD Browser"):
    """Show a Windows message box (used when there is no console)."""
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.MessageBoxW(0, str(message), title, 0x10)
        except Exception:
            pass


def pick_folder():
    """Open a native Windows folder picker dialog, return selected path or None."""
    if sys.platform != 'win32':
        return None
    try:
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32

        class BROWSEINFO(ctypes.Structure):
            _fields_ = [
                ("hwndOwner", ctypes.c_void_p),
                ("pidlRoot", ctypes.c_void_p),
                ("pszDisplayName", ctypes.c_wchar_p),
                ("lpszTitle", ctypes.c_wchar_p),
                ("ulFlags", ctypes.c_uint),
                ("lpfn", ctypes.c_void_p),
                ("lParam", ctypes.c_void_p),
                ("iImage", ctypes.c_int),
            ]

        BIF_RETURNONLYFSDIRS = 0x0001
        BIF_NEWDIALOGSTYLE = 0x0040

        # Use explicit W (Unicode) variants and pointer-correct restypes.
        # On 64-bit Python the default c_long restype truncates the 64-bit PIDL
        # returned by SHBrowseForFolderW, causing SHGetPathFromIDListW to receive
        # a corrupted pointer and silently return an empty path. Setting
        # restype=c_void_p (and matching argtypes) makes the PIDL round-trip
        # correctly on both 32- and 64-bit interpreters.
        SHBrowseForFolderW = shell32.SHBrowseForFolderW
        SHBrowseForFolderW.restype = ctypes.c_void_p
        SHBrowseForFolderW.argtypes = [ctypes.POINTER(BROWSEINFO)]

        SHGetPathFromIDListW = shell32.SHGetPathFromIDListW
        SHGetPathFromIDListW.restype = ctypes.c_int
        SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]

        ILFree = shell32.ILFree
        ILFree.restype = None
        ILFree.argtypes = [ctypes.c_void_p]

        bi = BROWSEINFO()
        bi.hwndOwner = user32.GetForegroundWindow()  # Attach to focused window
        bi.lpszTitle = "Select Markdown Directory"
        bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE

        ole32.CoInitialize(None)
        try:
            pidl = SHBrowseForFolderW(ctypes.byref(bi))
            if pidl:
                path_buf = ctypes.create_unicode_buffer(260)
                if SHGetPathFromIDListW(pidl, path_buf):
                    return str(Path(path_buf.value))
                ILFree(pidl)
        finally:
            ole32.CoUninitialize()
    except Exception as e:
        log(f"[MD Browser] pick_folder error: {e}")
    return None


def get_app_dir():
    """Get application directory, compatible with PyInstaller --onefile."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        return Path(sys._MEIPASS)
    return Path(__file__).parent

def get_md_tree(base_dir, current_dir=None):
    """Recursively build a tree structure of MD files."""
    if current_dir is None:
        current_dir = base_dir

    base_path = Path(base_dir).resolve()
    current_path = Path(current_dir).resolve()

    # Security: ensure we stay within base_dir
    if not str(current_path).startswith(str(base_path)):
        return None

    rel = current_path.relative_to(base_path) if current_path != base_path else None
    result = {
        "name": current_path.name or base_path.name,
        "path": rel.as_posix() if rel else "",
        "type": "directory",
        "children": []
    }

    try:
        items = sorted(current_path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return result

    for item in items:
        if item.is_dir():
            # Skip hidden and irrelevant directories
            if item.name.startswith('.') or item.name in ('node_modules', 'venv', 'dist', '__pycache__'):
                continue
            subdir = get_md_tree(base_dir, item)
            if subdir and (subdir["children"] or any(
                f.suffix.lower() == '.md' for f in item.rglob('*.md')
            )):
                result["children"].append(subdir)
        elif item.is_file() and item.suffix.lower() == '.md':
            result["children"].append({
                "name": item.stem,
                "filename": item.name,
                "path": item.relative_to(base_path).as_posix(),
                "type": "file",
                "size": item.stat().st_size
            })

    return result


def search_md_files(base_dir, query, max_results=50):
    """Search all MD files for a query string (case-insensitive fuzzy match)."""
    base_path = Path(base_dir).resolve()
    results = []
    query_lower = query.lower()

    for md_file in sorted(base_path.rglob('*.md'), key=lambda p: p.name.lower()):
        if len(results) >= max_results:
            break

        rel_path = md_file.relative_to(base_path).as_posix()

        # 1. Match against filename
        if query_lower in md_file.stem.lower():
            results.append({
                "path": rel_path,
                "name": md_file.stem,
                "line": 0,
                "text": f"[filename] {md_file.name}",
                "type": "filename"
            })

        # 2. Match against content
        try:
            lines = md_file.read_text(encoding='utf-8').splitlines()
        except Exception:
            continue

        for i, line in enumerate(lines, 1):
            if len(results) >= max_results:
                break
            if query_lower in line.lower():
                # Trim long lines for snippet
                snippet = line.strip()
                if len(snippet) > 120:
                    pos = snippet.lower().find(query_lower)
                    start = max(0, pos - 50)
                    end = min(len(snippet), pos + len(query) + 50)
                    snippet = ('...' if start > 0 else '') + snippet[start:end] + ('...' if end < len(snippet) else '')
                results.append({
                    "path": rel_path,
                    "name": md_file.stem,
                    "line": i,
                    "text": snippet,
                    "type": "content"
                })

    return results


class MDHandler(SimpleHTTPRequestHandler):
    """HTTP request handler with MD file API."""

    base_directory = None

    def handle(self):
        """Override to suppress ConnectionAbortedError on Windows."""
        try:
            super().handle()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass  # Client disconnected — normal for browser refresh/close

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == '/api/tree':
            self.handle_tree(query)
        elif path == '/api/file':
            self.handle_file(query)
        elif path == '/api/switch':
            self.handle_switch(query)
        elif path == '/api/search':
            self.handle_search(query)
        elif path == '/api/pick-folder':
            self.handle_pick_folder()
        elif path == '/api/asset':
            self.handle_asset(query)
        elif path == '/' or path == '/index.html':
            self.serve_frontend()
        else:
            super().do_GET()

    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == '/api/save':
            self.handle_save()
        else:
            self.send_error(405, "Method Not Allowed")

    def handle_save(self):
        """Save content to a markdown file within base_directory."""
        if not self.base_directory:
            self.send_json_error(400, "No directory selected")
            return

        # Read and parse request body
        try:
            content_length = int(self.headers.get('Content-Length', 0))
        except (ValueError, TypeError):
            self.send_json_error(400, "Invalid Content-Length")
            return

        if content_length > 10 * 1024 * 1024:
            self.send_json_error(413, "Request body too large (max 10MB)")
            return

        if content_length == 0:
            self.send_json_error(400, "Empty request body")
            return

        try:
            raw_body = self.rfile.read(content_length)
            body = json.loads(raw_body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self.send_json_error(400, f"Invalid JSON: {e}")
            return

        file_path = body.get('path')
        content = body.get('content')

        if not file_path:
            self.send_json_error(400, "Missing 'path' field")
            return
        if content is None:
            self.send_json_error(400, "Missing 'content' field")
            return

        # Resolve and validate path (same sandbox logic as handle_file)
        base_path = Path(self.base_directory).resolve()
        target_path = (base_path / unquote(file_path)).resolve()

        # Security: ensure path is within base directory
        if not str(target_path).startswith(str(base_path)):
            self.send_json_error(403, "Access denied: path outside allowed directory")
            return

        if not target_path.exists():
            self.send_json_error(404, f"File not found: {file_path}")
            return

        if not target_path.is_file() or target_path.suffix.lower() != '.md':
            self.send_json_error(400, "Not a markdown file")
            return

        # Write content (newline='' prevents Windows \n -> \r\n translation)
        try:
            with open(target_path, 'w', encoding='utf-8', newline='') as f:
                f.write(content)
            self.send_json({
                "success": True,
                "path": file_path,
                "size": target_path.stat().st_size
            })
        except Exception as e:
            self.send_json_error(500, f"Error saving file: {e}")

    def handle_tree(self, query):
        """Return directory tree structure."""
        if not self.base_directory:
            self.send_json({"error": "No directory selected"})
            return
        tree = get_md_tree(self.base_directory)
        self.send_json(tree)

    def handle_switch(self, query):
        """Switch to a different directory."""
        dir_path = query.get('dir', [None])[0]
        if not dir_path:
            self.send_json_error(400, "Missing 'dir' parameter")
            return

        target = Path(unquote(dir_path)).expanduser().resolve()

        if not target.exists():
            self.send_json_error(404, f"Directory not found: {dir_path}")
            return
        if not target.is_dir():
            self.send_json_error(400, f"Not a directory: {dir_path}")
            return

        # Count MD files as a quick sanity check
        md_count = len(list(target.rglob('*.md')))
        if md_count == 0:
            self.send_json_error(400, f"No .md files found in: {dir_path}")
            return

        MDHandler.base_directory = str(target)
        self.send_json({
            "path": str(target),
            "name": target.name,
            "md_count": md_count
        })

    def handle_search(self, query):
        """Search all MD files for a query string."""
        if not self.base_directory:
            self.send_json({"results": [], "query": "", "total": 0})
            return

        q = query.get('q', [None])[0]
        if not q or len(q.strip()) < 2:
            self.send_json({"results": [], "query": q or "", "total": 0})
            return

        results = search_md_files(self.base_directory, q.strip())
        self.send_json({
            "results": results,
            "query": q.strip(),
            "total": len(results)
        })

    def handle_pick_folder(self):
        """Open native folder picker and return selected path."""
        path = pick_folder()
        self.send_json({"path": path})

    def handle_file(self, query):
        """Return MD file content."""
        if not self.base_directory:
            self.send_error(400, "No directory selected")
            return

        file_path = query.get('path', [None])[0]
        if not file_path:
            self.send_error(400, "Missing 'path' parameter")
            return

        # Resolve and validate path
        base_path = Path(self.base_directory).resolve()
        target_path = (base_path / unquote(file_path)).resolve()

        # Security: ensure path is within base directory
        if not str(target_path).startswith(str(base_path)):
            self.send_error(403, "Access denied: path outside allowed directory")
            return

        if not target_path.exists():
            self.send_error(404, f"File not found: {file_path}")
            return

        if not target_path.is_file() or target_path.suffix.lower() != '.md':
            self.send_error(400, "Not a markdown file")
            return

        try:
            content = target_path.read_text(encoding='utf-8')
            self.send_json({
                "content": content,
                "path": file_path,
                "name": target_path.stem,
                "filename": target_path.name,
                "size": target_path.stat().st_size
            })
        except Exception as e:
            self.send_error(500, f"Error reading file: {str(e)}")

    def handle_asset(self, query):
        """Serve an image/static asset from within base_directory.

        Relative image paths in markdown (e.g. ./assets/x.png) are resolved
        against base_directory by the frontend and requested here as
        ?path=cloud-datacenter/assets/x.png. This avoids relying on the
        server's CWD (which SimpleHTTPRequestHandler uses) and keeps all
        file access sandboxed under base_directory.
        """
        if not self.base_directory:
            self.send_error(400, "No directory selected")
            return

        asset_path = query.get('path', [None])[0]
        if not asset_path:
            self.send_error(400, "Missing 'path' parameter")
            return

        base_path = Path(self.base_directory).resolve()
        target_path = (base_path / unquote(asset_path)).resolve()

        # Security: must stay within base_directory
        if not str(target_path).startswith(str(base_path)):
            self.send_error(403, "Access denied: path outside allowed directory")
            return

        if not target_path.exists() or not target_path.is_file():
            self.send_error(404, f"Asset not found: {asset_path}")
            return

        # Allow only common static asset types (block arbitrary file reads)
        allowed_suffixes = {
            '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.bmp', '.ico',
            '.pdf', '.css', '.js', '.json', '.txt',
        }
        if target_path.suffix.lower() not in allowed_suffixes:
            self.send_error(403, "Unsupported asset type")
            return

        content_type = self.guess_content_type(target_path)
        try:
            data = target_path.read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', len(data))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_error(500, f"Error reading asset: {str(e)}")

    @staticmethod
    def guess_content_type(path):
        """Map a file extension to a MIME type (minimal set for assets)."""
        ext = path.suffix.lower()
        return {
            '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.gif': 'image/gif', '.webp': 'image/webp', '.svg': 'image/svg+xml',
            '.bmp': 'image/bmp', '.ico': 'image/x-icon',
            '.pdf': 'application/pdf', '.css': 'text/css',
            '.js': 'application/javascript', '.json': 'application/json',
            '.txt': 'text/plain; charset=utf-8',
        }.get(ext, 'application/octet-stream')

    def serve_frontend(self):
        """Serve the index.html file."""
        frontend_path = get_app_dir() / 'index.html'
        if not frontend_path.exists():
            self.send_error(404, "Frontend not found")
            return

        content = frontend_path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(content))
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, data):
        """Send JSON response."""
        content = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(content))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(content)

    def send_json_error(self, code, message):
        """Send JSON error response."""
        content = json.dumps({"error": message}, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(content))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        """Suppress default HTTP request logging (no console in windowed mode)."""
        pass


def lock_path():
    """Path to the single-instance lock file (in the user's home dir)."""
    return Path.home() / "md-browser.lock"


def check_existing_instance():
    """Return the running instance's port if one is alive, else None.

    The lock file stores 'port' (and pid). We probe the port to confirm the
    instance is actually serving — a stale lock from a crashed process is
    detected and ignored so the new instance can start cleanly.
    """
    p = lock_path()
    try:
        if not p.exists():
            return None
        raw = p.read_text(encoding="utf-8").strip()
        port = int(raw.split(":")[0])
    except (ValueError, OSError):
        return None

    # Probe: is something actually listening there (and answering like us)?
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=0.5)
        s.close()
        return port
    except OSError:
        # Nothing listening — stale lock. Remove it.
        try:
            p.unlink()
        except OSError:
            pass
        return None


def write_lock(port):
    """Write the lock file with the chosen port (and pid for debugging)."""
    try:
        lock_path().write_text(f"{port}:{os.getpid()}", encoding="utf-8")
    except OSError:
        pass


def remove_lock():
    """Remove the lock file on clean shutdown."""
    try:
        lock_path().unlink()
    except OSError:
        pass


def run_tray_icon(server, url, chosen_port):
    """Run a system tray icon with an Exit menu item.

    The HTTP server runs in a daemon thread; this function runs a Windows
    message loop in the main thread. Blocks until the user selects Exit
    from the tray icon's right-click menu, then shuts down the server.
    Falls back to blocking serve_forever() on non-Windows or API failure.
    """
    if sys.platform != 'win32':
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            log("Shutting down...")
        finally:
            server.shutdown()
        return

    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        shell32 = ctypes.windll.shell32

        # --- Constants ---
        WM_APP = 0x8000
        WM_TRAYICON = WM_APP + 1
        WM_COMMAND = 0x0111
        WM_DESTROY = 0x0002
        WM_LBUTTONDBLCLK = 0x0203
        WM_RBUTTONUP = 0x0205

        NIM_ADD = 0
        NIM_DELETE = 2
        NIF_MESSAGE = 0x1
        NIF_ICON = 0x2
        NIF_TIP = 0x4

        IDI_APPLICATION = 32512
        MF_STRING = 0x0
        TPM_RIGHTALIGN = 0x8
        TPM_BOTTOMALIGN = 0x20

        ID_EXIT = 1001
        TRAY_UID = 1

        # --- Structures ---
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_size_t, ctypes.c_long
        )

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("style", ctypes.c_uint),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", ctypes.c_void_p),
                ("hIcon", ctypes.c_void_p),
                ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p),
                ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p),
                ("hIconSm", ctypes.c_void_p),
            ]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_uint),
                ("hWnd", ctypes.c_void_p),
                ("uID", ctypes.c_uint),
                ("uFlags", ctypes.c_uint),
                ("uCallbackMessage", ctypes.c_uint),
                ("hIcon", ctypes.c_void_p),
                ("szTip", ctypes.c_wchar * 128),
                ("dwState", ctypes.c_uint),
                ("dwStateMask", ctypes.c_uint),
                ("szInfo", ctypes.c_wchar * 256),
                ("uTimeout", ctypes.c_uint),
                ("szInfoTitle", ctypes.c_wchar * 64),
                ("dwInfoFlags", ctypes.c_uint),
            ]

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hWnd", ctypes.c_void_p),
                ("message", ctypes.c_uint),
                ("wParam", ctypes.c_size_t),
                ("lParam", ctypes.c_long),
                ("time", ctypes.c_uint),
                ("pt", POINT),
            ]

        # --- Argtypes for critical functions ---
        user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
        user32.RegisterClassExW.restype = ctypes.c_ushort

        user32.CreateWindowExW.argtypes = [
            ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ]
        user32.CreateWindowExW.restype = ctypes.c_void_p

        user32.DefWindowProcW.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_long,
        ]
        user32.DefWindowProcW.restype = ctypes.c_long

        shell32.Shell_NotifyIconW.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        shell32.Shell_NotifyIconW.restype = ctypes.c_int

        user32.LoadIconW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        user32.LoadIconW.restype = ctypes.c_void_p

        user32.GetMessageW.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
        ]
        user32.GetMessageW.restype = ctypes.c_int

        user32.TranslateMessage.argtypes = [ctypes.c_void_p]
        user32.TranslateMessage.restype = ctypes.c_int

        user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
        user32.DispatchMessageW.restype = ctypes.c_long

        user32.CreatePopupMenu.restype = ctypes.c_void_p
        user32.AppendMenuW.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_wchar_p,
        ]
        user32.AppendMenuW.restype = ctypes.c_int

        user32.TrackPopupMenu.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
        ]
        user32.TrackPopupMenu.restype = ctypes.c_int

        user32.DestroyMenu.argtypes = [ctypes.c_void_p]
        user32.DestroyMenu.restype = ctypes.c_int

        user32.GetCursorPos.argtypes = [ctypes.c_void_p]
        user32.GetCursorPos.restype = ctypes.c_int

        user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        user32.SetForegroundWindow.restype = ctypes.c_int

        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.PostQuitMessage.restype = None

        kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p

        # --- Window proc ---
        def window_proc(hwnd, msg_id, wparam, lparam):
            if msg_id == WM_TRAYICON:
                if lparam == WM_LBUTTONDBLCLK:
                    webbrowser.open(url)
                elif lparam == WM_RBUTTONUP:
                    menu = user32.CreatePopupMenu()
                    if menu:
                        user32.AppendMenuW(menu, MF_STRING, ID_EXIT, "Exit")
                        pt = POINT()
                        user32.GetCursorPos(ctypes.byref(pt))
                        # SetForegroundWindow is required for the menu to
                        # dismiss when clicking outside (Windows quirk).
                        user32.SetForegroundWindow(hwnd)
                        user32.TrackPopupMenu(
                            menu, TPM_RIGHTALIGN | TPM_BOTTOMALIGN,
                            pt.x, pt.y, 0, hwnd, None,
                        )
                        user32.DestroyMenu(menu)
                return 0

            if msg_id == WM_COMMAND:
                menu_id = wparam & 0xFFFF
                if menu_id == ID_EXIT:
                    log("Shutting down (tray exit)...")
                    # Remove tray icon immediately for visual feedback
                    nid = NOTIFYICONDATAW()
                    nid.cbSize = ctypes.sizeof(nid)
                    nid.hWnd = hwnd
                    nid.uID = TRAY_UID
                    shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                    user32.PostQuitMessage(0)
                return 0

            if msg_id == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0

            return user32.DefWindowProcW(hwnd, msg_id, wparam, lparam)

        # --- Register window class ---
        wndproc = WNDPROC(window_proc)  # keep reference to prevent GC
        hinst = kernel32.GetModuleHandleW(None)

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(wc)
        wc.lpfnWndProc = wndproc
        wc.hInstance = hinst
        wc.lpszClassName = "MDBrowserTrayIcon"

        if user32.RegisterClassExW(ctypes.byref(wc)) == 0:
            raise RuntimeError("RegisterClassExW failed")

        # --- Create hidden window ---
        hwnd = user32.CreateWindowExW(
            0, "MDBrowserTrayIcon", "MD Browser Tray",
            0, 0, 0, 0, 0, None, None, hinst, None,
        )
        if not hwnd:
            raise RuntimeError("CreateWindowExW failed")

        # --- Add tray icon ---
        hicon = user32.LoadIconW(None, IDI_APPLICATION)
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = hwnd
        nid.uID = TRAY_UID
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = hicon
        nid.szTip = f"MD Browser — localhost:{chosen_port}"[:127]

        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            raise RuntimeError("Shell_NotifyIconW (NIM_ADD) failed")

        log("  |  Tray icon active — right-click → Exit to stop")
        log("  +--------------------------------------+")

        # --- Message loop ---
        msg = MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        # --- Cleanup after message loop ends (tray Exit or WM_DESTROY) ---
        nid_del = NOTIFYICONDATAW()
        nid_del.cbSize = ctypes.sizeof(nid_del)
        nid_del.hWnd = hwnd
        nid_del.uID = TRAY_UID
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid_del))

    except Exception as e:
        log(f"[WARN] Tray icon failed: {e}")
        log("[INFO] Falling back to blocking server (Ctrl+C or kill to stop).")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            log("Shutting down...")
        finally:
            server.shutdown()
        return

    # Tray icon exited normally — shut down the HTTP server
    server.shutdown()


def main():
    parser = argparse.ArgumentParser(description='Markdown File Browser')
    parser.add_argument('directory', nargs='?', default=None,
                        help='Initial directory to browse (can be changed from UI)')
    parser.add_argument('--port', '-p', type=int, default=DEFAULT_PORT,
                        help=f'Port to listen on (default: {DEFAULT_PORT})')
    parser.add_argument('--host', '-H', default='localhost',
                        help='Host to bind to (default: localhost)')
    parser.add_argument('--no-browser', action='store_true',
                        help='Do not auto-open browser on startup')
    parser.add_argument('--multi', action='store_true',
                        help='Allow multiple instances (skip single-instance check)')

    args = parser.parse_args()

    # Single-instance check: if another instance is already running, tell the
    # user which port it's on (and optionally just focus it) instead of opening
    # a second one. A `--multi` escape hatch exists for forced parallel runs.
    if not args.multi:
        existing_port = check_existing_instance()
        if existing_port is not None:
            url = f"http://localhost:{existing_port}"
            msg = (f"MD Browser 已在运行中（端口 {existing_port}）。\n\n"
                   f"地址：{url}\n\n"
                   f"点击“确定”打开已运行的窗口。")
            log(f"[INFO] Another instance is running on port {existing_port}; not starting a second one.")
            # MB_OK (0x0) gives a single OK button that also opens the browser
            try:
                if sys.platform == "win32":
                    ctypes.windll.user32.MessageBoxW(0, msg, "MD Browser 已运行", 0x40)
                webbrowser.open(url)
            except Exception:
                pass
            sys.exit(0)

    # Resolve directory if provided
    if args.directory:
        base_dir = Path(args.directory).expanduser().resolve()
        if not base_dir.exists() or not base_dir.is_dir():
            msg = f"Error: '{args.directory}' is not a valid directory"
            log(msg)
            alert(msg + "\n\n请确认路径正确。")
            sys.exit(1)
        MDHandler.base_directory = str(base_dir)
    else:
        MDHandler.base_directory = None

    # Start server — try the requested port, fall back to alternatives on failure.
    # Windows WinError 10013 (WSAEACCES) usually means the port is in a Hyper-V /
    # WSL2 reserved range, occupied, or blocked by firewall. Auto-fallback keeps
    # the exe usable without the user having to debug port issues.
    candidate_ports = []
    if args.port:
        candidate_ports.append(args.port)
    if args.port != DEFAULT_PORT:
        candidate_ports.append(DEFAULT_PORT)
    # Common fallbacks unlikely to be in Windows excluded-port ranges
    candidate_ports.extend([8181, 8484, 9000, 3000])

    chosen_port = None
    server = None
    last_error = None
    for port in candidate_ports:
        try:
            server = ThreadingHTTPServer((args.host, port), MDHandler)
            chosen_port = port
            break
        except (OSError, OverflowError, ValueError) as e:
            # OSError → WinError 10013 (reserved/blocked/in-use) or in-use
            # OverflowError/ValueError → port out of valid range (0-65535)
            last_error = e
            continue

    if server is None:
        msg_lines = [
            "[ERROR] Could not bind to any port.",
            f"Last error: {last_error}",
            "",
            "This is usually WinError 10013 on Windows, caused by:",
            "  - The port is in a Hyper-V / WSL2 / Docker reserved range",
            "    Check: netsh interface ipv4 show excludedportrange protocol=tcp",
            "  - The port is already in use by another program",
            "  - Firewall / antivirus is blocking it",
            "",
            "Fix: run with an explicit free port, e.g.:",
            "  md-browser.exe --port 8484",
        ]
        msg = "\n".join(msg_lines)
        log("")
        log(msg)
        alert(msg, "MD Browser — 启动失败")
        sys.exit(1)

    if chosen_port != args.port:
        log(f"  [INFO] Port {args.port} unavailable, using {chosen_port} instead.")

    # Register this instance: write the lock so subsequent launches detect us.
    write_lock(chosen_port)
    atexit.register(remove_lock)

    actual_host = 'localhost' if args.host == '0.0.0.0' else args.host
    url = f"http://{actual_host}:{chosen_port}"

    log("")
    log("  +--------------------------------------+")
    log("  |       MD Browser is running          |")
    log("  +--------------------------------------+")
    if MDHandler.base_directory:
        log(f"  |  Dir:  {MDHandler.base_directory}")
    else:
        log("  |  Dir:  (select from browser UI)")
    log(f"  |  URL:  {url}")
    log("  +--------------------------------------+")

    # Auto-open browser after server is confirmed ready
    if not args.no_browser:
        def open_browser_when_ready():
            bind_host = '127.0.0.1' if args.host == '0.0.0.0' else args.host
            for _ in range(50):  # up to 5 seconds
                try:
                    s = socket.create_connection((bind_host, chosen_port), timeout=0.1)
                    s.close()
                    webbrowser.open(url)
                    return
                except OSError:
                    pass
        threading.Thread(target=open_browser_when_ready, daemon=True).start()

    # Run HTTP server in a daemon thread; main thread runs the tray icon
    # message loop (or falls back to serve_forever on non-Windows / failure).
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    run_tray_icon(server, url, chosen_port)

    # Cleanup on exit (tray Exit, Ctrl+C fallback, or API failure)
    remove_lock()


if __name__ == '__main__':
    main()
