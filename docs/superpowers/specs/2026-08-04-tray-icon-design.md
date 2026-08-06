# 设计文档：系统托盘图标

**日期**: 2026-08-04
**状态**: 已批准

## 目标

exe 运行时在系统托盘显示图标，双击重新打开浏览器，右键菜单可退出进程，无需任务管理器。

## 方案

ctypes 调用 Windows Shell_NotifyIconW API，零新依赖。在 `server.py` 中新增 `run_tray_icon()` 函数，将 HTTP server 移到 daemon 线程，主线程运行消息循环。

## 设计

### run_tray_icon(server, url)

1. 注册隐藏窗口类（RegisterClassExW + 自定义 WindowProc）
2. 创建隐藏窗口（CreateWindowExW）
3. Shell_NotifyIconW(NIM_ADD) 添加托盘图标，图标用 LoadIconW(0, IDI_APPLICATION)
4. 消息循环（GetMessageW / TranslateMessage / DispatchMessageW）
5. WindowProc 处理：
   - WM_APP+1（托盘回调）：左键双击 → webbrowser.open(url)；右键抬起 → 弹出菜单
   - WM_COMMAND（菜单项）：server.shutdown() + PostQuitMessage(0)
6. 弹出菜单：CreatePopupMenu + AppendMenuW("Exit") + TrackPopupMenu

### main() 改动

serve_forever() 移到 daemon 线程，主线程调用 run_tray_icon()。退出时：Shell_NotifyIconW(NIM_DELETE) + server.shutdown() + remove_lock()。

### Tooltip

"MD Browser — localhost:PORT"

### 不涉及

- 不改动 build.py
- 不改动 index.html
- 不引入第三方依赖
