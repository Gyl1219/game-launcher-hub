# -*- coding: utf-8 -*-
"""「预约中」条目回归测试。

核心要固化的三点：
- 预约条目**绝不**进入安装/启动链路，也不会被轮播误判成「尚未安装 / 去安装」；
- 预约条目不建 AppCard（否则 5 秒轮询和游戏扫描会为几十条空转）；
- 缺 key / 缺 display 的脏配置不能把启动器搞崩。
"""
import os
import sys
import json
import shutil
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"D:\OKApps\launcher")

import launcher  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OK, FAIL = [], []


def chk(name, cond):
    (OK if cond else FAIL).append(name)
    print(("PASS  " if cond else "FAIL  ") + name)


qapp = QApplication.instance() or QApplication([])
TMP = tempfile.mkdtemp(prefix="reserved_t_")
os.makedirs(os.path.join(TMP, ".cache"), exist_ok=True)

RESERVED = [
    {"key": "res-1", "display": "预约1", "reserved": True,
     "ecosystem": "maa", "game": "某游戏A", "website": "https://a.example/"},
    {"key": "res-2", "display": "预约2", "reserved": True,
     "ecosystem": "ok-script", "game": "某游戏B", "website": "https://b.example/"},
]
LIVE = [
    {"key": "live-a", "display": "正式A"},
    {"key": "no-display"},                     # 缺 display：必须兜底成 key
    {"display": "没有key"},                     # 缺 key：必须整条跳过
]

json.dump({"install_root": TMP, "apps": LIVE},
          open(os.path.join(TMP, "config.json"), "w", encoding="utf-8"),
          ensure_ascii=False)
json.dump({"apps": RESERVED},
          open(os.path.join(TMP, "config.reserved.json"), "w", encoding="utf-8"),
          ensure_ascii=False)
# 预置一份"新鲜"的 GitHub 统计缓存，避免总览页构造时真的去打网络
json.dump({"repos": {}, "fetched_at": time.time(), "attempted_at": time.time()},
          open(os.path.join(TMP, ".cache", "github_stats.json"), "w", encoding="utf-8"))

ORIG_DIR = launcher.LAUNCHER_DIR
launcher.LAUNCHER_DIR = TMP


class FakeCard:
    """假 AppCard：只提供总览页会读的 snapshot。"""

    def __init__(self, installed=True):
        self._installed = installed

    def snapshot(self):
        return {
            "reserved": False, "installed": self._installed, "host_ready": False,
            "version": "v1", "running": False, "badge": "已安装",
            "status": "", "has_update": False, "game_found": "",
        }


# ===== 加载与加固 =====
apps = launcher.load_apps()
chk("缺 key 的条目被整条跳过", not any(a.get("key", "") == "" for a in apps))
chk("缺 display 兜底为 key",
    [a for a in apps if a["key"] == "no-display"][0]["display"] == "no-display")
res = [a for a in apps if a.get("reserved")]
live = [a for a in apps if not a.get("reserved")]
chk("预约条目被合并进 APPS", len(res) == 2)
chk("正式条目不受影响", len(live) == 2)
chk("预约条目没有本地安装路径",
    all(not a.get("exe") and not a.get("working") for a in res))

# ===== 轮播：预约条目不能被当成「未安装 / 去安装」=====
cards = {"live-a": FakeCard(), "no-display": FakeCard()}
slides = launcher.build_banner_slides(apps, cards)
chk("轮播不含预约条目",
    not any(s["key"] in ("res-1", "res-2") for s in slides))
chk("启动器自身条目仍在（未被挤掉）",
    any(s["key"] == "__self__" for s in slides))

# ===== 安装 / 启动守卫 =====
res_card_cfg = [a for a in res if a["key"] == "res-1"][0]
chk("预约条目不在 InstallWorker.REPOS 里",
    "res-1" not in launcher.InstallWorker.REPOS)
chk("预约条目不在 GitHub 统计表里",
    not (set(launcher._GITHUB_REPOS) & {a["key"] for a in res}))

# ===== 我想要 +1 =====
launcher.record_wish("res-1")
launcher.record_wish("res-1")
launcher.record_wish("res-2")
counts = launcher._wish_counts()
chk("投票计数累加", counts.get("res-1") == 2 and counts.get("res-2") == 1)
chk("本机已投记录落盘", launcher._wish_voted().get("res-1") is True)

# ===== 预约区：排序 / 搜索 / 卡片 =====
sec = launcher.ReservedSection(res)
chk("预约区按票数降序（有人要的排前）",
    [a["key"] for a in sec._sorted()] == ["res-1", "res-2"])
chk("标题显示条目数", "（2）" in sec.title.text())
# 搜索是防抖的：setText 后不应立刻重建（否则每敲一个字都重建 79 张卡）
sec.search.setText("预约2")
chk("搜索防抖：setText 后不立即重建", "（2）" in sec.title.text())
sec.rebuild()
chk("手动重建后过滤生效", "（1）" in sec.title.text())
sec.search.setText("不存在的名字")
sec.rebuild()
chk("无匹配时给出提示", "（0）" in sec.title.text())
sec.search.setText("")
sec.rebuild()

# 分页：79 条不能一次全建成 widget
many = [dict(a, key="k%d" % i, display="助手%d" % i) for i in range(30)
        for a in res[:1]]
big = launcher.ReservedSection(many)
qapp.processEvents()   # deleteLater 是延迟删除，先跑一轮事件再数
shown = sum(1 for w in big.findChildren(launcher.ReservedCard))
chk("首屏只渲染 PAGE_SIZE 张（分页）", shown == launcher.ReservedSection.PAGE_SIZE)
chk("总数仍显示在标题里", "（30）" in big.title.text())
big._show_more()
qapp.processEvents()
# 注意：deleteLater 是延迟销毁，findChildren 会同时数到新旧卡片，
# 所以这里只断言"变多了 + 分页上限提高了"，不断言精确数量（上面那个精确断言才行）
after = sum(1 for w in big.findChildren(launcher.ReservedCard))
chk("点「显示更多」后渲染更多", after > shown and big._page == 48)

# 图标缓存
_p = res[0].get("icon", "")
if _p and os.path.exists(_p):
    chk("图标缩放结果被缓存", launcher._cached_pixmap(_p) is launcher._cached_pixmap(_p))
chk("缺失图标返回 None 不抛异常", launcher._cached_pixmap("不存在的文件.png") is None)

rc = launcher.ReservedCard(res[0], votes=3, voted=False)
chk("预约卡主按钮是「我想要 +1」", "我想要" in rc.vote_btn.text())
chk("预约卡没有安装按钮", not hasattr(rc, "install_btn"))
rc2 = launcher.ReservedCard(res[0], votes=0, voted=True)
chk("已投过的按钮置灰", rc2.vote_btn.isEnabled() is False
    and rc2.vote_btn.text() == "已想要")

# ===== 总览页集成 =====
page = launcher.OverviewPage(live, cards, reserved=res)
chk("总览页带预约区", getattr(page, "reserved_section", None) is not None)
chk("总览卡片只含正式助手", len(page.overview_cards) == len(live))
chk("预约条目没有进 self.cards（不建卡）",
    page._cards is cards and "res-1" not in cards)

launcher.LAUNCHER_DIR = ORIG_DIR
shutil.rmtree(TMP, ignore_errors=True)
print("\n通过 %d / 失败 %d" % (len(OK), len(FAIL)))
