# -*- coding: utf-8 -*-
"""引擎契约校验：扫 js/*.js 里对 $dataSystem 的解引用，反查 System.json 是否齐备。

为什么需要它
------------
官方 newdata 模板的 System.json 缺 `advanced.windowOpacity`，而引擎
`Game_System.prototype.windowOpacity()` 是 `return $dataSystem.advanced.windowOpacity;`
——零兜底。手搓工程不补这个字段，一进标题画面就
`TypeError: Cannot read properties of undefined (reading 'clamp')`，
而且报错只指向 `Window.set backOpacity`，完全不提缺哪个字段。

这类错的性质是：**引擎把数据当契约。** 所以把引擎源码当作 schema 的唯一真相。

判定规则（按引擎真实写法分三档）
--------------------------------
1. **有 `in` 守卫** —— 引擎写作
   `if ("screenScale" in $dataSystem.advanced) { return $dataSystem.advanced.screenScale; }`
   缺字段时走 else 分支拿默认值。**安全**，不计。
2. **布尔/哨兵语义** —— `optXxx` / `hasXxx` / `encryptionKey`，只用作条件判断，
   缺了等于 false。**安全**，不计。
3. **裸引用** —— 其余全部计入。这一档才是会崩的，`advanced.windowOpacity` 是实例。

用法
----
    python check_system_contract.py <工程目录>
"""
import json
import os
import re
import sys

RE_ADV = re.compile(r"\$dataSystem\.advanced\.([A-Za-z_]\w*)")
RE_TOP = re.compile(r"\$dataSystem\.([A-Za-z_]\w*)(?![.\w])")
# 引擎的守卫写法：if ("xxx" in $dataSystem[.advanced])
RE_GUARD_ADV = re.compile(r'"(\w+)"\s+in\s+\$dataSystem\.advanced')
RE_GUARD_TOP = re.compile(r'"(\w+)"\s+in\s+\$dataSystem(?!\.)')

# 引擎内部变量，不是 System.json 字段
RESERVED = {"advanced", "loadDataFile", "onLoad", "makeDataFileName"}
# 只作条件判断的字段，缺了等价于 false
OPTIONAL_RE = re.compile(r"^(opt[A-Z]|has[A-Z])|^encryptionKey$")


def scan(js_dir):
    guarded_adv, guarded_top = set(), set()
    refs = {}
    for fn in sorted(os.listdir(js_dir)):
        if not fn.endswith(".js"):
            continue
        with open(os.path.join(js_dir, fn), encoding="utf-8", errors="ignore") as f:
            for lineno, line in enumerate(f, 1):
                if line.strip().startswith("//"):
                    continue
                guarded_adv |= set(RE_GUARD_ADV.findall(line))
                guarded_top |= set(RE_GUARD_TOP.findall(line))
                for scope, name in _refs(line):
                    key = ("advanced." + name) if scope == "adv" else name
                    refs.setdefault(key, "%s:%d" % (fn, lineno))
    return refs, guarded_adv, guarded_top


def _refs(line):
    for m in RE_ADV.finditer(line):
        yield "adv", m.group(1)
    cleaned = RE_ADV.sub("", line)
    for m in RE_TOP.finditer(cleaned):
        if m.group(1) not in RESERVED:
            yield "top", m.group(1)


def classify(key, guarded_adv, guarded_top):
    if key.startswith("advanced."):
        name = key.split(".", 1)[1]
        if name in guarded_adv or OPTIONAL_RE.match(name):
            return "safe"
    elif key in guarded_top or OPTIONAL_RE.match(key):
        return "safe"
    return "fatal"


def main():
    if len(sys.argv) < 2:
        print("用法: python check_system_contract.py <工程目录>")
        return 2
    root = os.path.abspath(sys.argv[1])
    js_dir = os.path.join(root, "js")
    sys_path = os.path.join(root, "data", "System.json")
    for p in (js_dir, sys_path):
        if not os.path.exists(p):
            print("找不到: %s" % p)
            return 2

    data = json.load(open(sys_path, encoding="utf-8"))
    adv = data.get("advanced") if isinstance(data.get("advanced"), dict) else {}
    refs, g_adv, g_top = scan(js_dir)

    fatal, safe_present, missing_guarded = [], 0, []
    for key, where in sorted(refs.items()):
        exists = (key.split(".", 1)[1] in adv) if key.startswith("advanced.") else (key in data)
        if classify(key, g_adv, g_top) == "safe":
            if exists:
                safe_present += 1
            else:
                missing_guarded.append((key, where))
            continue
        if not exists:
            fatal.append((key, where))

    print("引擎解引用 $dataSystem 字段 %d 个" % len(refs))
    print("  有守卫/有兜底 : %d 个（其中 %d 个未填，引擎会走默认值）"
          % (safe_present + len(missing_guarded), len(missing_guarded)))
    print("  裸引用        : %d 个" % (safe_present + len(fatal)))
    print()
    if missing_guarded:
        print("未填但安全（引擎有 else 分支或仅作判断）：")
        for k, w in missing_guarded:
            print("   %-26s %s" % (k, w))
        print()
    if fatal:
        print("裸引用且缺失 —— 会崩：")
        for k, w in fatal:
            print("   %-26s 引擎用法首见 %s" % (k, w))
        return 1
    print("PASS — 引擎无守卫解引用的字段全部就位。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
