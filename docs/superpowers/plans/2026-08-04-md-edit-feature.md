# Markdown 文件编辑功能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 MD Browser 的 topbar 右上角添加编辑/保存按钮，允许用户直接在 web 界面修改 Markdown 源码并保存到磁盘。

**Architecture:** 后端 `server.py` 新增 `POST /api/save` 端点（复用现有路径沙箱校验）。前端 `index.html` 新增 textarea 编辑视图，通过 `isEditing` 状态机在阅读态/编辑态间切换，保存后调用 `loadFile` 重新渲染。未保存修改通过 `confirm()` 和 `beforeunload` 拦截。

**Tech Stack:** Python 3.7+ 标准库（`http.server`, `json`, `pathlib`），原生 HTML/CSS/JS（无前端框架）

## Global Constraints

- 后端零第三方依赖，仅用 Python 标准库
- 前端为单 HTML 文件（`index.html`），所有 CSS/JS 内联
- 路径安全：所有文件写入必须在 `base_directory` 沙箱内，防穿越攻击
- 文件编码：UTF-8，写入时 `newline=''` 保持 `\n` 不被 Windows 翻译为 `\r\n`
- POST body 上限 10MB
- 仅允许 `.md` 文件写入
- 不改动现有端点（`/api/tree`, `/api/file`, `/api/switch`, `/api/search`, `/api/pick-folder`, `/api/asset`）
- 不改动 `build.py` / `build.bat`

**Spec reference:** `docs/superpowers/specs/2026-08-04-md-edit-feature-design.md`

---

### Task 1: Backend — `/api/save` POST endpoint

**Files:**
- Modify: `server.py`（`MDHandler` 类，约 line 225-460）
- Test: `tests/test_save_api.py`（新建）

**Interfaces:**
- Produces: `POST /api/save` 端点，接收 JSON `{ "path": "<相对路径>", "content": "<新内容>" }`，返回 `{ "success": true, "path": "...", "size": <bytes> }`；失败返回 `{"error": "..."}` + HTTP 错误码

- [ ] **Step 1: Write the failing test**

Create `tests/test_save_api.py`:

```python
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
    """Saved content should preserve \\n without Windows \\r\\n inflation."""
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_save_api.py -v` (or `python -m unittest tests.test_save_api` if pytest unavailable)

Expected: FAIL — `urllib.error.HTTPError: HTTP Error 501: Unsupported method` because `do_POST` doesn't exist yet. If pytest is not installed, run:

```bash
python -m unittest tests.test_save_api -v
```

(Note: the test file uses plain `assert` + function names, compatible with both pytest and unittest. If using unittest, the functions must be prefixed with `test_` — they already are.)

- [ ] **Step 3: Implement `do_POST` and `handle_save` in `server.py`**

In the `MDHandler` class (after `do_GET`, around line 257), add:

```python
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
            target_path.write_text(content, encoding='utf-8', newline='')
            self.send_json({
                "success": True,
                "path": file_path,
                "size": target_path.stat().st_size
            })
        except Exception as e:
            self.send_json_error(500, f"Error saving file: {e}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_save_api.py -v`

Expected: all 5 tests PASS. If pytest is not installed, run:

```bash
python -m unittest tests.test_save_api -v
```

(If `tests/__init__.py` is needed, create an empty one.)

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_save_api.py
git commit -m "feat: add POST /api/save endpoint for markdown file editing"
```

---

### Task 2: Frontend — Edit button + textarea UI scaffolding

**Files:**
- Modify: `index.html`（CSS `<style>` 区 + topbar HTML + content-wrapper HTML）

**Interfaces:**
- Produces: `#edit-btn` 按钮（topbar）、`#editor` textarea（content-wrapper 内）、`#cancel-edit-btn` 按钮、`#save-status` span；CSS 类 `#editor` 样式

- [ ] **Step 1: Add CSS for `#editor`**

In `index.html`, after the `#content` CSS block (around line 732, after the closing `}` of `#content`), insert:

