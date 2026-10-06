# game-launcher-hub v1.0.1

> v1.0.0 为首个正式稳定版，但打包后首次启动即崩（已撤回）。本版修复打包缺陷，并**包含 v1.0.0 的全部功能**，故把完整更新日志一并列出。

## 相对 v0.3.0 测试版的变化（即 v1.0.0 的功能）

### 性能（卡顿根因修复）
- 总览页进程状态检测从「每卡片主线程同步 `tasklist /V`」重构为 Win32 瞬时调用 + `ProcScanner` 单例 + 单一 5s 心跳。
- 实测：同机 306 进程下，6 个助手状态轮询从 **3270ms → 11ms（约 300 倍）**，周期性粘滞感消除。

### 社区反馈（GitHub 集成）
- 详情页新增「社区反馈」：一键跳转 / 创建 GitHub Issue（预填环境信息），不再造数据孤岛。
- 评分区改为客观指标推算（提交频率主导、star 微调）+ 允许本地覆盖，不编造分布数据。

### GitHub 登录
- 设置页支持 PAT 登录，令牌经 Windows DPAPI 加密存储（`.cache/github_token.bin`，不进 config.json），API 配额升至 5000 次/小时。

## v1.0.1 修复
- **打包版首次启动即崩**：PyInstaller spec 漏打包 `config.example.json`，导致无法自动生成 `config.json`。现已随包附带 `config.example.json` 与 `config.reserved.json`，双击即可启动。
- 找不到配置时的报错改为可照做的提示文案（不再只抛裸 `FileNotFoundError`）。

## 使用
- 下载 `game-launcher-hub.exe`，放任意目录双击即可，无需本机 Python 环境。
- **首次运行会在 exe 同目录自动生成 `config.json`**（内容取自随包模板，`install_root` 默认 `D:/OKApps`）。若你的助手装在别处，改这个 `config.json` 的 `install_root` 即可。
