# 游戏助手启动器 (game-launcher-hub)

> **非官方第三方工具**，与 ok-script 项目方及各游戏官方均无隶属关系。
>
> 一个统一管理基于 [ok-script](https://ok-script.com/) 框架的各游戏自动化启动器的桌面工具。
> 左侧总览 / 各游戏 / 设置导航，右侧堆叠内容区，一个窗口看遍所有助手的运行状态、版本、更新日志，
> 一键启动 / 强制关闭 / 窗口内更新。主页聚合更新横幅轮播、活跃度 / 星标 / 我的使用三榜，
> 以及 MirrorChyan 全项目的「预约」区。
>
> 当前支持 ok-script 系（ok-nte / ok-ww / ok-end-field）+ 非该系的奇想盒（Whimbox，lite 接入）、绝区零一条龙（generic 接入）与 MaaEnd 终末地小助手（zip 发布接入），架构上不绑定单一框架，后续可接入其它生态。

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
- **主页信息聚合**：顶部横幅轮播（可更新 / 未安装 / 启动器自身发版）+ 右侧三个小榜
  （活跃度 = 近 30 天提交数、星标 = GitHub stars、我的使用 = 本机启动次数），带本地缓存与失败回退，打开主页不等网络。
- **MirrorChyan 全项目「预约」**：尚未适配的项目先进预约区（可搜索、按生态分组、按票数排序），
  「我想要」投票搭遥测匿名汇总，票数决定后续适配优先级。

---

## 与 AUTO-MAS 的区别（不是同类竞品）

常被问「不是已经有 AUTO-MAS 了吗」。两者都带「管理多个脚本」的字样，但**管的层级完全不同**：

> **AUTO-MAS 管「跑起来的任务」，本工具管「助手本体」。**

| 维度 | AUTO-MAS | 本工具（游戏助手启动器） |
|---|---|---|
| 一句话定位 | 多脚本 × 多配置的**批量代肝调度器** | 多游戏助手的**安装器 + 进程/版本看板** |
| 管什么 | 脚本实例 × 用户配置 × 任务队列 | 助手本体（装 / 启 / 停 / 更新 / 卸载） |
| 多账号配置管理 | ✅ 核心能力 | ❌ 不做（交给各助手自己） |
| 任务队列 / 调度编排 | ✅ 核心能力 | ❌ 不做 |
| 日志监看 + 异常自动重启 | ✅ 核心能力（无人值守） | ❌ 不做 |
| 代理记录 / 日志片段留存 | ✅ | ❌ |
| **安装助手本体** | ❌ 假定已装好 | ✅ **NSIS 整包直解、17 节点测速、MirrorChyan CDK** |
| **版本 / changelog 查看** | ❌ | ✅ 读本地 git 仓库，与原启动器同源 |
| **一键更新助手** | ❌ | ✅ 窗口内更新并应用到 working |
| 卸载（含清理残留） | ❌ | ✅ 三档：保留缓存 / 彻底清除 / 取消 |
| 体积 | **GB 级**（Electron，主程序 196 MB） | 源码 312 KB；打包单文件 exe **约 112 MB** |
| 技术栈 | Electron + Python 后端 | 纯 Python（PySide6 + qfluentwidgets） |
| 协议 | AGPL-3.0 | GPL-3.0 |
| 遥测 | 收集版本号 + 运行时错误 + 性能追踪（Sentry SaaS），**默认开启** | **默认关闭**；可手动开启匿名错误上报（详见下） |

### 覆盖的游戏也不同（关键）

AUTO-MAS 的脚本适配器为 `general / M9A / MAA / MaaEnd / Okww / SRC`：

- `Okww` → 鸣潮 **ok-ww**（与本工具管的是同一个）
- `MaaEnd` → 终末地，但走 **MaaFramework** 生态，**不是** ok-script 系的 `ok-end-field`
- **没有 `ok-nte`（异环）** —— AUTO-MAS 不支持异环

而本工具三个都管，且**全部是 ok-script 系**：`ok-nte` / `ok-ww` / `ok-end-field`。
想在 ok-script 系里用异环、或用 `ok-end-field`（而非 MaaEnd）管终末地，AUTO-MAS 帮不上忙。

### 结论：上下游关系，可以一起用

两者不是二选一，而是**互补**：

```
本工具：把 ok-nte / ok-ww / ok-end-field 装好、更新好、看住谁在跑
   ↓
AUTO-MAS：拿这些已装好的助手，编排多账号任务队列、无人值守代肝
```

如果你只需要「装 / 看 / 更新几个助手」，本工具更轻（无需 GB 级 Electron，遥测默认关闭）；
如果需要「多账号轮转 + 崩溃自动重启 + 任务编排」，那是 AUTO-MAS 的领域，本工具不做也不打算做。

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

**默认不发送任何数据。** 出错时只会写到本地 `logs/error.log`，不联网。

如果你愿意帮作者修 bug，可以在「设置」里手动开启匿名错误上报。开启后：

| | 内容 |
|---|---|
| **会发送** | 程序版本号、错误类型、**脱敏后**的调用栈、操作系统/Python 版本、一个本地随机生成的匿名 ID |
| **不会发送** | 你的配置文件内容、安装路径原文、用户名、CDK、邮箱、任何游戏相关数据 |

发送前所有文本都会过一遍脱敏：本机绝对路径 → `<HOME>` / `<LAUNCHER_DIR>` / `<INSTALL_ROOT>`，
`cdk=` / `token=` / 密码 → `<redacted>`，邮箱 → `<email>`。
匿名 ID 只用于统计「有多少独立用户在用」，删掉 `.cache/anon_id` 即可重置。

配置（`config.json`，默认全关）：

```json
"telemetry": { "enabled": false, "ping": false, "endpoint": "" }
```

- `enabled`：是否上报崩溃
- `ping`：是否额外发一次启动计数（用于统计活跃用户）
- `endpoint`：接收地址。**留空则即便 `enabled: true` 也不会发送任何东西**

---

## 环境依赖

- Python 3.10+
- [PySide6](https://pypi.org/project/PySide6/)
- [PyQt-Fluent-Widgets](https://pypi.org/project/PyQt-Fluent-Widgets/)（`qfluentwidgets`）

安装：

```bash
pip install PySide6 PyQt-Fluent-Widgets
```

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