```css
    /* ===== Editor (edit mode) ===== */
    #editor {
      max-width: 860px;
      margin: 0 auto;
      width: 100%;
      min-height: calc(100vh - 44px);
      padding: 20px;
      border: 1px solid var(--border-color);
      border-radius: 8px;
      font-family: "Cascadia Code", "Fira Code", "Consolas", "SF Mono", monospace;
      font-size: 14px;
      line-height: 1.6;
      color: var(--content-text);
      background: #fff;
      resize: vertical;
      outline: none;
      box-sizing: border-box;
      tab-size: 2;
    }

    #editor:focus {
      border-color: #4a90d9;
      box-shadow: 0 0 0 2px rgba(74, 144, 217, 0.15);
    }

    #save-status {
      color: #2d8a4e;
      font-size: 12px;
      font-weight: 500;
      opacity: 0;
      transition: opacity 0.3s;
      margin-right: 8px;
    }

    #save-status.visible {
      opacity: 1;
    }
```

- [ ] **Step 2: Add edit button to topbar**

In the topbar HTML (around line 1226, after the `</div>` closing `#search-wrapper`), insert:

```html
      <button class="nav-btn" id="edit-btn" onclick="toggleEdit()" disabled title="Edit (Ctrl+E)" style="margin-left: 8px;">✏️</button>
      <button class="nav-btn" id="cancel-edit-btn" onclick="cancelEdit()" title="Cancel edit" style="display: none;">✕</button>
      <span id="save-status"></span>
```

The topbar should now look like:

```html
    <div id="topbar">
      <button class="nav-btn" id="sidebar-toggle" onclick="toggleSidebar()" title="Toggle sidebar">☰</button>
      <div id="breadcrumb">
        <span>Select a file from the sidebar</span>
      </div>
      <div id="nav-buttons">
        <button class="nav-btn" id="btn-back" onclick="navigateBack()" disabled title="Back (Ctrl+Left)">&#9664;</button>
        <button class="nav-btn" id="btn-forward" onclick="navigateForward()" disabled title="Forward (Ctrl+Right)">&#9654;</button>
      </div>
      <div id="search-wrapper">
        <div id="search-input-wrap">
          <span id="search-icon">&#x1F50D;</span>
          <input type="text" id="search-input" placeholder="Search... (Ctrl+K)" spellcheck="false">
          <div id="search-results"></div>
        </div>
        <button id="search-btn" onclick="triggerSearch()">Search</button>
      </div>
      <button class="nav-btn" id="edit-btn" onclick="toggleEdit()" disabled title="Edit (Ctrl+E)" style="margin-left: 8px;">✏️</button>
      <button class="nav-btn" id="cancel-edit-btn" onclick="cancelEdit()" title="Cancel edit" style="display: none;">✕</button>
      <span id="save-status"></span>
    </div>
```

- [ ] **Step 3: Add textarea element to content-wrapper**

In the content-wrapper HTML (around line 1242, after `<div id="content" style="display:none;"></div>`), insert:

```html
      <textarea id="editor" style="display:none;" spellcheck="false"></textarea>
```

The content-wrapper should now look like:

```html
    <div id="content-wrapper">
      <div id="welcome">
        <div class="icon">📚</div>
        <h2>Markdown Browser</h2>
        <p>在左侧输入目录路径来加载 Markdown 文件</p>
        <p style="margin-top: 8px; font-size: 12px; color: #bbb;">例如: <code>D:\claude\001-network-protocols</code></p>
      </div>
      <div id="content" style="display:none;"></div>
      <textarea id="editor" style="display:none;" spellcheck="false"></textarea>
    </div>
```

- [ ] **Step 4: Verify in browser**

Run: `python server.py` and open the browser.

Verify:
- topbar 右侧搜索框后出现 `✏️` 按钮（灰色 disabled 状态）
- `✕` 按钮不可见
- 打开一个 MD 文件后 `✏️` 按钮变为可点击
- 检查页面无 JS 报错（`toggleEdit` 函数尚未定义，点击会报错——这是预期的，Task 3 会实现）

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat: add edit button and textarea UI elements to topbar"
```

---

### Task 3: Frontend — Edit/save state machine

**Files:**
- Modify: `index.html`（`<script>` 区）

**Interfaces:**
- Consumes: `POST /api/save`（Task 1）、`#edit-btn` / `#cancel-edit-btn` / `#editor` / `#save-status`（Task 2）、`currentFile`（existing global）、`loadFile()`（existing function）
- Produces: `isEditing` global、`currentFileContent` global、`toggleEdit()`、`saveEdit()`、`cancelEdit()`、`exitEditMode()` 函数

