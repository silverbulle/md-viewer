# MD Browser — Markdown 文件浏览器

轻量级本地 Markdown 文件浏览器，支持目录树导航和文件间交叉引用链接。

## 快速启动

### 方式一：双击 exe（推荐）

1. 双击 `md-browser.exe`，浏览器会自动打开
2. 在左侧输入框输入目录路径，点"打开"
3. 关闭时在终端窗口按 `Ctrl+C`

```
md-browser.exe [目录路径]

# 示例
md-browser.exe                              # 启动后从 UI 选目录
md-browser.exe D:\docs\001-network-protocols  # 直接打开指定目录
md-browser.exe --port 3000                    # 指定端口
```

### 方式二：Python 直接运行

```bash
python server.py
python server.py ../001-network-protocols
```

## 构建 exe

需要 Python 和 PyInstaller：

```bash
pip install pyinstaller
build.bat
```

生成的 `dist/md-browser.exe` 即为独立可执行文件，可拷贝到任意位置使用。

## 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | >= 3.6 | 仅运行 `server.py` 时需要 |
| PyInstaller | 最新 | 仅构建 exe 时需要 |
| 浏览器 | 现代浏览器 | Chrome / Edge / Firefox |

**运行时零依赖** — 后端仅使用 Python 标准库（`http.server`, `pathlib`, `json`, `argparse`, `webbrowser`）。

前端 JS 库通过 CDN 加载（需联网首次访问，之后浏览器会缓存）：
- [marked.js](https://marked.js.org/) — Markdown 渲染
- [highlight.js](https://highlightjs.org/) — 代码高亮

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `目录路径` | 初始目录（可省略，从 UI 选择） | 无 |
| `--port, -p` | 监听端口 | 8080 |
| `--host, -H` | 绑定地址 | localhost |
| `--no-browser` | 不自动打开浏览器 | false |

## 功能特性

- **双击启动** — exe 自动打开浏览器，无需命令行
- **目录切换** — 在侧边栏输入任意路径即可切换浏览目录
- **目录树侧边栏** — 可折叠的目录结构，README 自动置顶
- **Markdown 渲染** — 支持 GFM 表格、代码高亮、ASCII 图表
- **交叉引用导航** — 点击文档内的 `.md` 链接直接跳转
- **路径安全** — 限制在指定目录内，防止路径穿越

## 项目结构

```
003-md-viewer/
├── server.py          # Python 后端（API + 静态服务）
├── index.html         # 前端 SPA（随 exe 打包）
├── build.bat          # Windows 构建脚本
├── requirements.txt   # 依赖说明（无第三方运行时依赖）
└── README.md          # 本文件
```
