"""Tests for the POST /api/save endpoint."""
import json
import sys
import os
import tempfile
import threading
import urllib.request
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server import MDHandler
from http.server import ThreadingHTTPServer


def start_server(base_dir):
    """Start a test server on a random port, return (server, port)."""
    MDHandler.base_directory = str(base_dir)
    server = ThreadingHTTPServer(("127.0.0.1", 0), MDHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def post_json(url, data):
    """Send a POST request with JSON body, return (status_code, response_json)."""
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=5)
        return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_save_normal():
    """Save content to an existing .md file — should succeed."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "note.md").write_text("# Old\n", encoding="utf-8")
        server, port = start_server(tmp)
        try:
            code, data = post_json(
                f"http://127.0.0.1:{port}/api/save",
                {"path": "note.md", "content": "# New Title\n"},
            )
            assert code == 200, f"Expected 200, got {code}: {data}"
            assert data["success"] is True
            assert data["path"] == "note.md"
            assert data["size"] > 0
            # File on disk should be updated
            saved = (Path(tmp) / "note.md").read_text(encoding="utf-8")
            assert saved == "# New Title\n"
        finally:
            server.shutdown()


def test_save_path_traversal():
    """Path traversal attempt should return 403."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "note.md").write_text("ok", encoding="utf-8")
        server, port = start_server(tmp)
        try:
            code, data = post_json(
                f"http://127.0.0.1:{port}/api/save",
                {"path": "../../../etc/evil.md", "content": "hacked"},
            )
            assert code == 403, f"Expected 403, got {code}: {data}"
            assert "error" in data
        finally:
            server.shutdown()


def test_save_non_md():
    """Saving a non-.md file should return 400."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "readme.txt").write_text("old", encoding="utf-8")
        server, port = start_server(tmp)
        try:
            code, data = post_json(
                f"http://127.0.0.1:{port}/api/save",
                {"path": "readme.txt", "content": "new"},
            )
            assert code == 400, f"Expected 400, got {code}: {data}"
            assert "error" in data
        finally:
            server.shutdown()


def test_save_nonexistent_file():
    """Saving to a path that doesn't exist should return 404."""
    with tempfile.TemporaryDirectory() as tmp:
        server, port = start_server(tmp)
        try:
            code, data = post_json(
                f"http://127.0.0.1:{port}/api/save",
                {"path": "ghost.md", "content": "boo"},
            )
            assert code == 404, f"Expected 404, got {code}: {data}"
            assert "error" in data
        finally:
            server.shutdown()


def test_save_newline_preservation():
    """Saved content should preserve \n without Windows \r\n inflation."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "note.md").write_text("old", encoding="utf-8")
        server, port = start_server(tmp)
        try:
            post_json(
                f"http://127.0.0.1:{port}/api/save",
                {"path": "note.md", "content": "line1\nline2\n"},
            )
            raw = (Path(tmp) / "note.md").read_bytes()
            assert b"\r\n" not in raw, f"Found CRLF in saved file: {raw!r}"
            assert raw == b"line1\nline2\n"
        finally:
            server.shutdown()
