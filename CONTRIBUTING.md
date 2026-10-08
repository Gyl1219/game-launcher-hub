# 贡献指南

感谢你想改进这个项目！先花 5 分钟读完本文，能避开这里踩过的所有坑。

本项目是**单文件 PySide6 桌面应用**（`launcher.py`，约 1.2 万行），GPL-3.0 开源。

---

## 1. 环境搭建

```bash
git clone https://github.com/<你的用户名>/game-launcher-hub.git
cd game-launcher-hub
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux / macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

依赖清单以 `requirements.txt` 为准（含精确版本）。核心只有三个：
**PySide6**、**PySide6-Fluent-Widgets**（导入名 `qfluentwidgets`）、**dulwich**。

> ⚠ 注意 pip 包名与导入名不一致：`PySide6-Fluent-Widgets` → `import qfluentwidgets`。
> 网上很多教程写的是 `PyQt-Fluent-Widgets`（Qt5/PyQt 版），**本项目用的是 PySide6 版**，装错会崩。

## 2. 配置

```bash
cp config.example.json config.json
```

然后按你本机实际情况改 `config.json`：`install_root` 与各 app 的
`exe` / `app_json` / `working` / `pythonw`（均相对 `install_root`，用正斜杠）。

**没有装任何游戏助手也能跑**——界面会显示"未安装"，不影响开发 UI 相关功能。

## 3. 运行

```bash
python launcher.py
```

### 无显示器环境（CI / 容器 / 远程）

```bash
QT_QPA_PLATFORM=offscreen python launcher.py
```

`offscreen` 下窗口不会真的显示，但能验证「导入不报错、页面能构建、不闪退」，
是 CI 里最有用的冒烟手段。

---

## 4. 改代码前必读的四条铁律

这四条都是**真实事故**换来的，破坏任意一条都会导致启动器打不开或行为错乱。

### ① `py_compile` 通过 ≠ 能跑，必须用真实解释器验证

```bash
python -m py_compile launcher.py        # 只能查语法
python -c "import launcher"             # 这一步才能查出 NameError / 导入缺失
```

**事故案例**：新写的类继承了 `QObject`，但忘了在文件顶部 import 它。
`py_compile` 完全通过，用户双击直接闪退（`NameError: name 'QObject' is not defined`）。

更完整的验证（构建窗口对象）：

```bash
QT_QPA_PLATFORM=offscreen python -u -c "
import launcher, sys, os
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
w = launcher.Launcher(); w.show()
print('OK'); sys.stdout.flush()
os._exit(0)          # 必须：见下方说明
"
```

> ⚠ 末尾的 `os._exit(0)` 不是多余的：启动器常驻着后台线程（进程扫描 / 心跳 /
> 版本拉取），Python 正常退出时会撞上 `QThread: Destroyed while thread is still
> running`，Windows 下表现为**已经打印出 `OK`、功能其实正常，但退出码是
> `0xC0000409`（-1073740791）**。第一次跑的人极易把它误当成崩溃。
> `-u` 是为了让 `OK` 及时刷出来。

### ② 往类里插新方法，锚点绝不能选「某个方法内部的尾部片段」

**事故案例**：给主窗口加 `resizeEvent` 时，锚点选了 `__init__` 末尾两行做替换，
结果新方法被插进 `__init__` 中间，原本属于 `__init__` 的 8 步初始化
（心跳启动、定时器）全变成 `resizeEvent` 里的死代码。语法合法、功能测试还全绿，
但用户一启动就崩。

正确做法：**锚点选下一个方法的 `def` 行**，把新方法插在它前面。

### ③ 进程检测绝不能用 `tasklist /V` 做轮询

`tasklist /V` 的「窗口标题」列会向每个窗口 `SendMessage(WM_GETTEXT)`，
遇到无响应窗口不超时返回 → 界面周期性卡死。实测同机 306 进程下 6 个应用全查要
**3270ms**；改用 ctypes Win32 API（`CreateToolhelp32Snapshot` + `EnumWindows`）后
**11ms**。

已有架构：`ProcScanner` 主线程单例（TTL 3s）+ `ProcScanWorker(QThread)` +
`HeartBeat` 单一 5 秒心跳。**新增卡片请接入这两个单例，不要自己 `new QTimer` 轮询。**

### ④ 更新流程必须"事后校验真实产物"

历史上出现过「`app.json` 写着 v3.6.7、实际跑的代码还是 v3.6.4」的假更新，
根因是两处 `except: pass` 把失败静默吞掉了。现在更新流程有 5 道闸门，
任何一层失败都必须返回 False 并中止，**绝不能留下"显示成功、实际没做"的状态**。
改这块逻辑时务必保持纵深，别为了"少报错"把校验去掉。

---

## 5. 测试

`tests/` 下是**独立可执行脚本**（不是 pytest 用例），直接跑：

```bash
QT_QPA_PLATFORM=offscreen python tests/carousel_test.py
```

每个脚本会打印 `PASS` / `FAIL` 行，末尾给汇总（`N failed` 或 `通过 X / 失败 Y`）。

> ⚠ **判断成败请看 stdout 的汇总行，不要只看退出码。**
> 本项目常驻后台线程（进程扫描 / 心跳 / 版本拉取），测试进程退出时
> Windows 下常被 Qt 线程销毁污染退出码（`0xC0000409` 或偶发 `0xC0000005`），
> 出现「明明 `0 failed` 却返回非 0」。**这是已知的测试基建问题，不是你的改动坏了。**
> 部分脚本已改用 `os._exit()` 规避，但仍可能偶发；CI 里建议这样判：
>
> ```bash
> python tests/carousel_test.py > out.txt 2>&1
> grep -q "^FAIL" out.txt && echo "有失败" || echo "全通过"
> ```

> ⚠ 另一个已知问题：`tests/` 下有 8 个脚本**硬编码了**
> `sys.path.insert(0, r"D:\OKApps\launcher")`（作者本机绝对路径）。
> 你在别的位置跑，要么改那行，要么在仓库根目录执行并设 `PYTHONPATH=.`。
> 已经用相对推导 `os.path.dirname(os.path.abspath(__file__))` 的脚本是正确写法，
> 这是待改进项，欢迎提 PR 把剩下的统一过去。

改 UI / 更新逻辑相关代码后，**至少跑一遍** `carousel_test.py`、`rank_test.py`、
`install_ctrl_test.py`、`self_update_test.py`。

## 6. 本地打包（可选）

```bash
pip install pyinstaller
pyinstaller game-launcher-hub.spec --noconfirm --clean
# 产物：dist/game-launcher-hub.exe
```

两个坑：

1. **打包前先杀掉正在运行的旧 exe**，否则旧文件被锁 → 构建失败：
   ```bash
   taskkill /F /IM game-launcher-hub.exe
   ```
2. **`spec` 的 `datas` 必须包含 `config.example.json` 和 `config.reserved.json`**。
   漏掉会导致打包版首次启动直接崩（找不到配置模板、无法生成 `config.json`）。

打包后自测：

```bash
QT_QPA_PLATFORM=offscreen timeout 25 ./dist/game-launcher-hub.exe
```

退出码 124（超时被杀）表示**正常运行中**，不是崩溃；同时 exe 同目录会生成
`config.json`，即证明初始化成功。

## 7. 提交 PR 的规范

### 分支

**每个 PR 用独立分支，只放该 PR 的目标改动。**

> 真实教训：曾经 fork 的 `main` 分支被推了整个启动器源码，于是提一个"改一行文档"的
> PR，实际变成了 **+4200 行**（拖进了全量代码、还含本机绝对路径的草稿脚本），
> 被代码审查标记为高风险，PR 直接废掉。

```bash
git checkout -b fix/banner-scale upstream/main   # 从上游 main 开分支
# ... 改代码 ...
git commit -m "fix(banner): 说明改了什么、为什么"
git push origin fix/banner-scale
```

### Commit message

用约定式提交前缀，正文写清**为什么**（不只是做了什么）：

```
fix(overview): 排行榜字号随栏宽缩放

