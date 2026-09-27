# -*- coding: utf-8 -*-
"""按引用裁剪 CuzhiDemo 里的引擎素材 —— 构建管线的最后一步。

## 为什么必须挂在构建里

`build_project.py` 每次都是 `rmtree(TARGET)` + `copytree(MZ:newdata)` 整棵重建，
所以在这里删掉的文件，下一次构建就会被 newdata 原样搬回来。裁剪只能作为
构建的第 7 步，而不是一次性的手工清理。

## 判据（保守优先：宁可多留，绝不错删）

1. **引擎硬编码名** —— 只存在于 js 源码里，`data/*.json` 一个字都搜不到。
   清单不写死，每次现场从 `js/rmmz_*.js` 解析 `loadSystem("X")` 与字面量
   （源码即契约；引擎换版本这里自动跟上）。
   现实例：`Window`（窗口皮肤）、`IconSet`（全部图标）、`Balloon`（气泡）、
   `States`（状态图标）、`GameOver`、`Splash`、`Shadow1/2`、`Weapons1-3`、
   `ButtonSet` —— 少一个就是某个 UI 元素默默变空白。

2. **数据引用** —— 文件名（去扩展名）作为**带引号的字符串**出现在任何
   `data/*.json` 里。引擎存素材名一律是 JSON 字符串，所以子串命中是引用的
   **超集**：可能多留（不同目录下的同名文件），但不会漏。
   多留是安全的，漏掉不是 —— 所以不用精确语义解析。

3. **图块集单独走一条路** —— 不能对 `Tilesets.json` 做子串扫描：模板里列着
   7 张图块集（World/Outside/Inside/Dungeon/SF…），扫一遍会把 61 张根本没用
   的模板图全留下（约 5.6 MB）。真正的引用链是
   `Map*.json: tilesetId → Tilesets.json[ id ].tilesetNames → img/tilesets/*.png`，
   所以这里解析 id，而不是扫名字。

只读 / 只删，不生成任何东西。`--dry` 只报数不动手。
"""

import json
import os
import re
import sys

# 只处理这两棵子树，其余（data/js/docs/…）一概不碰
ASSET_ROOTS = ("img", "audio")
# 模板里的 40 张图块集一共 61 张图，全在 tilesets/ 下
TILESET_DIR = "img/tilesets"

# 引擎硬编码清单的**下限断言**：解析失败（正则改不动了、js 被压缩了）时炸出来，
# 而不是安静地少一截。这些名字全部实测自 CuzhiDemo/js/rmmz_*.js。
MUST_FIND = {
    "system/Window", "system/IconSet", "system/Balloon", "system/States",
    "system/GameOver", "system/Splash", "system/Shadow1", "system/Shadow2",
    "system/ButtonSet", "system/Weapons1", "system/Weapons2", "system/Weapons3",
}

_re_loadsystem = re.compile(r'loadSystem\(\s*"([^"]+)"')
_re_literal = re.compile(r'["\'](?:img|audio)/([A-Za-z0-9_$.%\-/]+)["\']')


def hardcoded_names(target):
    """从引擎源码现场解析"用硬编码名字加载"的素材 → {'system/Window', ...}。

    只有 `img/` 下的有意义（audio 都是数据驱动的）；返回的是相对 img/ 的
    "目录/文件名"（无扩展名）。
    """
    sys_names, literals = set(), set()
    jsdir = os.path.join(target, "js")
    for f in sorted(os.listdir(jsdir)) if os.path.isdir(jsdir) else []:
        if not f.endswith(".js"):
            continue
        txt = open(os.path.join(jsdir, f), encoding="utf-8", errors="replace").read()
        sys_names.update(m.group(1) for m in _re_loadsystem.finditer(txt))
        literals.update(m.group(1) for m in _re_literal.finditer(txt))

    # 归一化成 "子目录/文件名"（无扩展名），与工程的相对路径对齐。
    norm = set()
    for n in sys_names:
        # 关键：loadSystem 的实参是**相对 img/system/ 的文件名**，不带目录前缀 ——
        # 源码是 `loadSystem("Window")` → `loadBitmap("img/system/", "Window")`。
        # 所以这里必须补上 system/，否则整张清单落空（会静默删掉全部 UI 素材）。
        if "/" in n:
            continue          # 极少见，按原样处理没有意义，直接跳过
        stem = os.path.splitext(n)[0]
        if stem:
            norm.add("system/" + stem)
    for n in literals:
        d, _, base = n.rpartition("/")
        # 目录前缀字面量（"img/animations/" 这种）base 为空；只收真正的文件名，
        # 且必须有扩展名 —— 否则 "img/xxx/" 会被当成一个叫 xxx 的素材。
        stem, ext = os.path.splitext(base)
        if d and stem and ext:
            norm.add(d + "/" + stem)
    missing = MUST_FIND - norm
    assert not missing, (
        "引擎硬编码清单解析残缺，缺 %s —— js 源码结构变了？"
        "此处必须炸，否则会静默删掉 UI 素材" % sorted(missing))
    return norm


def data_text(target, skip=("Tilesets.json",)):
    """data/*.json 原文拼起来（跳过 skip 里的文件名，理由见模块头注释 3）。"""
    datadir = os.path.join(target, "data")
    parts = []
    for f in sorted(os.listdir(datadir)):
        if f.endswith(".json") and f not in skip:
            parts.append(open(os.path.join(datadir, f), encoding="utf-8").read())
    # js/plugins.js 里也可能写死素材名
    pj = os.path.join(target, "js", "plugins.js")
    if os.path.isfile(pj):
        parts.append(open(pj, encoding="utf-8").read())
    return "\n".join(parts)