- [ ] **Step 1: Add global state variables**

In `index.html` `<script>` section, after `let currentFile = null;` (line 1248), add:

```javascript
    let currentFileContent = null;
    let isEditing = false;
```

- [ ] **Step 2: Set `currentFileContent` in `loadFile`**

In the `loadFile` function (around line 2312, after `currentFile = path;`), add:

```javascript
        currentFileContent = data.content;
```

The code around that point should read:

```javascript
        const data = await fetchFile(path);
        currentFile = path;
        currentFileContent = data.content;
```

Also, in `loadTree()` around line 2748 where `currentFile = null;` is set on directory switch, add right after it:

```javascript
        currentFile = null;
        currentFileContent = null;
        document.getElementById('edit-btn').disabled = true;
```

- [ ] **Step 3: Implement `toggleEdit()`, `saveEdit()`, `cancelEdit()`, `exitEditMode()`**

Add these functions in the `<script>` section. Place them after the `loadFile` function (after line 2387, before the `// ===== Link Navigation =====` comment at line 2389):

```javascript
    // ===== Edit Mode =====
    function toggleEdit() {
      if (!currentFile) return;
      if (!isEditing) {
        enterEditMode();
      } else {
        saveEdit();
      }
    }

    function enterEditMode() {
      const content = document.getElementById('content');
      const welcome = document.getElementById('welcome');
      const editor = document.getElementById('editor');
      const editBtn = document.getElementById('edit-btn');
      const cancelBtn = document.getElementById('cancel-edit-btn');

      editor.value = currentFileContent || '';
      editor.style.display = 'block';
      content.style.display = 'none';
      welcome.style.display = 'none';

      editBtn.textContent = '💾';
      editBtn.title = 'Save (Ctrl+S)';
      cancelBtn.style.display = 'flex';

      isEditing = true;
      editor.focus();
    }

    function exitEditMode() {
      const content = document.getElementById('content');
      const welcome = document.getElementById('welcome');
      const editor = document.getElementById('editor');
      const editBtn = document.getElementById('edit-btn');
      const cancelBtn = document.getElementById('cancel-edit-btn');

      editor.style.display = 'none';
      editor.value = '';
      // Restore content or welcome view
      if (currentFile) {
        content.style.display = 'block';
      } else {
        welcome.style.display = 'flex';
      }

      editBtn.textContent = '✏️';
      editBtn.title = 'Edit (Ctrl+E)';
      cancelBtn.style.display = 'none';

      isEditing = false;
    }

    async function saveEdit() {
      if (!currentFile) return;

      const editor = document.getElementById('editor');
      const editBtn = document.getElementById('edit-btn');
      const newContent = editor.value;

      editBtn.disabled = true;
      editBtn.textContent = '⏳';

      try {
        const res = await fetch('/api/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: currentFile, content: newContent })
        });
        const data = await res.json();

        if (!res.ok) {
          throw new Error(data.error || res.statusText);
        }

        currentFileContent = newContent;
        exitEditMode();

        // Show "Saved" flash
        showSaveStatus();

        // Reload file to re-render (reuses full render pipeline)
        await loadFile(currentFile);
      } catch (err) {
        alert('保存失败: ' + err.message);
      } finally {
        editBtn.disabled = false;
        // If still editing (save failed), restore 💾 icon; otherwise ✏️
        if (isEditing) {
          editBtn.textContent = '💾';
        } else {
          editBtn.textContent = '✏️';
        }
      }
    }

    function cancelEdit() {
      if (!isEditing) return;
      const editor = document.getElementById('editor');
      if (editor.value !== currentFileContent) {
        if (!confirm('放弃未保存的修改？')) return;
      }
      exitEditMode();
    }

    function showSaveStatus() {
      const status = document.getElementById('save-status');
      status.textContent = '✓ Saved';
      status.classList.add('visible');
      setTimeout(() => {
        status.classList.remove('visible');
      }, 2000);
    }
```

