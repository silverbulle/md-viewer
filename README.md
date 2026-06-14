# MD Browser — Markdown 文件浏览器

轻量级本地 Markdown 文件浏览器，支持目录树导航和文件间交叉引用链接。

## 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | >= 3.6 | 使用标准库，无需 pip install |
| 浏览器 | 现代浏览器 | Chrome / Edge / Firefox |

**无第三方依赖** — 后端仅使用 Python 标准库（`http.server`, `pathlib`, `json`, `argparse`）。

前端 JS 库通过 CDN 加载（需联网首次访问，之后浏览器会缓存）：
- [marked.js](https://marked.js.org/) — Markdown 渲染
- [highlight.js](https://highlightjs.org/) — 代码高亮

验证环境：
```bash
python --version    # 确认 >= 3.6
# 无需 pip install，无 requirements 需安装
```

## 快速启动

```bash
cd 003-md-viewer
python server.py
```

浏览器打开 http://localhost:8080 ，在左侧输入框输入目录路径（如 `D:\claude\001-network-protocols`）点"打开"即可。

## 命令行参数

```bash
python server.py [目录路径] [--port 端口] [--host 主机]
```

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `目录路径` | 初始目录（可省略，从 UI 选择） | 无 |
| `--port, -p` | 监听端口 | 8080 |
| `--host, -H` | 绑定地址 | localhost |

### 示例

```bash
# 启动后从浏览器 UI 选目录
python server.py

# 直接指定初始目录
python server.py ../001-network-protocols

# 指定端口
python server.py ../002-openstack --port 3000

# 允许局域网访问
python server.py ../001-network-protocols --host 0.0.0.0
```

## 功能特性

- **目录切换** — 在侧边栏输入任意路径即可切换浏览目录
- **目录树侧边栏** — 可折叠的目录结构，README 自动置顶
- **Markdown 渲染** — 支持 GFM 表格、代码高亮、ASCII 图表
- **交叉引用导航** — 点击文档内的 `.md` 链接直接跳转
- **零依赖** — 纯 Python 标准库，无需 `pip install`
- **路径安全** — 限制在指定目录内，防止路径穿越

## 项目结构

```
003-md-viewer/
├── server.py          # Python 后端（API + 静态服务）
├── index.html         # 前端 SPA
├── requirements.txt   # 依赖说明（无第三方依赖）
└── README.md          # 本文件
```