def used_tileset_names(target):
    """真正被地图引用的图块集图片名集合（走 tilesetId，不扫名字）。"""
    datadir = os.path.join(target, "data")
    tp = os.path.join(datadir, "Tilesets.json")
    if not os.path.isfile(tp):
        return set()
    tilesets = json.load(open(tp, encoding="utf-8"))
    ids = set()
    for f in sorted(os.listdir(datadir)):
        if not (f.startswith("Map") and f.endswith(".json")):
            continue
        if not f[3:4].isdigit():
            continue
        m = json.load(open(os.path.join(datadir, f), encoding="utf-8"))
        tid = m.get("tilesetId")
        if isinstance(tid, int) and tid > 0:
            ids.add(tid)
    names = set()
    for i in sorted(ids):
        if i < len(tilesets) and tilesets[i]:
            names.update(n for n in tilesets[i]["tilesetNames"] if n)
    return names


def _self_check(keep, ts_names):
    """裁剪前的兜底：判据一旦坏掉，宁可炸也不要交出一个被掏空的工程。

    这几条看着像废话（"保留集合非空"），但判据全是**解析**出来的：解析器坏掉
    （js 结构变了、Map 文件没落盘、正则失配）不会抛异常，只会安静地返回空集，
    然后一路删到底 —— 那就是一个"构建成功、打开全空白"的工程。
    本工程已经吃过这种"不报错但全错"的亏，所以这里主动砌一道墙。
    """
    for d in ("img/system", "img/tilesets", "img/faces", "img/characters",
              "audio/bgm", "audio/se"):
        n = sum(1 for r in keep if r.startswith(d + "/"))
        assert n, ("判据坏了：%s 一个都没保留。"
                   "（若这一版确实不用这类素材，就把 %s 从这条断言里去掉）" % (d, d))
    assert ts_names, "没解析出任何被地图引用的图块集图片 —— Map*.json 落盘了吗？"
    for r in ("img/system/Window.png", "img/system/IconSet.png"):
        assert r in keep, "%s 被判成可删 —— 引擎硬编码的判据坏了" % r


def plan(target):
    """算清"留什么、删什么"。返回 (keep, drop)。

    keep/drop 都是 {相对工程目录的 posix 路径: 理由或体积}。
    """
    hard = hardcoded_names(target)
    text = data_text(target)
    ts_names = used_tileset_names(target)
    keep, drop = {}, {}
    for kind in ASSET_ROOTS:
        base = os.path.join(target, kind)
        if not os.path.isdir(base):
            continue
        for dp, dn, fn in os.walk(base):
            for f in fn:
                p = os.path.join(dp, f)
                rel = os.path.relpath(p, target).replace("\\", "/")
                stem = os.path.splitext(f)[0]
                sub = os.path.relpath(dp, base).replace("\\", "/")
                # 图块集：只认 tilesetId 链（注释 3）
                if kind == "img" and sub == "tilesets":
                    (keep if stem in ts_names else drop)[rel] = (
                        "地图 tilesetId 引用" if stem in ts_names
                        else os.path.getsize(p))
                    continue
                # 引擎硬编码（注释 1）
                if kind == "img" and sub + "/" + stem in hard:
                    keep[rel] = "引擎硬编码"
                    continue
                # 数据引用（注释 2）
                if '"%s"' % stem in text:
                    keep[rel] = "数据引用"
                    continue
                drop[rel] = os.path.getsize(p)
    _self_check(keep, ts_names)
    return keep, drop


def prune(target, dry=False):
    """执行裁剪，返回统计 dict。"""
    keep, drop = plan(target)
    for rel in drop:
        if not dry:
            os.remove(os.path.join(target, rel))
    # 清掉空目录（删完一堆文件后 tilesets/ 之类可能空了）
    if not dry:
        for dp, dn, fn in os.walk(target, topdown=False):
            if os.path.basename(dp) in ASSET_ROOTS:
                continue
            if os.path.relpath(dp, target).replace("\\", "/").startswith(ASSET_ROOTS) \
                    and not os.listdir(dp):
                os.rmdir(dp)
    return {
        "keep": len(keep),
        "keep_bytes": sum(os.path.getsize(os.path.join(target, r)) for r in keep),
        "drop": len(drop),
        "drop_bytes": sum(drop.values()),
    }


def main():
    dry = "--dry" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    target = args[0] if args else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "CuzhiDemo")
    assert os.path.isdir(target), "找不到工程目录：%s" % target

    keep, drop = plan(target)
    print("工程：%s" % target)
    print("  保留 %4d 个  %7.2f MB" % (len(keep), sum(
        os.path.getsize(os.path.join(target, r)) for r in keep) / 1048576))
    print("  删除 %4d 个  %7.2f MB" % (len(drop), sum(drop.values()) / 1048576))
    from collections import Counter
    print("  保留原因：", dict(Counter(keep.values())))
    agg = {}
    for r, s in drop.items():
        a = agg.setdefault(os.path.dirname(r), [0, 0])
        a[0] += 1
        a[1] += s
    print("  删除构成：")
    for d in sorted(agg, key=lambda x: -agg[x][1]):
        print("      %-22s %4d 个  %7.2f MB" % (d, agg[d][0], agg[d][1] / 1048576))
    if dry:
        print("（--dry：没有真的删）")
    else:
        st = prune(target)
        print("已执行。保留 %d / 删除 %d 个（%.2f MB）"
              % (st["keep"], st["drop"], st["drop_bytes"] / 1048576))


if __name__ == "__main__":
    main()
