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
import argparse
import webbrowser
import threading
import ctypes
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from pathlib import Path

DEFAULT_PORT = 8080


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
                ("pszDisplayName", ctypes.c_char * 260),
                ("lpszTitle", ctypes.c_wchar_p),
                ("ulFlags", ctypes.c_uint),
                ("lpfn", ctypes.c_void_p),
                ("lParam", ctypes.c_void_p),
                ("iImage", ctypes.c_int),
            ]

        BIF_RETURNONLYFSDIRS = 0x0001
        BIF_NEWDIALOGSTYLE = 0x0040

        bi = BROWSEINFO()
        bi.hwndOwner = user32.GetForegroundWindow()  # Attach to focused window
        bi.lpszTitle = "Select Markdown Directory"
        bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE

        ole32.CoInitialize(None)
        try:
            pidl = shell32.SHBrowseForFolder(ctypes.byref(bi))
            if pidl:
                path_buf = ctypes.create_unicode_buffer(260)
                shell32.SHGetPathFromIDListW(pidl, path_buf)
                shell32.ILFree(pidl)
                return str(Path(path_buf.value))
        finally:
            ole32.CoUninitialize()
    except Exception:
        pass
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
            # Skip hidden directories
            if item.name.startswith('.'):
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
        elif path == '/' or path == '/index.html':
            self.serve_frontend()
        else:
            super().do_GET()

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
        """Custom log format."""
        sys.stderr.write(f"[MD Browser] {args[0]}\n")


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

    args = parser.parse_args()

    # Resolve directory if provided
    if args.directory:
        base_dir = Path(args.directory).expanduser().resolve()
        if not base_dir.exists() or not base_dir.is_dir():
            print(f"Error: '{args.directory}' is not a valid directory")
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
        print("")
        print("  [ERROR] Could not bind to any port.")
        print(f"  Last error: {last_error}")
        print("")
        print("  This is usually WinError 10013 on Windows, caused by:")
        print("    - The port is in a Hyper-V / WSL2 / Docker reserved range")
        print("      Check with:  netsh interface ipv4 show excludedportrange protocol=tcp")
        print("    - The port is already in use by another program")
        print("    - Firewall / antivirus is blocking it")
        print("")
        print("  Fix: run with an explicit free port, e.g.:")
        print("    md-browser.exe --port 8484")
        sys.exit(1)

    if chosen_port != args.port:
        print(f"  [INFO] Port {args.port} unavailable, using {chosen_port} instead.")

    actual_host = 'localhost' if args.host == '0.0.0.0' else args.host
    url = f"http://{actual_host}:{chosen_port}"

    print(f"")
    print(f"  +--------------------------------------+")
    print(f"  |       MD Browser is running          |")
    print(f"  +--------------------------------------+")
    if MDHandler.base_directory:
        print(f"  |  Dir:  {MDHandler.base_directory}")
    else:
        print(f"  |  Dir:  (select from browser UI)")
    print(f"  |  URL:  {url}")
    print(f"  +--------------------------------------+")
    print(f"  |  Press Ctrl+C to stop                |")
    print(f"  +--------------------------------------+")
    print(f"")

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

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == '__main__':
    main()
