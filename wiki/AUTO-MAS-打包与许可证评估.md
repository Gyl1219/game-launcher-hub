# AUTO-MAS 融合：打包与许可证可行性评估

> 面向：项目作者 / 后续维护者。写于 v1.3.0（集成页面上线后）。
> 结论先行：**技术上可分三步走，但「分发」这一步被许可证卡住，必须先做决策。**

---

## 1. 现状（实测数据，非估算）

| 项 | 大小 | 说明 |
|---|---|---|
| `vendor/auto-mas`（后端源码） | **57.7 MB** | `res/` 占 45.3 MB（图片/音频资源）；`app/` 仅约 8 MB / 475 文件 |
| AUTO-MAS 自带 Python 环境 `environment/python` | **449.2 MB** | 上游锁 Python 3.12.0 + 全部依赖（fastapi / uvicorn / loguru / opencv / numpy…） |
| AUTO-MAS 完整安装目录 | **1 961.4 MB** | 含 Electron 前端（`resources/` 92 MB、`locales/` 42.5 MB、`.git/` 41.8 MB） |
| 当前启动器单文件 exe | 约 **112 MB** | PyInstaller onefile（PySide6 + qfluentwidgets） |

## 2. 当前打包版的三处硬缺口

### ① `spec` 根本没打包 `vendor/auto-mas`
`game-launcher-hub.spec` 的 `datas` 只有 `assets` / `config.example.json` / `config.reserved.json`。
所以**打包版里没有任何后端源码**，页面只会显示「未找到 AUTO-MAS 后端（vendor 缺失）」。

### ② 已修：打包版曾会"回落到自己"再开一个启动器
旧 `auto_mas_paths()` 在找不到解释器时回落 `sys.executable`。PyInstaller onefile 下
`sys.executable` 就是 `game-launcher-hub.exe` 本身 → `Popen([exe, main.py])` 会**再开一个
启动器窗口**（或直接参数报错），而不是拉起后端。

v1.3.0 已修：`_auto_mas_python_candidates()` 在 `sys.frozen` 为真时不再回落，
`auto_mas_paths()` 区分「后端缺失 → `("", "")`」与「后端在但无解释器 → `(repo, "")`」，
界面据此给出**可照做的**提示（缺 Python 3.12），且只影响该页，其余功能不受影响
（`tests/mas_card_test.py` 第 6 组断言守着）。

### ③ 打包版没有 Python 3.12，而后端必须用它
上游锁定 3.12.x，且依赖很重（自带环境 449 MB）。onefile exe 不可能内嵌。

## 3. 三条可选路线（按落地成本排序）

### 路线 A：打包版不含后端，只给"入口 + 明确提示"（**推荐先做**）
- 行动：`spec` 里**不加** `vendor/auto-mas`；页面在缺解释器/缺源码时给出清晰提示 +
  「打开官方界面」按钮（已有）。
- 体积：**不变**（约 112 MB）。
- 优点：零风险、许可证最干净（打包产物里**不含** AGPL 代码，见 §4 路线 ①）。
- 缺点：打包版用户要自己装 AUTO-MAS 才能用编排页；「开箱即用」不成立。

### 路线 B：随包 vendor 源码 + 首次运行创建独立 venv
- 行动：`spec` 加 `('vendor/auto-mas', 'vendor/auto-mas')`（+57.7 MB，exe 约 170 MB）；
  首次点「启动后端」时若检测不到解释器 → 用系统 Python 3.12 建 venv 并
  `pip install -r vendor/auto-mas/requirements.txt`，装到 `<launcher>/auto-mas-runtime/`。
- 体积：exe +57.7 MB；运行期再占约 250~400 MB（venv）。需要**网络 + 国内镜像**，
  且要处理「用户没有 Python 3.12」的情况（那就还得引导装 Python）。
- 优点：一次配置后接近开箱即用。
- 风险：依赖安装是长流程（可能几分钟），要有进度/失败回滚；上游 requirements 变动要跟。
- 备注：`res/` 45.3 MB 里大量是 MAS Web 前端的图片/音效，原生页面基本不展示，
  **可评估剔除**（但 `Notifications` 里的素材、技能图标等可能有引用，需逐项实测）。

### 路线 C：随包 AUTO-MAS 自带 Python 环境（**不建议**）
- exe 会到 560 MB+（onefile 还要在临时目录解压，启动变慢），
  已接近"再装一个 Electron 版 AUTO-MAS"的体积，与本项目"轻"的定位冲突。
- 若真要走，正确形态是 **onedir 安装包（NSIS）**，而不是 onefile exe。

## 4. 许可证：分发前的硬闸门

事实：
- 本项目 `LICENSE` = **GPL-3.0**；`vendor/auto-mas/LICENSE` = **AGPL-3.0**。
- 两者的不兼容是公认结论（AGPL 第 13 条的网络服务条款正是 GPL 所无）。
- **聚合 ≠ 衍生**：把两个程序放在同一台机器/同一安装包里，与"把 AGPL 代码编译进同一程序"
  在法律定性上不同——但这是需要作者自行判断（必要时咨询专业人士）的部分，
  本文只给工程侧建议，不构成法律意见。

