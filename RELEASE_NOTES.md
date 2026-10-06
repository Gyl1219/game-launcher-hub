# game-launcher-hub v1.0.1

> v1.0.0 首发即发现打包缺陷，本版为修复版。功能与 v1.0.0 一致。

## 修复
- **打包版启动即报「找不到 config.json」**：PyInstaller spec 漏打包 `config.example.json`，
  导致首次运行无法自动生成配置。现已随包附带，双击 exe 即可启动。
- **预约列表在打包版读不到**：`config.reserved.json` 现已随包，且在 exe 同目录缺失时自动回退到随包副本。
- 找不到配置时的报错改为可照做的提示文案（不再只抛裸 `FileNotFoundError`）。

## 使用
- 下载 `game-launcher-hub.exe`，放任意目录双击即可，无需本机 Python 环境。
- **首次运行会在 exe 同目录自动生成 `config.json`**（内容取自随包模板，`install_root` 默认 `D:/OKApps`）。
  若你的助手装在别处，改这个 `config.json` 的 `install_root` 即可。
- 其余同 v1.0.0：总览页进程状态检测重构（消除周期性卡顿）、详情页社区反馈 + 客观评分、
  设置页 GitHub PAT 登录（DPAPI 加密）。