- [ ] **Step 4: Enable edit button when file loads**

In `loadFile` function, after `currentFileContent = data.content;` (added in Step 2), add:

```javascript
        document.getElementById('edit-btn').disabled = false;
```

- [ ] **Step 5: Verify in browser**

Run: `python server.py`, open a MD file.

Verify:
1. `✏️` 按钮可点击 → 点击后变为 textarea 编辑模式，显示原始 Markdown 源码
2. `✕` 按钮出现 → 点击取消回到阅读态
3. 修改内容后点 `💾` → 文件保存成功，闪现 `✓ Saved`，页面重新渲染
4. 保存失败时（可手动改后端端口模拟）→ alert 提示，留在编辑态
5. 未修改内容点取消 → 不弹确认直接退出
6. 修改后点取消 → 弹确认框

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat: implement edit/save/cancel state machine for inline editing"
```

---

### Task 4: Frontend — Unsaved change protection

**Files:**
- Modify: `index.html`（`<script>` 区）

**Interfaces:**
- Consumes: `isEditing`, `currentFileContent`（Task 3）、`exitEditMode()`（Task 3）、`loadFile()`（existing）、`switchToDir()`（existing）

- [ ] **Step 1: Add `confirmDiscardIfEditing()` guard function**

After the `cancelEdit()` function (added in Task 3), add:

```javascript
    function confirmDiscardIfEditing() {
      if (!isEditing) return true;
      const editor = document.getElementById('editor');
      if (editor.value !== currentFileContent) {
        return confirm('有未保存的修改，是否放弃？');
      }
      // No unsaved changes — silently exit edit mode
      exitEditMode();
      return true;
    }
