#!/usr/bin/env python3
"""
Markdown File Browser - Lightweight local server
Usage: python server.py [--port PORT] [--host HOST] [directory]
Example: python server.py --port 8080
         python server.py ../001-network-protocols
"""

import os
import sys
import json
import argparse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from pathlib import Path

DEFAULT_PORT = 8080

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


class MDHandler(SimpleHTTPRequestHandler):
    """HTTP request handler with MD file API."""

    base_directory = None

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
        frontend_path = Path(__file__).parent / 'index.html'
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

    args = parser.parse_args()

    # Resolve directory if provided
    if args.directory:
        base_dir = Path(args.directory).expanduser().resolve()
        if not base_dir.exists() or not base_dir.is_dir():
            print(f"Error: '{args.directory}' is not a valid directory")
            sys.exit(1)
        MDHandler.base_directory = str(base_dir)
        print(f"  Directory: {base_dir}")
    else:
        MDHandler.base_directory = None
        print(f"  Directory: (select from browser UI)")

    # Start server
    server = HTTPServer((args.host, args.port), MDHandler)
    print(f"Markdown Browser started!")
    print(f"  URL: http://{args.host}:{args.port}")
    print(f"  Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == '__main__':
    main()
