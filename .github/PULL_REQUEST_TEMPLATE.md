## 这个 PR 解决什么

<!-- 一句话说明动机。修 bug 就写「现象 + 根因」，加功能就写「解决什么问题」。
     有对应 Issue 的话在这里写 `Closes #编号`。 -->

Closes #

## 怎么改的

<!-- 关键实现点。为什么这样做、有没有考虑过别的方案。 -->

## 验证方式

<!-- **必填**。本项目 py_compile 通过 ≠ 能跑，请务必至少做下面第 1 项。 -->

- [ ] `python -c "import launcher"` 不报错（能查出 NameError / 漏 import）
- [ ] `QT_QPA_PLATFORM=offscreen python -c "..."` 能构建出 `Launcher()` 窗口
- [ ] 跑过相关测试脚本（`tests/` 下，如 `carousel_test.py` / `rank_test.py`）
- [ ] 本机实际点过一遍受影响的交互

具体做了什么：

## 截图 / 录屏

<!-- UI 改动**必须**附前后对比图。GitHub 里直接把图片拖进输入框就能上传。 -->

## 提交前确认

- [ ] **用的是独立分支**，本 PR 只含目标改动（不要夹带无关文件、本机绝对路径脚本、`*.bak`）
- [ ] 没有提交 `config.json` / `.cache/` / `repos/` / `logs/` / `dist/` / `build/`
- [ ] commit message 说明了「为什么」，不只是「做了什么」
- [ ] 改到更新流程 / 进程检测时，已阅读 CONTRIBUTING.md 第 4 节的四条铁律

<!--
提醒（本项目作者自己踩过的真实教训）：曾经提一个「改一行 README」的 PR，
因为 fork 的 main 分支被推了整个启动器源码，结果变成 +4200 行、
还夹带了含本机绝对路径的草稿脚本，被审查标记为高风险，PR 直接作废。
请一定从上游 main 开干净分支。
-->