```

- [ ] **Step 2: Guard `loadFile` entry**

At the very top of the `loadFile` function (line 2282, before any existing code), add:

```javascript
    async function loadFile(path, fragment, searchTerm) {
      if (!confirmDiscardIfEditing()) return;
      // ... existing code ...
```

The function signature stays the same; just insert the guard line as the first statement.

- [ ] **Step 3: Guard `switchToDir` entry**

At the very top of the `switchToDir` function (line 1949, before `if (!dirPath) return;`), add:

```javascript
    async function switchToDir(dirPath) {
      if (!confirmDiscardIfEditing()) return;
      if (!dirPath) return;
      // ... existing code ...
```

- [ ] **Step 4: Add `beforeunload` handler**

After the `showSaveStatus()` function (or anywhere in the edit mode section), add:

```javascript
    window.addEventListener('beforeunload', (e) => {
      if (isEditing) {
        const editor = document.getElementById('editor');
        if (editor.value !== currentFileContent) {
          e.preventDefault();
          e.returnValue = '';
        }
      }
    });
```

- [ ] **Step 5: Verify in browser**

Run: `python server.py`, open a MD file.

Verify:
1. 进入编辑模式，修改内容 → 点击侧边栏另一个文件 → 弹"有未保存的修改"确认框
2. 点"取消" → 留在当前文件编辑态
3. 点"确定" → 切换到新文件
4. 编辑模式但未修改内容 → 切换文件 → 不弹框直接切换
5. 编辑修改后 → 刷新页面（F5）→ 浏览器弹"未保存修改"原生提示
6. 编辑修改后 → 切换目录（输入新路径点 Go）→ 弹确认框

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "feat: add unsaved change protection for file switch and page unload"
```

---

### Task 5: Frontend — Keyboard shortcuts (Ctrl+E, Ctrl+S)

**Files:**
- Modify: `index.html`（`<script>` 区 keydown listener）

**Interfaces:**
- Consumes: `toggleEdit()`（Task 3）、`saveEdit()`（Task 3）、`isEditing`（Task 3）

- [ ] **Step 1: Add Ctrl+E and Ctrl+S to keydown handler**

Find the existing keydown handler for Ctrl+Left/Ctrl+Right (around line 2492):

```javascript
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === 'ArrowLeft') {
        e.preventDefault();
        navigateBack();
      }
      if (e.ctrlKey && e.key === 'ArrowRight') {
        e.preventDefault();
        navigateForward();
      }
    });
```

Replace it with:

```javascript
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === 'ArrowLeft') {
        e.preventDefault();
        navigateBack();
      }
      if (e.ctrlKey && e.key === 'ArrowRight') {
        e.preventDefault();
        navigateForward();
      }
      // Ctrl+E: toggle edit mode
      if (e.ctrlKey && (e.key === 'e' || e.key === 'E')) {
        e.preventDefault();
        toggleEdit();
      }
      // Ctrl+S: save (only in edit mode)
      if (e.ctrlKey && (e.key === 's' || e.key === 'S') && isEditing) {
        e.preventDefault();
        saveEdit();
      }
    });
```

- [ ] **Step 2: Verify in browser**

Run: `python server.py`, open a MD file.

Verify:
1. `Ctrl+E` → 进入编辑模式
2. `Ctrl+E` 再次 → 不触发保存（`toggleEdit` 在编辑态调 `saveEdit`，所以实际是保存）—— 确认 Ctrl+E 在编辑态也触发保存
3. 编辑模式按 `Ctrl+S` → 保存文件
4. 阅读模式按 `Ctrl+S` → 不拦截浏览器原生"另存网页"
5. 编辑模式按 `Ctrl+E` → 等同于点 💾 保存

- [ ] **Step 3: Commit**

```bash
git add index.html
git commit -m "feat: add Ctrl+E and Ctrl+S keyboard shortcuts for edit/save"
```

---

### Task 6: README update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add edit feature to README**

In `README.md`, in the "文档阅读" section table (around line 47-53), add a new row after the last existing row:

```markdown
| **轻量级编辑** | 右上角 ✏️ 按钮进入编辑模式，直接修改 Markdown 源码并保存；`Ctrl+E` 切换编辑、`Ctrl+S` 保存；切换文件时自动拦截未保存修改 |
```

In the "导航控制" table (around line 68-73), add:

```markdown
| **编辑/保存** | `Ctrl + E` | 进入/保存编辑模式 |
| **保存** | `Ctrl + S` | 编辑模式下保存文件 |
```

In the "API 接口" table (around line 176-183), add:

```markdown
| `/api/save` | POST | 保存 Markdown 文件内容（JSON body: `{path, content}`） |
```

In the "更新日志" section (before `### v1.15`), add a new entry at the top:

```markdown
### v1.16 — 轻量级编辑功能
- **在线编辑**: 右上角 ✏️ 按钮一键进入编辑模式，textarea 显示原始 Markdown 源码，保存后自动重新渲染
- **快捷键**: `Ctrl+E` 切换编辑/保存，`Ctrl+S` 保存（编辑模式下）
- **未保存保护**: 编辑中切换文件或关闭页面时弹确认框，避免误丢修改
- **安全沙箱**: 保存端点复用 `base_directory` 路径校验，防穿越攻击，仅允许 `.md` 文件
- **新增 `POST /api/save` 端点**: 接收 JSON `{path, content}`，写入文件并返回 `{success, size}`
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add edit feature to README"
```

---

## Post-Implementation Verification

After all tasks are complete, run a full manual test:

1. `python server.py` → 打开浏览器
2. 选择一个有 MD 文件的目录
3. 打开一个文件 → `✏️` 按钮可用
4. `Ctrl+E` → 进入编辑模式
5. 修改文字 → `Ctrl+S` → 闪现 `✓ Saved` → 页面重新渲染显示修改后内容
6. 再次 `Ctrl+E` → 修改 → 点 `✕` → 弹确认 → 确认 → 回到原内容
7. `Ctrl+E` → 修改 → 点击侧边栏另一个文件 → 弹确认
8. 用文本编辑器打开磁盘上的文件 → 确认内容已更新且换行为 `\n`（非 `\r\n`）
9. 运行后端测试: `python -m pytest tests/test_save_api.py -v`（全部通过）
