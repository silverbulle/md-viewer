# 设计文档：Markdown 文件轻量级编辑功能

**日期**: 2026-08-04
**状态**: 已批准（待最终 spec 评审）
**目标版本**: v1.16

## 背景与动机

MD Browser 目前是只读的 Markdown 浏览器。用户在阅读协议文档、笔记时偶尔发现错别字或小错误，需要切换到外部编辑器修改再刷新。本功能允许直接在 web 界面进行轻量级文本修改并保存，省去上下文切换。

## 目标

- 在 topbar 右上角添加"编辑/保存"按钮，一键进入编辑模式
- 编辑模式下用 textarea 显示原始 Markdown 源码，保存后重新渲染
- 防止误丢未保存修改（切换文件 / 关闭页面时弹确认）
- 零新依赖，复用现有路径安全沙箱

## 非目标

- 不做所见即所得（WYSIWYG）富文本编辑
- 不做左右分栏实时预览
- 不做版本历史 / 撤销栈 / 多文件批量编辑
- 不做图片上传或附件管理

## 架构

整体仍是单后端 `server.py` + 单前端 `index.html`。新增一个 POST 端点用于保存，前端新增编辑视图状态与 textarea 元素。

```
┌─────────────────────────────────────────────────────┐
│  topbar: ☰ | breadcrumb | ◀▶ | [search] | ✏️ Edit  │
└─────────────────────────────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        │                             │
   阅读态（默认）                  编辑态（点 Edit 后）
   #content 渲染区               #editor textarea
   marked.js 渲染                原始 Markdown 源码
                                 [💾 Save] [✕ Cancel]
```

## 后端改动（server.py）

### 新增 `do_POST` 方法

`MDHandler` 目前只实现 `do_GET`。新增 `do_POST` 路由 `/api/save`：

1. 读取 Content-Length，从 `rfile` 读取 POST body
2. 解析 JSON：`{ "path": "<相对路径>", "content": "<新内容>" }`
3. 路径校验（复用 `handle_file` / `handle_asset` 的沙箱逻辑）：
   - `base_directory` 必须已设置
   - `target_path = (base_path / unquote(path)).resolve()`
   - `str(target_path).startswith(str(base_path))` 防穿越
   - 必须是 `.md` 文件
4. 写入文件：`target_path.write_text(content, encoding='utf-8')`
   - UTF-8 编码，与读取时一致（`handle_file` 用 `read_text(encoding='utf-8')`）
   - Python `write_text` 默认使用平台换行符翻译；为保持跨平台一致性，显式传入 `newline=''` 让 `\n` 原样写入，避免 Windows 上 `\n` 被 inflate 为 `\r\n` 造成 diff 噪音
5. 返回 JSON：`{ "success": true, "path": path, "size": <新字节数> }`
6. 错误处理：
   - 路径越界 → 403
   - 文件不存在 / 非 .md → 400
   - 写入异常（权限/占用）→ 500 + 错误消息

### 安全考量

- 完全复用现有 `base_directory` 沙箱模型，不引入新的文件访问路径
- POST body 大小限制：读取 Content-Length 后校验 `< 10MB`，防止恶意大 body（MD 文件通常远小于此）
- 不解析 / 执行文件内容，仅文本写入

## 前端改动（index.html）

### UI 元素

**topbar 新增按钮**（位于 `#search-wrapper` 右侧）：

```html
<button class="nav-btn" id="edit-btn" onclick="toggleEdit()" disabled title="Edit (Ctrl+E)">✏️</button>
```

- 无文件打开时 `disabled`
- 阅读态显示 `✏️`，title "Edit (Ctrl+E)"
- 编辑态显示 `💾`，title "Save (Ctrl+S)"，并紧邻显示 `✕ Cancel` 按钮

**编辑区**（位于 `#content-wrapper` 内，与 `#content` 同级）：

```html
<textarea id="editor" style="display:none;" spellcheck="false"></textarea>
```

样式：
- 等宽字体（`monospace`）
- 与 `#content` 相同的 max-width / padding / margin（阅读宽度一致）
- `width: 100%; min-height: calc(100vh - 44px);`（44px 为 topbar 高度）
- `resize: vertical`（允许纵向拉高，不横向拉伸以保持阅读宽度）
- 浅色边框，focus 时蓝色边框

### 状态机

新增全局变量 `isEditing = false` 和 `currentFileContent = null`。

`currentFileContent` 在 `loadFile` 成功 `fetchFile` 后赋值（`currentFileContent = data.content`），保存原始 Markdown 源码。编辑器从此变量取值，无需重新请求后端。未保存比较也基于此变量（`editor.value !== currentFileContent`）。

**`toggleEdit()` 函数**：
- 若 `isEditing === false`（阅读态）：
  - 检查 `currentFile` 存在
  - 显示 `#editor`，隐藏 `#content` 与 `#welcome`
  - 从 `currentFileContent` 填入 textarea
  - 按钮切 `💾`，显示 `✕ Cancel`
  - `isEditing = true`
  - 禁用 sidebar 文件点击的默认行为（改为触发未保存确认）
