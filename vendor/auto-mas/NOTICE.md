# AUTO-MAS（vendored）

本目录包含 [AUTO-MAS](https://cnb.cool/AUTO-MAS-Project/AUTO-MAS.git) 的**后端**源码，以 vendor 方式内嵌进 game-launcher-hub。

- 上游仓库：https://cnb.cool/AUTO-MAS-Project/AUTO-MAS.git
- 锁定 commit：`c77f213f6ef0e475c7eade615e14825ff59fddf4`
- 提交日期：2026-10-08 10:09:04 +0800
- 上游许可证：**AGPL-3.0**（见本目录 `LICENSE`）
- vendor 时间：2026-10-10 05:10:32

## 引入范围（仅后端）

| 项 | 说明 |
|---|---|
| `main.py` | 后端入口（支持受监督模式） |
| `app/` | 后端业务代码 |
| `res/` | 后端资源 |

**未引入**：Electron 前端（`frontend/`）、测试（`tests/`）、文档（`docs/`）、
上游 Git 历史。前端由 game-launcher-hub 自身承担。

## 使用约束

1. **不修改**本目录内任何上游源码；需要修复请向上游提 PR。
2. 上游代码保持 AGPL-3.0；本目录与 game-launcher-hub 的集成产物，
   在**分发**前必须确保整体许可证兼容（AGPL-3.0）。
3. 与上游的交互仅通过「外部监督器协议」：
   - 环境变量 `AUTO_MAS_SUPERVISED=1`、`AUTO_MAS_SUPERVISED_PORT=<port>`
   - `GET /api/core/health`、`POST /api/core/close`

## 本地运行

后端由 `launcher.py` 的 `ServiceWorker` 以子进程方式拉起，
不嵌入其 Electron GUI。