上一版只撑高了卡片外壳，里面的图标和字号是写死的，全屏下仍显小。
```

常用 scope：`sidebar` / `overview` / `banner` / `settings` / `install` / `update` / `pack`

### PR 描述

- 说清**改动动机**和**验证方式**（跑了哪些测试、截图/录屏）；
- 如果是 UI 改动，**附前后对比图**；
- 不要只写"见代码"。

### 其它

- 不要提交 `config.json`（含本机路径，已在 `.gitignore`）；
- 不要提交 `.cache/`、`repos/`、`logs/`、`__pycache__/`、`dist/`、`build/`；
- 不要提交 `*.bak*` 备份文件；
- 本项目仅支持 Windows（依赖 Win32 API 与 `pywin32`），Linux/macOS 只能跑 offscreen 冒烟。

## 8. 提 Issue

用仓库的 Issue 模板（Bug / 功能请求）。报 bug 请尽量带上：

- 启动器版本（设置页底部有「版本 vX.Y.Z」）
- 操作系统版本
- 复现步骤
- `logs/error.log` 的相关片段（**贴之前把路径、用户名、CDK、邮箱等敏感信息打码**）

---

## 9. 代码结构速查

单文件但分区清晰，按注释标题定位：

| 关键字 | 内容 |
|---|---|
| `APPS` / `load_apps` | 应用配置加载（全部路径来自 config.json） |
| `GitVersionFetcher` | 读本地 git 仓库拿版本列表与 changelog |
| `MirrorUpdater` / `ApplyWorker` | 更新下载与"应用到 working" |
| `InstallWorker` | 一键安装（下载 release → 解压） |
| `ProcScanner` / `HeartBeat` | 进程检测单例与统一心跳 |
| `NavButton` / `SideBar` | 左侧导航（含折叠与随窗口缩放） |
| `AppCard` | 单个助手的详情页卡片 |
| `OverviewPage` / `BannerCarousel` / `RankRail` | 总览页、海报轮播、排行榜 |
| `SettingsPage` / `SettingsDialog` | 设置（独立窗口） |

---

有不清楚的地方，欢迎开一个 Issue 问，或者直接按 README 里的 QQ 群联系开发者。
