# MD Browser — Markdown 文件浏览器

轻量级本地 Markdown 文件浏览器，面向结构化知识库（如协议文档、笔记集合），支持目录树导航、全文搜索、文档大纲和交叉引用跳转。

## 快速启动

### 方式一：双击 exe（推荐）

1. 双击 `md-browser.exe`，浏览器自动打开
2. 点击 **📂 Open Folder** 选择 Markdown 目录（或输入路径）
3. 关闭时在终端窗口按 `Ctrl+C`

```
md-browser.exe [目录路径]

# 示例
md-browser.exe                                # 启动后从 UI 选目录
md-browser.exe D:\docs\001-network-protocols  # 直接打开指定目录
md-browser.exe --port 3000                    # 指定端口
```

### 方式二：Python 直接运行

```bash
python server.py
python server.py ../001-network-protocols
```

## 功能特性

### 目录导航

| 功能 | 说明 |
|------|------|
| **原生文件夹选择器** | 点击 📂 Open Folder 弹出 Windows 目录选择对话框 |
| **路径输入** | 也可直接输入路径，按 Enter 或点 Go 打开 |
| **记忆上次目录** | 自动记住上次打开的目录，下次启动直接恢复 |
| **可折叠目录树** | 文件夹展开/折叠，README 自动置顶 |

### 文档阅读

| 功能 | 说明 |
|------|------|
| **Markdown 渲染** | GFM 表格、代码语法高亮、Mermaid 图表、数学公式、ASCII 图表 |
| **数学公式** | 行内 `$...$` 与块级 `$$...$$`，基于 KaTeX 渲染 LaTeX 语法（`\frac`、`\sum`、`\text` 等） |
| **Mermaid 图表** | 支持流程图、时序图、脑图、甘特图、类图、状态图等所有 Mermaid 图表类型，渲染失败时显示错误信息和源码 |
| **交叉引用跳转** | 点击文档内 `.md` 链接直接跳转到目标文件 |
| **锚点跳转** | 支持 `file.md#heading` 跨文件锚点和 `#heading` 同页面锚点 |
| **文档大纲 (Outline)** | 侧边栏 Files/Outline 切换，显示 h1~h4 标题结构，点击跳转（从 MD 源码提取，不依赖渲染 DOM） |

### 搜索

| 功能 | 说明 |
|------|------|
| **全文模糊搜索** | 搜索所有 MD 文件的文件名和内容，大小写不敏感 |
| **实时结果** | 输入 2 字符后自动搜索，或按 Enter / 点 Search 手动触发 |
| **结果高亮** | 匹配文本高亮显示，点击跳转到对应文件和位置 |
| **搜索定位** | 点击搜索结果后自动滚动到匹配位置，黄色高亮标记，首个匹配项加粗 |
| **搜索历史** | 聚焦搜索框显示最近 8 条搜索记录，↑↓ 键导航，可单条删除或一键清空 |
| **代码行号** | 代码块左侧显示行号（2 行以上自动显示），方便定位 |

### 导航控制

| 功能 | 快捷键 | 说明 |
|------|--------|------|
| **后退** | `Ctrl + ←` | 返回上一个浏览过的文档 |
| **前进** | `Ctrl + →` | 前进到下一个文档 |
| **聚焦搜索** | `Ctrl + K` | 快速聚焦搜索框 |
| **关闭搜索** | `Esc` | 关闭搜索结果下拉 |

## 常见问题

### 启动报 `WinError 10013` / 端口绑定失败

Windows 上端口 8080 等可能被 **Hyper-V / WSL2 / Docker Desktop** 预留或占用，导致套接字绑定抛 `PermissionError: WinError 10013`。

- **自动处理**：v1.6 起程序会自动回退到备用端口（8181 / 8484 / 9000 / 3000），通常无需干预。
- **手动指定**：用 `--port` 指定一个空闲端口：
  ```bash
  md-browser.exe --port 8484
  ```
