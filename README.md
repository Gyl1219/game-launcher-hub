# 游戏助手启动器 (game-launcher-hub)

> **非官方第三方工具**，与 ok-script 项目方及各游戏官方均无隶属关系。
>
> 一个统一管理基于 [ok-script](https://ok-script.com/) 框架的各游戏自动化启动器的桌面工具。
> 左侧总览 / 各游戏 / 设置导航，右侧堆叠内容区，一个窗口看遍所有助手的运行状态、版本、更新日志，
> 一键启动 / 强制关闭 / 窗口内更新。主页聚合更新横幅轮播、活跃度 / 星标 / 我的使用三榜，
> 以及 MirrorChyan 全项目的「预约」区。
>
> 当前支持 ok-script 系（ok-nte / ok-ww / ok-end-field）+ 非该系的奇想盒（Whimbox，lite 接入）、绝区零一条龙（generic 接入）与 MaaEnd 终末地小助手（zip 发布接入），架构上不绑定单一框架，后续可接入其它生态。

> [!IMPORTANT]
> **关于接入新助手**：本项目为个人业余维护，精力有限，**不接单、不承诺时间表**。
> 想要哪个助手，去总览页「预约」区给它投「我想要」—— **票数高的优先适配**；
> 尚未适配的 79 个项目已全部收录在预约区，你的一票直接影响顺序。
> 也接受带理由的 issue（说明需求场景与该助手的维护活跃度）。

## 下载

到 [Releases](https://github.com/Gyl1219/game-launcher-hub/releases) 下载打包好的 `game-launcher-hub.exe`（单文件、免安装，自带 Python 运行时）；或克隆仓库后直接 `pythonw launcher.py` 跑源码（依赖 PySide6 / qfluentwidgets / dulwich）。

---

## 这是什么

ok-script 生态目前是「一个框架 (ok-script) + 一堆独立游戏仓库（ok-nte / ok-wuthering-waves / ok-end-field …）」的松散结构，每个游戏都要单独开一个窗口。本项目把这些启动器**聚合到一个侧栏式界面**里（左侧固定导航，右侧堆叠内容区），解决「开一堆窗口、看不清谁在跑、更新麻烦」的痛点。

核心能力：

- **统一卡片展示**：每个游戏一个卡片，含封面、版本下拉、更新日志（changelog）。
- **一键安装**：MirrorChyan 源整包下载（17 节点测速 + CDK），支持暂停 / 取消 / 断点续传。
- **真实运行态监测**：通过 `tasklist` 精确识别各启动器进程（PyAppify 打包后进程名是 `pythonw.exe`，靠窗口标题区分），徽章 + 独立「运行中」标签 + 启动/强制关闭按钮三控件分工。
- **窗口内更新**：下载目标版本到本启动器 `repos/<key>/`（不碰原启动器目录），可一键「应用到 working 目录」。
- **强制关闭**：运行中时按钮变「强制关闭」，二次确认后终止进程（需以管理员身份运行才能生效）。
- **单实例运行**：重复双击（含桌面快捷方式）不会再开第二个窗口，而是把已有窗口
  从最小化恢复并置前。避免两个实例各扫一遍进程表、各起一个任务编排后端、
  以及互相抢 WebSocket 导致日志闪跳。排查问题时可用 `LAUNCHER_ALLOW_MULTI=1` 临时多开。
- **主页信息聚合**：顶部横幅轮播（可更新 / 未安装 / 启动器自身发版）+ 右侧三个小榜
  （活跃度 = 近 30 天提交数、星标 = GitHub stars、我的使用 = 本机启动次数），带本地缓存与失败回退，打开主页不等网络。
- **MirrorChyan 全项目「预约」**：尚未适配的项目先进预约区（可搜索、按生态分组、按票数排序），
  「我想要」投票搭遥测匿名汇总，票数决定后续适配优先级。
- **AUTO-MAS 任务编排（v1.3.0 融合集成，可选组件）**：总览页右上角**恒显示**「AUTO-MAS」
  （它是编排插件，不是第 7 个游戏助手，所以**不占侧栏**）。
  - **首发不带 MAS**：exe 仍约 112 MB、仍是 GPL-3.0，不用的用户不会被拖着下载任何东西。
  - **要用再装**：点右上角 → 确认 → 自动下载官方增量包（约 116 MB）静默安装 → 装完自动进编排页；
    状态栏会明写「未安装（点此下载）」，不会让人误以为装了只是没启动。
  - 能用之后：建队列、排脚本、立即运行/停止循环、看实时日志，都在启动器里。
  - 要配账号密码 / 游戏路径 / 模拟器 / 定时任务等**完整表单**，在编排页点「完整配置」
    → 打开官方客户端窗口（一个 exe 开多窗口，不是两个软件）。
- **也能卸载**：编排页「组件（安装/卸载）」分段走注册表里的官方卸载程序。
  卸载只移除程序本体，**你在启动器里配的队列/账号数据（auto-mas/）保留不动**。

---

## 与 AUTO-MAS 的关系（上下游互补，现已融合集成）

常被问「不是已经有 AUTO-MAS 了吗」。两者都带「管理多个脚本」的字样，但**管的层级完全不同**：

> **AUTO-MAS 管「跑起来的任务」，本工具管「助手本体」。**

从 **v1.3.0** 起，两者不再是「装完再另开一个软件」：本工具用 **vendor 方式内嵌了
AUTO-MAS 的后端**（AGPL-3.0，锁 commit、保留上游 LICENSE 与 NOTICE，**不改上游一行源码**），
并在启动器内做了一个**原生 PySide6 的「AUTO-MAS 任务编排」页**——不引入它的 Electron 前端，
所以体积只多约 53 MB 的后端源码，而不是 GB 级 Electron 运行时。

| 维度 | AUTO-MAS | 本工具（游戏助手启动器） |
|---|---|---|
| 一句话定位 | 多脚本 × 多配置的**批量代肝调度器** | 多游戏助手的**安装器 + 进程/版本看板 + 编排入口** |
| 管什么 | 脚本实例 × 用户配置 × 任务队列 | 助手本体（装 / 启 / 停 / 更新 / 卸载）+ 编排控制台 |
| 多账号配置管理 | ✅ 核心能力（完整表单） | ⚠️ 只读展示账号列表，配置仍在官方界面里做 |
| 任务队列 / 调度编排 | ✅ 核心能力 | ✅ v1.3.0 起可在页面里建队列、加脚本、运行/停止、看日志 |
| 日志监看 + 异常自动重启 | ✅ 核心能力（无人值守） | ⚠️ 看后端日志与运行中任务的日志尾部；异常重启仍归后端 |
| 代理记录 / 日志片段留存 | ✅ | ❌（可跳官方界面） |
| **安装助手本体** | ❌ 假定已装好 | ✅ **NSIS 整包直解、17 节点测速、MirrorChyan CDK** |
| **版本 / changelog 查看** | ❌ | ✅ 读本地 git 仓库，与原启动器同源 |
| **一键更新助手** | ❌ | ✅ 窗口内更新并应用到 working |
| 卸载（含清理残留） | ❌ | ✅ 三档：保留缓存 / 彻底清除 / 取消 |
| 体积 | **GB 级**（Electron，主程序 196 MB） | 源码 500 KB；打包单文件 exe **约 112 MB**（AUTO-MAS 按需安装，不随包） |
| 技术栈 | Electron + Python 后端 | 纯 Python（PySide6 + qfluentwidgets）+ 监督式拉起同一后端 |
| 协议 | AGPL-3.0 | GPL-3.0（仓库含 AGPL 的 `vendor/auto-mas` 源码，但**发布的 exe 不含 AGPL 代码**，见下方许可证说明） |
| 遥测 | 收集版本号 + 运行时错误 + 性能追踪（Sentry SaaS），**默认开启** | **首次启动问一次，你选**；可随时关（详见下） |

### 集成方式（不 fork、不改上游）

```
启动器（PySide6）                        AUTO-MAS 后端（vendor/auto-mas，AGPL-3.0）
  ├─ 总览页右上角「AUTO-MAS 任务编排」─┐
  │    （编排插件入口，不占侧栏）        │
  ├────────────────────────────────────┘
  ├─ 编排页（原生）──HTTP──▶  FastAPI @ 127.0.0.1:<随机端口>
  ├─ 编排页（原生）──WS────▶  /api/core/ws（任务实时日志与状态）
  ├─ ServiceWorker(QThread) 监督子进程 ──▶  以 AUTO_MAS_SUPERVISED=1 拉起
  │    · 注入端口 / 期望版本，健康检查 /api/core/health
  │    · 退出时调 /api/core/close，超时再杀进程树
  └─ Windows Job Object 托管进程树（KILL_ON_JOB_CLOSE，不留孤儿 python）
```

- **入口在总览页右上角**（与「扫描游戏」同排，带状态灯：未启动/运行中/不可用），
  不在侧栏 —— 它与 6 个游戏助手不是同一层级，摆平级会让人以为是第 7 个助手。
- 打开页面时自动拉起后端并常驻；切页不停后端（可能正在跑队列），只有关启动器才优雅关闭。
- **实时任务日志**走后端原生 WebSocket `/api/core/ws`（任务级日志只有这条通道有，
  上游没有对应的 HTTP 接口）；官方界面（Electron）一连上，本页收到 `4001`
  就**主动让位、不再重连**，不会和它互踢。
- 后端进程**不弹控制台黑窗**（`CREATE_NO_WINDOW`），也**不会自行弹 UAC**（受监督模式的行为）。
- 数据落在启动器目录下的 `auto-mas/`（账号 / 队列 / 脚本配置 + 历史 + 日志），**不是** `.cache`
  —— 那是「随时可清」的目录，装用户配置会丢；旧版写在 `.cache/auto-mas` 的会自动搬过来。
- 缺 Python 3.12 环境时只有这一页标「不可用」，其余助手的安装/更新/启动完全不受影响。
- **安装 / 卸载**（与其它助手同构）：
  - 安装：从官方发布页取 `AUTO-MAS-Setup-<ver>-x64.zip`（CNB 镜像优先、GitHub 回退）
    → 解压 → 调官方安装程序静默装（参数照抄上游自己的更新流程
    `/SP- /SILENT /NOCANCEL /FORCECLOSEAPPLICATIONS /LANG=Chinese /DIR=<目录>`）。
    刻意**不自己复制文件**：安装路径、注册表项、开始菜单快捷方式都由它负责，
    重复实现只会做出一个「装了但卸不掉」的半吊子。
  - 卸载：读注册表 `UninstallString`（本机实测 `D:\AUTO-MAS\unins000.exe`）→ 带 `/S` 静默卸载。
    **只移除程序本体**，启动器自己的编排数据（`auto-mas/`）不受影响。
  - ⚠ 本功能只是**引导下载官方安装包**并调用官方安装程序，
    不内置、不分发 AUTO-MAS 的二进制。

> 📦 **打包相关**：AUTO-MAS 自带 Python 环境实测 449 MB、后端源码 57.7 MB，
> 打包版如何处理（含「打包版会回落 sys.executable 再开一个启动器」这个已修的坑）
> 见 [wiki/AUTO-MAS-打包与许可证评估.md](./wiki/AUTO-MAS-打包与许可证评估.md)。

> ⚖ **许可证**：本仓库为 GPL-3.0；仓库内 `vendor/auto-mas/` 是上游 AUTO-MAS 后端的
> 源码副本，遵循其原有 AGPL-3.0（保留上游 LICENSE 与 NOTICE，未改上游一行代码）。
> **发布的 exe 不含 AGPL 代码** —— 按需安装设计，后端不在随包资源里，
> 用户点右上角「AUTO-MAS」时才由官方安装程序单独安装官方发布包。
> 若将来要改成随包后端，则必须先把本项目改为 AGPL-3.0 或双许可。

### 覆盖的游戏也不同（关键）

AUTO-MAS 的脚本适配器为 `general / M9A / MAA / MaaEnd / Okww / SRC`：

- `Okww` → 鸣潮 **ok-ww**（与本工具管的是同一个）
- `MaaEnd` → 终末地，但走 **MaaFramework** 生态，**不是** ok-script 系的 `ok-end-field`
- **没有 `ok-nte`（异环）** —— AUTO-MAS 不支持异环（上游版本较新时以官方适配表为准）

而本工具三个都管，且**全部是 ok-script 系**：`ok-nte` / `ok-ww` / `ok-end-field`。
想在 ok-script 系里用异环、或用 `ok-end-field`（而非 MaaEnd）管终末地，AUTO-MAS 帮不上忙。

### 结论：上下游关系，现在一个窗口里就能串起来

```
本工具：把 ok-nte / ok-ww / ok-end-field 装好、更新好、看住谁在跑
   ↓
本工具内「AUTO-MAS 任务编排」页：开后端 → 建队列 → 排脚本 → 立即运行 / 看日志
   ↓
（需要账号密码、脚本路径、模拟器、通知渠道等完整配置时）→ 点「官方界面」跳 Electron 端
```

如果你只需要「装 / 看 / 更新几个助手」，本工具更轻（无需 GB 级 Electron，遥测由你决定）；
需要多账号轮转等**完整表单配置**时，本页做不到，请用官方界面——它的数据目录与本页不同，
两套配置各自独立。

---

## ⚠️ 免责声明

本软件是**第三方开源工具**，与上述游戏官方、ok-script 项目方均无隶属关系，仅供个人学习研究。

- 本项目基于 **ok-script** 生态构建，依其 Apache-2.0 + Commons Clause 协议要求，**明确提及并链接**：https://ok-script.com/
- 被管理的各游戏启动器（ok-nte / ok-ww / ok-end-field 等）各自拥有独立的开源协议
  （如 GPL-3.0 / AGPL-3.0，详见其各自仓库 LICENSE）。本工具仅以独立进程调用其可执行文件，**不复制、不修改其源码**，不构成衍生义务。
- 界面中使用的各游戏图标取自 ok-script 官方资源站（https://ok-script.com/），版权归各自项目方所有，仅作识别用途。
- 使用后果由使用者自行承担。

---

## 隐私 / 遥测

**首次启动会问一次，你自己选。** 不问之前一条都不发——不会"先收集再征求同意"。

三种选择：

| 你的选择 | 会发生什么 |
|---|---|
| **同意，帮助改进** | 崩溃日志 + 启动计数都发 |
| **只发崩溃日志** | 只发崩溃，不发启动计数（不想被统计但愿意帮忙修 bug） |
| **不发**（默认高亮，关窗口也算这个） | 一条都不发，只写本地 `logs/error.log` |

选完就记住，之后不再打扰；随时可在「设置 → 匿名错误上报」里改。

| | 内容 |
|---|---|
| **会发送** | 程序版本号、错误类型、**脱敏后**的调用栈、操作系统/Python 版本、一个本地随机生成的匿名 ID |
| **绝不发送** | 你的用户名、电脑名、文件路径原文、CDK / Token / 密码 / 邮箱、装了什么游戏、配置内容 |

发送前所有文本都会过一遍脱敏：本机绝对路径 → `<HOME>` / `<LAUNCHER_DIR>` / `<INSTALL_ROOT>`，
`cdk=` / `token=` / 密码 → `<redacted>`，邮箱 → `<email>`。
匿名 ID 只用于统计「有多少独立用户在用」，删掉 `.cache/anon_id` 即可重置。

配置（`config.json`）：

```json
"telemetry": {
  "enabled": true,
  "ping": true,
  "endpoint": "https://glh-tele.pages.dev/collect"
},
"telemetry_asked": true
```

- `enabled`：是否上报崩溃
- `ping`：是否额外发一次启动计数（用于统计活跃用户）
- `endpoint`：接收地址。**留空则即便 `enabled: true` 也不会发送任何东西**
- `telemetry_asked`：是否已问过（删掉它 = 下次启动重新问你）
- 想彻底关掉：把 `enabled` 设为 `false`，或把 `endpoint` 置空

> 自测链路：设置页有「发送测试上报」按钮，会在本机起临时接收端验一遍
> 发送→脱敏→接收，**不联网也不改配置**，用来确认功能本身是好的。

---

## 环境依赖

- Python 3.10+（仅支持 Windows）
- [PySide6](https://pypi.org/project/PySide6/) — Qt for Python
- [PySide6-Fluent-Widgets](https://pypi.org/project/PySide6-Fluent-Widgets/) — 导入名是 `qfluentwidgets`
- [dulwich](https://pypi.org/project/dulwich/) — 纯 Python 的 git 实现，拉版本列表用

安装（版本以 `requirements.txt` 为准）：

```bash
pip install -r requirements.txt
```

> ⚠ 包名注意：本项目用 **PySide6**-Fluent-Widgets。网上多数教程写的是
> `PyQt-Fluent-Widgets`（Qt5/PyQt 版），**装错会崩**。

想改代码请看 [CONTRIBUTING.md](./CONTRIBUTING.md)。

---

## 配置

所有路径都在 `config.json` 里，**不写死在代码里**。首次使用前把 `config.example.json` 复制为 `config.json`，再按需修改：

```bash
cp config.example.json config.json
```

```jsonc
{
  "install_root": "D:/OKApps",          // 你的游戏启动器根目录
  "apps": [
    {
      "key": "ok-nte",
      "display": "异环",
      "exe": "ok-nte/ok-nte/ok-nte.exe",          // 相对 install_root
      "app_json": "ok-nte/ok-nte/data/apps/ok-nte/app.json",
      "working": "ok-nte/ok-nte/data/apps/ok-nte/working",
      "pythonw": "ok-nte/ok-nte/data/apps/ok-nte/python/pythonw.exe",
      "icon": "assets/ok-nte.png",                // 可选，缺省回退到 assets/<key>.png
      "website": "https://ok-script.com/ok-nte/"
    }
    // ok-ww / ok-end-field 同理
  ]
}
```

> `exe / app_json / working / pythonw / icon` 均可写相对 `install_root` 的路径，也可写绝对路径。

---

## 运行

```bash
# 普通运行（监测、启动、更新均可，但「强制关闭」需管理员权限才生效）
python launcher.py

# 以管理员身份运行（推荐，强制关闭按钮才能真正杀进程）
# 右键「以管理员身份运行」或：
runas /user:Administrator "python launcher.py"
```

启动后会自动检测窗口主题并适配浅色/深色样式。

---

## 已知限制

1. **强制关闭需要管理员权限**：聚合启动器以普通权限运行时，`taskkill` 无法终止 PyAppify 启动器进程（拒绝访问）；以管理员身份运行后才会生效。
2. **运行态判定依赖 Windows `tasklist`**：目前仅支持 Windows。
3. **仅中文 Windows 体验最佳**：状态色遵循中国股票市场约定（涨/运行 → 红，跌 → 绿）。
4. 未适配的项目只提供「预约」占位（可投票催更），不提供下载安装；已适配项目的安装包均来自各项目官方发布渠道（NSIS 整包 / zip），本工具不做镜像。

---

## 上游生态：预约中（79）

以下为已收录、适配中的上游项目（按生态分组，点击名称直达仓库/官网），启动器内同一清单支持搜索与「我想要」投票：

**ok-script 系（9）**

- [ok-Onmyoji](https://github.com/YunLiuZ/ok-Onmyoji)
- [ok-er - 伊瑟](https://github.com/ok-oldking/ok-etheria)
- [ok-kes](https://ok-script.com/ok-kes/)
- [ok-script 按键精灵](https://ok-script.com/app/)
- [原神 ok-gi](https://github.com/ok-oldking/ok-genshin-impact)
- [少前2 ok-gf2](https://github.com/AliceJump/ok-gf2)
- [二重夜渊](https://ok-script.com/ok-duet-night-abyss/)
- [崩铁助手](https://ok-script.com/ok-starrailassistant/)（崩坏：星穹铁道）
- [星痕共鸣](https://ok-script.com/ok-star-resonance/)

**MaaFramework 系（32）**

- [MAATree](https://github.com/caicai00001/MAATree)
- [MAA_Punish](https://github.com/overflow65537/MAA_Punish)
- [MAA_SnowBreak](https://github.com/overflow65537/MAA_SnowBreak)
- [MBCCtools](https://github.com/quietlysnow/MBCCtools)
- [MCCA](https://github.com/MaaXYZ/MCCA)
- [Maa-Assistant-Browndust2](https://github.com/alkaidjin/Maa-Assistant-Browndust2)
- [Maa-HBR](https://github.com/KarylDAZE/Maa-HBR)
- [MaaADr](https://github.com/Azureetude/MaaADr)
- [MaaAshEchoes](https://github.com/moulai/MaaAshEchoes)
- [MaaDuDuL](https://mddl.codax.site/docs/)
- [MaaFgo](https://github.com/xlxyvergil/MaaFgo)
- [MaaGC](https://github.com/KhazixW2/MAAGC)
- [MaaGF2Exilium](https://github.com/DarkLingYun/MaaGF2Exilium)
- [MaaGakumasu](https://github.com/SuperWaterGod/MaaGakumasu)
- [MaaGumballs](https://maagb.xyz/)
- [MaaKEDR](https://github.com/APPLe-DF/MaaKEDR)
- [MaaLYSK](https://maalysk.top/)
- [MaaNTE](https://github.com/1bananachicken/MaaNTE)
- [MaaPVZ](https://github.com/Maa-Assistant-PVZ-The-best/MAAPVZ)
- [MaaQNZL](https://github.com/chenxing-ye/MaaQNZL)
- [MaaResonance](https://github.com/DaiMao204/MaaResonance)
- [MaaStarResonance](https://github.com/233Official/MaaStarResonance)
- [MaaYYs](https://github.com/TanyaShue/MaaYYs)
- [MaaYuan](http://maayuan.com/)
- [Maa_KES](https://github.com/miaojiuqing/Maa_Kes)
- [Maa_MHXY_MG](https://github.com/gitlihang/Maa_MHXY_MG)
- [火影忍者手游MAA](https://github.com/duorua/narutomobile)
- [识宝小助手](https://github.com/miaojiuqing/Maa_bbb)
- [MCC_Framework](https://github.com/MAACrossCore/MCC_Framework)（交错战线）
- [MRA](https://github.com/Saratoga-Official/MRA)（战舰少女R）
- [MAA](https://maa.plus/)（明日方舟）
- [MaaVillageConquest](https://github.com/kpAjun/MaaVillageConquest)（村长征战团）

**独立生态（38）**

- [AALC](https://github.com/KIYI671/AhabAssistantLimbusCompany)
- [AUTO-MAS](https://auto-mas.top/)
- [Ark-Pets](https://arkpets.harryh.cn/?from=mc)
- [Auto_Resonance](https://github.com/Night-stars-1/Auto_Resonance)
- [BAAH 爱丽丝助手](https://github.com/sanmusen214/BAAH)
- [BAAS](https://baas.wiki/)
- [BetterGI](https://bettergi.com/)
- [BetterNTE](https://github.com/BetterAutoFramework/BetterNTE)
- [FFmpegFreeUI](https://ffmpegfreeui.top/)
- [Haiyu](https://github.com/BlameTwo/Haiyu)
- [IMAO](https://github.com/kahvia-d/IMAO)
- [LALC](https://github.com/HSLix/LixAssistantLimbusCompany)
- [LocalizeLC](https://www.zeroasso.top/)
- [M9A](https://1999.fan/)
- [MATR](https://github.com/NotZoruak/MATR)
- [MMleo](https://github.com/fictionalflaw/MMleo)
- [MaaBD2](https://github.com/sunyink/MFABD2)
- [MangaProof](https://github.com/gunfub/MangaProof)
- [MicYou](https://micyou.top/)
- [New-ZexNote](https://github.com/BaiXiaoTao520/New-ZexNote)
- [OEA](https://oea.biohazard.top/)
- [OnmyojiDesktopAssistant](https://github.com/AquamarineCyan/OnmyojiDesktopAssistant)
- [PCL-CE](https://www.pclc.cc/projects/pcl-ce/)
- [Polymerium](https://github.com/d3ara1n/Polymerium)
- [ReveriePaint](https://reveriepaint.lanrhyme.top/)
- [SLIMEIM_Maa](https://github.com/miaojiuqing/SLIMEIM_Maa)
- [SRA](https://starrailassistant.top/)
- [SkiHide](https://skihide.xyz/)
- [三月七小助手](https://m7a.top/)
- [千机链](https://one-dragon.com/tools/zh/script_chainer.html)
- [明日方舟速通](https://github.com/AegirTech/ArkLights)
- [模拟宇宙自动化](https://github.com/CHNZYX/Auto_Simulated_Universe)
- [胡桃重制版](https://github.com/SnapHutaoRemasteringProject/Snap.Hutao.Remastered)
- [花笺 Floral Notepaper](https://github.com/Achilng/floral-notepaper)
- [Better HSR-Currency Wars](https://github.com/439awsl-hue/Better-HSR-Currency-Wars)（崩坏：星穹铁道）
- [异环驱动计算器](https://github.com/hxwd94666/NTE-Drive-Calculator)
- [MR3A](https://github.com/originalsage/MR3A)（忍者必须死3）
- [SSAH](https://github.com/SodaCodeSave/StellaSora-Auto-Helper)（星塔旅人）

---

## 贡献 / 接手

本项目以 **GPL-3.0** 开源，欢迎接手维护。

- 代码托管：https://github.com/Gyl1219/game-launcher-hub
- **贡献指南**：[CONTRIBUTING.md](./CONTRIBUTING.md) — 环境搭建、本地运行/打包、
  测试怎么跑、提 PR 的规范，以及四条「破坏就会闪退」的铁律
- **依赖清单**：[requirements.txt](./requirements.txt)
- 报 Bug / 提功能请求：直接开 [Issue](https://github.com/Gyl1219/game-launcher-hub/issues/new/choose)（有模板）
- 上游生态入口：
  - ok-script 框架：https://ok-script.com/
  - ok-wuthering-waves（鸣潮，社区最活跃）：https://github.com/ok-oldking/ok-wuthering-waves
  - ok-nte（异环）：https://github.com/BnanZ0/ok-nte
  - ok-end-field（终末地，ok-script 系）：https://github.com/AliceJump/ok-end-field
  - MaaEnd（终末地小助手，MaaFramework 系，zip 发布接入）：https://github.com/MaaEnd/MaaEnd
  - Whimbox（奇想盒，非 ok-script 系 lite 接入）：https://github.com/nikkigallery/Whimbox
  - 绝区零一条龙（绝区零，非 ok-script 系 generic 接入）：https://github.com/OneDragon-Anything/ZenlessZoneZero-OneDragon
  - 开发者交流：ok-script 官方 QQ 群 938132715

---

## 许可证

GPL-3.0，详见 [LICENSE](./LICENSE)。本项目基于 ok-script（Apache-2.0 + Commons Clause）生态，特此署名：https://ok-script.com/
