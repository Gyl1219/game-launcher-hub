# -*- coding: utf-8 -*-
"""版本检查缓存（stale-while-revalidate）契约测试。"""
import json
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LAUNCHER_TELEMETRY_NOASK", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import launcher  # noqa: E402

fails = []


def chk(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


tmp = tempfile.mkdtemp(prefix="vcache_")
cache = os.path.join(tmp, "versions-ok-ww.json")

print("--- 1) 读缓存：正常 / 缺失 / 损坏 ---")
items = [{"version": "v3.7.14", "update_note": ["x"]},
         {"version": "v3.7.13", "update_note": []}]
with open(cache, "w", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False)
got, age = launcher._read_version_cache(cache)
chk("正常缓存读回 items", got == items, got)
chk("age 接近 0（刚写入）", age is not None and age < 5, age)

got2, age2 = launcher._read_version_cache(os.path.join(tmp, "missing.json"))
chk("缺失文件 → (None, None)", got2 is None and age2 is None)

with open(cache, "w", encoding="utf-8") as f:
    f.write("{broken")
got3, age3 = launcher._read_version_cache(cache)
chk("损坏 JSON → (None, None)", got3 is None and age3 is None)

print("\n--- 2) age 随写入时间增长（限频判断依据）---")
# 上一组把 cache 写坏过，重写回正常内容再调 mtime
with open(cache, "w", encoding="utf-8") as f:
    json.dump(items, f, ensure_ascii=False)
old = time.time() - 3600
os.utime(cache, (old, old))
got4, age4 = launcher._read_version_cache(cache)
chk("一小时前的缓存 age ≈ 3600（超过 30 分钟 TTL）",
    got4 == items and 3500 < age4 < 3700, age4)

print("\n--- 3) 路径规则 ---")
p = launcher._version_cache_path("ok-ww")
chk("缓存路径在 logs/ 下", os.path.basename(os.path.dirname(p)) == "logs"
    and os.path.basename(p) == "versions-ok-ww.json", p)

print("\n%d failed" % len(fails))
sys.exit(1 if fails else 0)