三条路径：

1. **分发不含 AGPL 代码的产物**（= 上面的路线 A）
   打包版不随包 `vendor/auto-mas`，只保留"调用本机已安装的 AUTO-MAS"的代码路径。
   主程序仍为 GPL-3.0。**代价**：没有开箱即用。
2. **整项目改为 AGPL-3.0（或双许可）**
   最省事、最一致：`LICENSE` / `README` / 发布页说明 / `spec` 一起改。
   代价：AGPL 比 GPL 严（对外提供服务也须开源），会影响一些使用场景。
3. **双产物**：源码版/自用版含后端（不分发），分发版不含后端（GPL）。
   工程上要维护两条打包配置，且用户容易混淆，不太推荐。

> ⚠ 无论选哪条：**在做出决策前不要分发含 `vendor/auto-mas` 的产物**。
> `CONTRIBUTING.md` 顶部与 `vendor/auto-mas/NOTICE.md` 已写明同一约束。

## 5. 建议的执行顺序

1. **先按路线 A 把打包版跑通**：`spec` 保持不含 vendor，验证「缺后端时页面提示正确、
   其余功能正常」+ exe 仍 112 MB 左右（这一步不涉及许可证决策，可以立刻做）。
2. 再决定「开箱即用」值不值：如果值 → 选路线 B + 许可证决策 ②；不值 → 停在路线 A。
3. 若走路线 B，先做一次**离线实测**：把 `environment/python` 之外的依赖装进独立 venv，
   量出真实体积与安装耗时，再决定是否剔除 `res/` 中的 Web 前端素材。

## 5.1 安装 / 卸载（已实现，v1.3.0）

用户反馈：「有些用户只有一个号不用这个 mas」→ MAS 定位成**可选组件**，
编排页新增「组件（安装/卸载）」分段，与其它助手同构。

| 动作 | 实现 | 依据 |
|---|---|---|
| 取包 | `AUTO-MAS-Setup-<ver>-x64.zip`，CNB 优先、GitHub 回退（复用仓库既有的 `_resolve_release_asset`） | 上游 `app/services/update.py:357/374` |
| 安装 | 解压 → 调官方安装程序，参数 `/SP- /SILENT /NOCANCEL /FORCECLOSEAPPLICATIONS /LANG=Chinese /DIR=<目录>` | 照抄上游自己的更新流程 `update.py:703-711` |
| 卸载 | 读注册表 `UninstallString` → 带 `/S` 静默 | 本机实测 `D:\AUTO-MAS\unins000.exe` |
| 体积 | zip 约 116 MB；装完约 1.9 GB（含 449 MB 的 Python 运行环境） | v5.6.2 实测 |

两条刻意的设计：
1. **不自己复制安装文件**——安装路径、注册表项、开始菜单快捷方式全交给官方安装程序，
   自己实现只会得到一个「装了但卸不掉」的半吊子。
2. **卸载只移除程序本体**，启动器自己的编排数据（`auto-mas/` 下的队列/账号/历史）保留不动，
   想连它们一起清需要用户手动删目录（这也是卸载确认框里写明的话）。

## 6. 打包后自测清单（每次改动都要跑）

```powershell
# 0) 先杀残留（旧 exe 被锁会导致构建失败）
taskkill /F /IM game-launcher-hub.exe

# 1) 构建
D:\OKApps\ok-nte\...\python.exe -m PyInstaller game-launcher-hub.spec --noconfirm --clean

# 2) 随包内容核验（TOC 里应有 config.example.json / config.reserved.json）
python -c "from PyInstaller.archive.readers import CArchiveReader as R; print([n for n in R('dist/game-launcher-hub.exe').toc if 'config' in n])"

# 3) 无头存活 25s（提前退出才是崩溃；正常是"杀进程前一直活着"）
$env:QT_QPA_PLATFORM='offscreen'
$p = Start-Process .\dist\game-launcher-hub.exe -PassThru
if ($p.WaitForExit(25000)) { "提前退出 rc=$($p.ExitCode) —— 有问题" } else { "存活 25s 正常"; $p.Kill() }
#    跑完确认 exe 同目录生成了 config.json（首次初始化成功），然后清测试残留：
#    taskkill /F /IM game-launcher-hub.exe ; del dist\config.json ; rmdir /s /q dist\.cache dist\logs

# 4) MAS 页在打包版里的表现（本轮新增的降级路径）
#    打开 MAS 页 → 若提示「缺 Python 3.12 / 未找到后端」且其它页正常 = 通过；
#    若弹出第二个启动器窗口 = 回归（见 §2 ②）
```

## 7. 体积账（供决策）

| 方案 | 分发体积 | 用户额外占用 | 开箱即用 |
|---|---|---|---|
| A 不含后端 | 约 112 MB | 用户自装 AUTO-MAS（约 1.9 GB） | ❌ |
| B 含后端源码 + 运行期 venv | 约 170 MB | venv 约 250~400 MB | ✅（需网络） |
| C 含后端 + 自带 Python 环境 | 560 MB+ | 基本为 0 | ✅ |
| 现状（未处理） | 112 MB | — | ❌（页面提示"未找到后端"，本轮已把提示做准） |
