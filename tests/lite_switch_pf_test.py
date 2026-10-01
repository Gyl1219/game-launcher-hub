import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import launcher
from PySide6.QtWidgets import QApplication
qapp = QApplication(sys.argv)

fails = []
def chk(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)

app = [a for a in launcher.APPS if a.get("key") == "whimbox"][0]
exe = app["exe"]
print("exe =", exe)
chk("指向正版 Program Files", "Program Files" in exe and os.path.isfile(exe))

fe = launcher._exe_file_version(exe)
be = launcher._lite_backend_version(app)
print("前端(FileVersion) =", fe, "| 后端 =", repr(be))
chk("前端读到 2.4.7", fe == "2.4.7")
# 后端是会随用户更新变化的活数据（2026-10-02 已真实落盘 D 盘内嵌，曾经装在 C 盘用户目录），
# 断言不写死版本号，只要求「识别到了真实安装」
chk("后端识别到真实安装(D盘内嵌)", be != "")
print("   (当前后端实测 =", repr(be), ")")

card = launcher.AppCard(app)
card._rebuild_lite_body()
chk("卡片判已安装", card._installed)
chk("徽章显示 2.4.7", card.ver_tag.text() == "2.4.7")
chk("ver_hint 含 前端 2.4.7", "前端 2.4.7" in card.ver_hint.text())

# 模拟"检查成功"后选 2.4.7：应只下 whl 不动前端（fe 已是 2.4.7）
card._on_lite_check_done({
    "tag": "2.4.7", "exe": "https://x/setup.exe", "whl": "https://x/whimbox-2.4.7-py3-none-any.whl",
    "body": "", "versions": [{"tag": "2.4.7", "exe": "https://x/setup.exe",
                              "whl": "https://x/whimbox-2.4.7-py3-none-any.whl"}],
})
sel, exe_u, whl_u, fe_tag = getattr(card, "_lite_selected", ("", "", "", ""))
print("_lite_selected =", (sel, fe_tag), "| whl_u =", whl_u)
chk("选中 2.4.7 且前端来源=2.4.7", sel == "2.4.7" and fe_tag == "2.4.7")
chk("后端 whl 指向 2.4.7", "2.4.7" in whl_u)
btn = card.update_btn.text()
print("更新按钮 =", btn)
# 按钮方向必须与后端实际版本一致：选 2.4.7 → 相同=已是最新 / 实际更高=降级 / 实际更低=更新
_d = launcher.compare_version(launcher._normalize_tag("2.4.7"),
                              launcher._normalize_tag(be or "0"))
_want = ("已是最新" if _d == 0 else
         ("更新后端到 2.4.7" if _d > 0 else "降级后端到 2.4.7"))
chk("按钮方向与后端实际版本一致(期望含『%s』)" % _want, _want in btn)

# 启动路径计算
cap = {}
def fake_run(parent, exe_, args=None, cwd=None, need_admin=False, show_errors=True):
    cap["exe"] = exe_; cap["cwd"] = cwd; return True
orig = launcher.run_exe; launcher.run_exe = fake_run
card.launch_app(); launcher.run_exe = orig
chk("启动目标=正版 exe", cap.get("exe") == exe)
chk("cwd=正版安装目录", cap.get("cwd") == os.path.dirname(exe))

# 后端安装会用正版的 python-embedded
py = os.path.join(os.path.dirname(exe), "python-embedded", "python.exe")
chk("后端 pip 用的 python 存在", os.path.isfile(py))

print("\n%d failed" % len(fails))
sys.exit(1 if fails else 0)