- 若 `isEditing === true`（编辑态）：调用 `saveEdit()`

**`saveEdit()` 函数**：
1. 从 `#editor.value` 取内容
2. POST `/api/save`，body `{ path: currentFile, content }`
3. 成功：
   - `currentFileContent = newValue`（更新内存副本）
   - 隐藏 `#editor`，显示 `#content`
   - 调用 `loadFile(currentFile)` 重新从磁盘加载并渲染（复用现有渲染管线：marked + Mermaid + KaTeX + hljs + 图片 + 行号，无需抽取新函数）
   - 按钮恢复 `✏️`，隐藏 Cancel
   - `isEditing = false`
   - breadcrumb 区域闪现 `✓ Saved` 文字 2 秒后恢复（用临时 span，不引入 toast 组件）
4. 失败：
   - 弹 `alert("保存失败: <error>")`
   - 留在编辑态，不切换视图

**`cancelEdit()` 函数**：
- `if (confirm('放弃未保存的修改？'))` → 退出编辑态，不保存，恢复原 `#content` 显示

### 未保存保护

三处拦截点：

1. **切换文件**（sidebar 点击 / `.md` 链接跳转 / 前进后退）：
   - 在 `loadFile(path)` 入口处检查 `isEditing`
   - 若为 true 且内容已变（`editor.value !== currentFileContent`）：`confirm("有未保存的修改，是否放弃？")`
   - 用户取消 → 中断加载，留在当前文件
   - 用户确认 → 退出编辑态，继续加载新文件

2. **页面关闭 / 刷新**：
   - `window.addEventListener('beforeunload', e => { if (isEditing && editor.value !== currentFileContent) { e.preventDefault(); e.returnValue = ''; } })`
   - 浏览器显示原生"未保存修改"提示

3. **Cancel 按钮**：见上文 `cancelEdit()`

### 快捷键

- `Ctrl+E`：切换编辑 / 保存（与现有 `Ctrl+K` 聚焦搜索、`Ctrl+←/→` 导航并列）
- `Ctrl+S`：编辑态下触发保存（`preventDefault` 拦截浏览器"另存网页"）
- 阅读态下 `Ctrl+S` 不拦截（或也不响应，避免与浏览器原生行为冲突）

在现有 `keydown` 事件处理函数中追加这两个分支。

### 按钮状态同步

- `loadFile` 成功后（`fetchFile` 返回后）：设置 `currentFileContent = data.content`，`edit-btn.disabled = false`
- `loadFile` 失败 / 无文件时：`edit-btn.disabled = true`
- 编辑态下：sidebar 文件项点击仍可用，但会触发未保存确认

## 数据流

```
阅读态点 Edit
  → 显示 textarea（内容来自 currentFileContent 内存副本，无需重新请求）
  → 用户编辑
  → 点 Save 或 Ctrl+S
  → POST /api/save {path, content}
  → server.py 校验路径 + 写文件
  → 返回 {success, size}
  → 前端更新 currentFileContent
  → 调用 loadFile(currentFile) 重新加载渲染（复用完整渲染管线）
  → 切回阅读态
```

## 边界情况

| 情况 | 处理 |
|------|------|
| 无文件打开点 Edit | 按钮 disabled，不响应 |
| 编辑中文件被外部修改 | 保存时直接覆盖（轻量级工具，不做冲突检测；用户可接受） |
| 保存时文件被占用（另一个进程写锁） | server 返回 500，前端 alert，留在编辑态 |
| 编辑超大文件（>5MB） | textarea 可能卡顿，但不在本期优化范围；POST body 上限 10MB 兜底 |
| 切换目录（`/api/switch`）时正在编辑 | `switchDirectory()` 入口加未保存确认 |
| 编辑态下点击搜索结果跳转 | 触发 `loadFile`，走未保存确认逻辑 |
| 切换目录（`switchToDir`） | `switchDirectory` 和 `pickFolder` 均调用 `switchToDir`，在该函数入口加未保存确认 |

## 测试要点

- 路径穿越攻击：POST `path: "../../../etc/passwd"` → 403
- 非 .md 文件：POST `path: "foo.txt"` → 400
- 正常保存 → 文件内容更新，重新渲染正确
- 编辑后切换文件 → 弹确认
- 编辑后关闭页面 → 浏览器弹未保存提示
- Ctrl+S / Ctrl+E 快捷键生效
- 取消编辑 → 内容不保存，恢复原渲染
- 保存失败 → 留在编辑态，内容不丢

## 不涉及

- 不修改 `build.py` / `build.bat`（打包流程不变）
- 不修改 `/api/asset`、`/api/tree`、`/api/search` 等现有端点
- 不改动单实例检测、端口回退等基础设施
- README 更新（新增功能说明 + API 端点）放在实现完成后
