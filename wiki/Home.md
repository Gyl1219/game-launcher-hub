# 游戏助手启动器 (game-launcher-hub)

> **非官方第三方工具**，与 ok-script 项目方及各游戏官方均无隶属关系。
> 一个窗口管理所有游戏助手的安装 / 启动 / 更新 / 卸载，统一看板，不再开一堆窗口。

## 下载

- **打包版**：到 [Releases](https://github.com/Gyl1219/game-launcher-hub/releases) 下载 `game-launcher-hub.exe`（单文件免安装，约 107 MB，自带 Python 运行时）
- **源码运行**：克隆仓库后 `pythonw launcher.py`（依赖 PySide6 / qfluentwidgets / dulwich）

## 支持的应用

| 助手 | 游戏 | 接入方式 |
|---|---|---|
| [ok-nte](https://github.com/BnanZ0/ok-nte) | 异环 | ok-script 系 |
| [ok-wuthering-waves](https://github.com/ok-oldking/ok-wuthering-waves) | 鸣潮 | ok-script 系（社区最活跃） |
| [ok-end-field](https://github.com/AliceJump/ok-end-field) | 终末地 | ok-script 系 |
| [Whimbox](https://github.com/nikkigallery/Whimbox) | 奇想盒 | 非 ok-script 系，lite 接入 |
| [绝区零一条龙](https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon) | 绝区零 | 非 ok-script 系，generic 接入 |
| [MaaEnd](https://github.com/MaaEnd/MaaEnd) | 终末地小助手 | MaaFramework 系，zip 发布接入 |

架构上不绑定单一框架，后续可接入其它生态。

## 常见问题

### 下载能暂停 / 取消吗？

能。下载大文件（如 MaaEnd 309 MB）时进度条旁有「⏸ 暂停 / ▶ 继续」和「✕ 取消」：
暂停保留已下部分，继续时 HTTP Range 断点续传；取消立即停止并删除半截临时文件。

### 安装 / 更新时报 416？

上次下载中断留下的临时文件尺寸 ≥ 服务器文件，导致续传 Range 越界。
v0.2.3 起自动处理：本地已下完整就直接用（不重下 309 MB），不完整则删掉重下。

### 和 AUTO-MAS 是什么关系？

**上下游互补，不是竞品**：AUTO-MAS 管「跑起来的任务」（多账号配置、任务队列、日志监看无人值守），
本工具管「助手本体」（安装 / 启动 / 强制关闭 / 更新 / 卸载）。且 AUTO-MAS 不支持异环 ok-nte、
终末地走 MaaEnd 而非 ok-end-field。详见 [README](https://github.com/Gyl1219/game-launcher-hub#与-auto-mas-的区别不是同类竞品)。

### 为什么进程识别靠窗口标题？

各助手由 PyAppify 打包，运行时进程名都是 `pythonw.exe`，无法按进程名区分，
所以用 `tasklist /V` 按窗口标题匹配。

## 构建

```bash
python -m PyInstaller game-launcher-hub.spec --noconfirm --clean
```

产物为单文件 `dist/game-launcher-hub.exe`。

## 参与维护

本项目以 **GPL-3.0** 开源，欢迎接手。上游生态入口见 [README 贡献章节](https://github.com/Gyl1219/game-launcher-hub#贡献--接手)。