- **排查保留端口**（管理员权限）：
  ```bash
  netsh interface ipv4 show excludedportrange protocol=tcp
  ```
  若目标端口落在某个 `Start Port - End Port` 区间内，说明被系统保留，换一个区外的端口即可。

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `目录路径` | 初始目录（可省略，从 UI 选择） | 无 |
| `--port, -p` | 监听端口 | 8080 |
| `--host, -H` | 绑定地址 | localhost |
| `--no-browser` | 不自动打开浏览器 | false |

### 示例

```bash
# 启动后从 UI 选目录
python server.py

# 直接打开指定目录
python server.py ../001-network-protocols

# 指定端口
python server.py ../002-openstack --port 3000

# 允许局域网内其他设备访问
python server.py ../001-network-protocols --host 0.0.0.0
```

## 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | >= 3.7 | 仅运行 `server.py` 时需要（3.7+ for `ThreadingHTTPServer`） |
| PyInstaller | 最新 | 仅构建 exe 时需要 |
| 浏览器 | Chrome / Edge | 支持 `SHBrowseForFolder` 原生对话框 |

**运行时零依赖** — 后端仅使用 Python 标准库：
`http.server`, `pathlib`, `json`, `argparse`, `webbrowser`, `ctypes`, `threading`

前端 JS 库通过 CDN 加载（首次需联网，之后浏览器缓存）：
- [marked.js](https://marked.js.org/) — Markdown 渲染
- [highlight.js](https://highlightjs.org/) — 代码语法高亮
- [mermaid.js](https://mermaid.js.org/) — 图表渲染（流程图、时序图、脑图等）
- [KaTeX](https://katex.org/) — 数学公式渲染（LaTeX 语法）

## 构建 exe

```bash
pip install pyinstaller
build.bat
```

生成的 `dist/md-browser.exe` 为单文件独立可执行程序（约 5.6MB），可拷贝到任意 Windows 机器直接使用，无需安装 Python。

## 项目结构

```
003-md-viewer/
├── server.py          # Python 后端（多线程 HTTP 服务 + API）
├── index.html         # 前端 SPA（随 exe 打包）
├── build.bat          # Windows 一键构建脚本
├── requirements.txt   # 依赖说明（无第三方运行时依赖）
├── .gitignore
└── README.md          # 本文件
```

## API 接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/tree` | GET | 返回当前目录的 MD 文件树结构 |
| `/api/file?path=...` | GET | 返回指定 MD 文件的内容 |
| `/api/switch?dir=...` | GET | 切换到指定目录 |
| `/api/search?q=...` | GET | 全文搜索，返回匹配结果 |
| `/api/pick-folder` | GET | 打开原生文件夹选择对话框 |

## 更新日志

### v1.9.1 — 公式渲染健壮性修复
- **KaTeX 加载时序修复**: CDN 慢加载时 `katex` 可能未就绪导致部分公式渲染失败、显示原始 LaTeX。改为等待就绪后重试（最多 20s）
- **渲染失败兜底**: 单条公式 KaTeX 报错时显示带样式的原始 LaTeX，不阻塞其它公式
- **占位符残留安全网**: 极端情况下占位符未被替换时，自动还原为 LaTeX 文本，避免出现 `@@MATH...@@`
- **KaTeX 完全不可用时**: 20s 后放弃等待，全部公式降级为原始 LaTeX 文本显示

### v1.9 — 数学公式支持（KaTeX）
- **行内公式**: `$...$` 渲染为行内数学公式（如 `$a_i$`、`$\frac{1}{2}$`）
- **块级公式**: `$$...$$` 渲染为居中独立公式（可跨行），如 `$$\sum_{i=1}^n x_i$$`
- **完整 LaTeX 语法**: 支持 `\text{}`、`\ge`、`\sum`、`\frac{}{}`、`\times`、上下标、希腊字母等
- **智能识别**: 代码块/行内代码内的 `$` 不误识别；`$100`（价格）、`\$50`（转义）不触发公式
- **渲染保护**: 公式在 marked 渲染前提取为占位符，避免 `_`、`*`、`{}` 被 Markdown 语法破坏
- **搜索兼容**: 搜索高亮跳过 KaTeX 内部，不破坏已渲染公式

### v1.8 — 搜索历史记忆
- **历史记录**: 搜索词自动存入 localStorage，最多保留 8 条，去重置顶
- **历史下拉**: 聚焦搜索框（内容为空）时显示最近搜索，点击即重填并搜索
- **键盘导航**: 历史/结果列表内 ↑↓ 切换高亮，Enter 直接选用
- **单条删除 & 清空**: 每条历史可单独删除，底部"Clear all"一键清空
- **智能记录时机**: 仅在明确提交（Enter / Search 按钮 / 复用历史）时记录，避免输入到一半的词被误记

### v1.7 — 文件夹选择器路径修复
- **64 位 PIDL 截断修复**: 64 位 Python 打包的 exe 中，`SHBrowseForFolder` 默认 `c_long` 返回值会截断 64 位 PIDL 指针，导致 `SHGetPathFromIDListW` 拿到损坏指针、路径取空——选完目录不生效。改用显式 `W` 变体 + `restype=c_void_p` 指针安全传递，32/64 位均正确
- **BROWSEINFO 修正**: `pszDisplayName` 改为 `c_wchar_p`（Unicode），与 W 变体一致
- **错误可见化**: `pick_folder` 异常不再静默吞掉，写入 stderr 便于排查

### v1.6 — 端口绑定健壮性
- **端口自动回退**: 请求端口绑定时（WinError 10013 等），自动尝试备用端口（8080 → 8181 → 8484 → 9000 → 3000），不再直接崩溃
- **清晰报错**: 全部端口失败时输出根因和排查命令（`netsh interface ipv4 show excludedportrange protocol=tcp`）
- **异常覆盖**: 捕获 OSError / OverflowError / ValueError，兼容端口越界等异常

### v1.5 — Mermaid 图表支持
- **Mermaid 渲染**: 支持所有 Mermaid 图表类型（流程图、时序图、脑图、甘特图、类图、状态图等）
- **错误处理**: 渲染失败时显示可折叠错误信息和原始代码，不阻塞页面
- **智能跳过**: Mermaid 代码块自动跳过 hljs 语法高亮和行号添加

### v1.4 — 搜索定位 & 代码行号 & 选择器修复
- **搜索结果定位**: 点击搜索结果后自动跳转到匹配位置并高亮显示（黄色标记），首个匹配项加粗高亮
- **代码行号**: 代码块左侧显示行号（2 行以上自动显示）
- **对话框聚焦**: 设置 `hwndOwner` 为 `GetForegroundWindow()`，文件夹选择对话框弹出时自动获得焦点
- **路径传递可靠性**: 移除多余子线程层，直接在 HTTP 请求线程调用对话框，避免 COM 线程模型不稳定导致路径丢失
- **COM 清理**: 使用 `try/finally` 确保 `CoUninitialize()` 始终执行

### v1.3 — 文档大纲 & 锚点跳转
- **Outline tab**: 侧边栏 Files/Outline 切换，从 MD 源码正则提取 h1~h4 标题（跳过代码块），点击平滑滚动到对应位置
- **跨文件锚点**: `file.md#heading` 链接正确拆分路径和片段，加载文件后自动滚动
- **同页面锚点**: `#heading` 链接在当前文档内跳转
- **Ctrl+Left/Right**: 前进后退快捷键

### v1.2 — 搜索 & 导航
- **全文模糊搜索**: 搜索所有 MD 文件的文件名和内容，Ctrl+K 快捷聚焦，Enter/按钮手动触发
- **前进/后退按钮**: 浏览历史记录，按钮 + 快捷键导航
- **Search 按钮**: 手动触发搜索（除自动防抖外）

### v1.1 — 目录选择 & 多线程
- **原生文件夹选择器**: 📂 按钮弹出 Windows 目录选择对话框（ctypes SHBrowseForFolder）
- **记忆上次目录**: localStorage 持久化，启动自动恢复
- **ThreadingHTTPServer**: 多线程处理并发请求，多浏览器可同时访问
- **浏览器启动修复**: 等待服务器端口就绪后再打开浏览器，避免 chrome-error

### v1.0 — 初始版本
- Python 后端（标准库，零依赖）+ 单 HTML 前端（marked.js + highlight.js）
- 目录树侧边栏、Markdown 渲染、交叉引用跳转、PyInstaller 打包为单文件 exe
