"""RPG Maker MZ 工程校验器 —— 生成之后立刻自查，别等打开游戏才发现崩。

检查项：
  1. 工程标识与必备数据文件齐不齐
  2. 地图数据长度是否等于 宽 x 高 x 6（MZ 是 6 层，写错必崩）
  3. 每个事件页的指令列表是否以 code 0 收尾
  4. 起始点是否落在合法地图与合法坐标上
  5. 事件引用的行走图 / 脸图 / BGM / 音效是否真实存在
  5b. 全量素材引用：事件里的 241/245/249/250 音频、地图用的图块集、标题画面图片
      —— 这三类的失效都是**静默**的，所以必须静态查。
      与 tools/prune_assets.py 配对：那边保证不多删，这边保证没缺斤。
  6. 事件指令码是否在已知集合内
  7. 道具：id 与下标是否对齐、图标索引是否越界、事件引用的道具 id 是否有定义
  8. 开关：$dataSystem.switches 是否命名、事件读写的开关 id 是否有定义、
     开关条件（111 type 0）的参数个数对不对
  9. 脸图接线：有没有哪张脸图在包里躺着却没有任何对话引用它（素材做了没接上）

用法：
    python validate_project.py <工程目录>
"""
import json
import os
import struct
import sys

REQUIRED_DATA = [
    "Actors.json", "Animations.json", "Armors.json", "Classes.json",
    "CommonEvents.json", "Enemies.json", "Items.json", "MapInfos.json",
    "Skills.json", "States.json", "System.json", "Tilesets.json",
    "Troops.json", "Weapons.json",
]

# 本校验器认识的指令码（用于拦截 LLM 编造出来的编号）
KNOWN_CODES = {
    0, 101, 102, 103, 104, 105, 108, 111, 112, 113, 115, 117, 118, 119,
    121, 122, 123, 124, 125, 126, 127, 128, 129, 131, 132, 133, 134, 135,
    136, 201, 202, 203, 204, 205, 206, 211, 212, 213, 214, 216, 217, 221,
    222, 223, 224, 225, 230, 231, 232, 233, 234, 235, 236, 241, 242, 243,
    244, 245, 246, 249, 250, 251, 261, 281, 282, 283, 284, 285, 301, 302,
    303, 311, 312, 313, 314, 315, 316, 317, 318, 319, 320, 321, 322, 323,
    324, 325, 326, 331, 332, 333, 334, 335, 336, 337, 339, 340, 351, 352,
    353, 354, 355, 356, 401, 402, 403, 404, 405, 411, 412, 413, 601, 602,
    603, 604, 605, 655,
}


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.checks = 0

    def ok(self, msg):
        self.checks += 1
        print("  [ok]   %s" % msg)

    def err(self, msg):
        self.checks += 1
        self.errors.append(msg)
        print("  [FAIL] %s" % msg)

    def warn(self, msg):
        self.warnings.append(msg)
        print("  [warn] %s" % msg)


def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def names_in(folder):
    if not os.path.isdir(folder):
        return set()
    return {os.path.splitext(f)[0] for f in os.listdir(folder)}


def main(root):
    r = Report()
    print("校验工程：%s\n" % root)

    # --- 1. 骨架 ---
    print("[1] 工程骨架")
    proj = os.path.join(root, "game.rmmzproject")
    if os.path.isfile(proj):
        r.ok("game.rmmzproject 存在 (%s)" % open(proj, encoding="utf-8").read().strip())
    else:
        r.err("缺少 game.rmmzproject —— 编辑器不会把它认成工程")

    data_dir = os.path.join(root, "data")
    for name in REQUIRED_DATA:
        if not os.path.isfile(os.path.join(data_dir, name)):
            r.err("缺少 data/%s" % name)
    if not r.errors:
        r.ok("data/ 下 %d 个必备数据文件齐全" % len(REQUIRED_DATA))

    # --- 2. 素材索引 ---
    print("\n[2] 素材索引")
    chars = names_in(os.path.join(root, "img", "characters"))
    faces = names_in(os.path.join(root, "img", "faces"))
    audio = {k: names_in(os.path.join(root, "audio", k)) for k in ["bgm", "bgs", "me", "se"]}
    r.ok("行走图 %d / 脸图 %d / BGM %d / BGS %d / ME %d / 音效 %d"
         % (len(chars), len(faces), len(audio["bgm"]), len(audio["bgs"]),
            len(audio["me"]), len(audio["se"])))

    # --- 3. System.json ---
    print("\n[3] System.json")
    sysj = jload(os.path.join(data_dir, "System.json"))
    map_infos = [m for m in jload(os.path.join(data_dir, "MapInfos.json")) if m]
    info_by_id = {m["id"]: m for m in map_infos}
    r.ok("标题=%r 起始地图=%s 起点=(%s,%s) 字体回退=%r"
         % (sysj["gameTitle"], sysj["startMapId"], sysj["startX"], sysj["startY"],
            sysj["advanced"]["fallbackFonts"]))
    if sysj["startMapId"] not in info_by_id:
        r.err("起始地图 %s 不在 MapInfos 里" % sysj["startMapId"])

    # --- 4. 逐张地图 ---
    print("\n[4] 地图")
    # 先量一遍各图尺寸：场所移动（201）的落点要拿它验。
    # 201 的落点错了**不会崩**，只会把人扔进墙里或扔出地图外，
    # 而 201 之外的传参还有 mapId —— 指到不存在的地图是一进游戏就黑屏。
    dims = {}
    portals = {}                  # 地图 -> {(x,y)}，所有「踩上去会触发」的格子
    for m in map_infos:
        p = os.path.join(data_dir, "Map%03d.json" % m["id"])
        if os.path.isfile(p):
            mp = jload(p)
            dims[m["id"]] = (mp["width"], mp["height"])
            portals[m["id"]] = {(e["x"], e["y"]) for e in mp.get("events", []) if e
                                and e["pages"][0]["trigger"] == 1
                                and e["pages"][0]["priorityType"] == 0}

    transfers = []                # (标签, 目标图, 落点x, 落点y)
    for m in map_infos:
        p = os.path.join(data_dir, "Map%03d.json" % m["id"])
        if not os.path.isfile(p):
            r.err("MapInfos 里有地图 %s，但 data/Map%03d.json 不存在" % (m["id"], m["id"]))
            continue
        mp = jload(p)
        w, h = mp["width"], mp["height"]
        if len(mp["data"]) != w * h * 6:
            r.err("地图 %s 数据长度 %d != %d*%d*6=%d"
                  % (m["id"], len(mp["data"]), w, h, w * h * 6))
        else:
            r.ok("地图 %s《%s》%dx%d，瓦片数据 %d 项（6 层校验通过）"
                 % (m["id"], m["name"], w, h, len(mp["data"])))

        # 起始点
        if m["id"] == sysj["startMapId"]:
            x, y = sysj["startX"], sysj["startY"]
            if 0 <= x < w and 0 <= y < h:
                r.ok("起始点 (%d,%d) 在地图范围内" % (x, y))
            else:
                r.err("起始点 (%d,%d) 超出地图 %dx%d" % (x, y, w, h))

        # 事件
        events = [e for e in mp.get("events", []) if e]
        r.ok("事件 %d 个" % len(events))
        for e in events:
            tag = "地图%s 事件#%s(%s)" % (m["id"], e["id"], e["name"])
            if not (0 <= e["x"] < w and 0 <= e["y"] < h):
                r.err("%s 坐标 (%d,%d) 越界" % (tag, e["x"], e["y"]))
            if not e["pages"]:
                r.err("%s 没有任何事件页" % tag)
                continue
            for pi, pg in enumerate(e["pages"]):
                lst = pg["list"]
                if not lst or lst[-1]["code"] != 0:
                    r.err("%s 第 %d 页指令列表未以 code 0 收尾" % (tag, pi))
                bad = {c["code"] for c in lst if c["code"] not in KNOWN_CODES}
                if bad:
                    r.err("%s 第 %d 页含未知指令码 %s" % (tag, pi, sorted(bad)))
                img = pg["image"]
                if img["characterName"] and img["characterName"] not in chars:
                    r.err("%s 引用了不存在的行走图 %r" % (tag, img["characterName"]))
                if img["characterName"] and not (0 <= img["characterIndex"] <= 7):
                    r.warn("%s characterIndex=%s 通常应在 0-7" % (tag, img["characterIndex"]))

            # 对话里的脸图
            for c in e["pages"][0]["list"]:
                if c["code"] == 101 and c["parameters"][0]:
                    if c["parameters"][0] not in faces:
                        r.err("%s 引用了不存在的脸图 %r" % (tag, c["parameters"][0]))

            # 场所移动 201：[0, mapId, x, y, direction, fadeType]
            for c in e["pages"][0]["list"]:
                if c["code"] != 201:
                    continue
                p = c["parameters"]
                if len(p) < 6:
                    r.err("%s 的 201 参数只有 %d 个，应为 6 个" % (tag, len(p)))
                    continue
                if p[0] != 0:
                    r.warn("%s 的 201 用变量指定坐标，无法静态校验" % tag)
                    continue
                dest = dims.get(p[1])
                if dest is None:
                    r.err("%s 的 201 指向不存在的地图 %s" % (tag, p[1]))
                elif not (0 <= p[2] < dest[0] and 0 <= p[3] < dest[1]):
                    r.err("%s 的 201 落点 (%s,%s) 超出地图 %s 的 %dx%d"
                          % (tag, p[2], p[3], p[1], dest[0], dest[1]))
                elif p[4] not in (2, 4, 6, 8):
                    r.err("%s 的 201 朝向 %s 非法（应为 2/4/6/8）" % (tag, p[4]))
                elif p[2] == e["x"] and p[3] == e["y"] and p[1] == m["id"]:
                    r.err("%s 的 201 落点就是自己这一格 —— 会来回弹" % tag)
                transfers.append((tag, p[1], p[2], p[3]))

        # 地图 BGM
        if mp.get("autoplayBgm") and mp["bgm"]["name"] not in audio["bgm"]:
            r.err("地图 %s 的 BGM %r 不存在" % (m["id"], mp["bgm"]["name"]))

    # --- 4b. 传送落点交叉校验 ---
    # 落点踩在**另一张图的传送格**上 = 落地即被弹走，两张图之间来回弹，玩家出不来。
    # 这是跨地图的错，单看一张图永远看不出来，所以放在这里单独查。
    print("\n[4b] 传送落点")
    if not transfers:
        r.ok("本工程还没有场所移动（201）")
    for tag, tmid, tx, ty in transfers:
        if (tx, ty) in portals.get(tmid, ()):
            r.err("%s 落到地图 %s 的 (%d,%d)，而那格本身是传送格 —— 会来回弹"
                  % (tag, tmid, tx, ty))
    if transfers and not r.errors:
        r.ok("%d 处传送的落点都在空地上（不落在任何传送格上）" % len(transfers))

    # --- 5. 术语与系统音效 ---
    print("\n[5] 系统项")
    sys_audio = {
        "titleBgm": "bgm", "battleBgm": "bgm",
        "gameoverMe": "me", "defeatMe": "me", "victoryMe": "me",
    }
    for key, folder in sys_audio.items():
        nm = sysj.get(key, {}).get("name")
        if nm and nm not in audio[folder]:
            r.err("System.json 的 %s 引用 %s/%r 不存在" % (key, folder, nm))
    sounds = sysj.get("sounds") or []
    if isinstance(sounds, dict):
        sounds = list(sounds.values())
    for i, snd in enumerate(sounds):
        nm = (snd or {}).get("name")
        if nm and nm not in audio["se"]:
            r.err("System.json 的 sounds[%d] 引用 se/%r 不存在" % (i, nm))
    r.ok("系统音频引用检查完毕")

    # --- 5b. 全量素材引用 ---
    # [5] 只查了 System.json 的五个字段。剩下的引用 —— 事件里的 BGM/BGS/ME/SE、
    # 地图用的图块集、标题画面 —— 此前**没有任何静态校验兜着**，而它们的失效
    # 全是静默的：MZ 的音频加载失败不报错（XHR 404 直接吞掉），图块集缺图只是
    # 画不出来。这一类"不报错但全错"正是本工程反复吃亏的地方。
    #
    # 这一节和 tools/prune_assets.py 是一对，合起来才是完整证明：
    #   prune 保证「保留集合 ⊇ 数据里出现过的所有名字」，这一节保证
    #   「数据里引用到的每个名字都真的有文件」—— 于是裁剪不可能删掉要用的东西。
    # 两边故意用**不同的办法**判同一件事（prune 扫字符串、这里做语义解析），
    # 免得同一种解析错误在两边同时发生、互相作证。
    print("\n[5b] 全量素材引用")
    tileset_imgs = names_in(os.path.join(root, "img", "tilesets"))
    titles1 = names_in(os.path.join(root, "img", "titles1"))
    titles2 = names_in(os.path.join(root, "img", "titles2"))
    dir_of_code = {241: "bgm", 245: "bgs", 249: "me", 250: "se"}
    stat = {"n": 0, "miss": 0}

    def scan_audio(lst, where):
        for i, c in enumerate(lst):
            folder = dir_of_code.get(c["code"])
            if not folder:
                continue
            audio_obj = c["parameters"][0] if c["parameters"] else None
            nm = (audio_obj or {}).get("name") if isinstance(audio_obj, dict) else None
            stat["n"] += 1
            if nm and nm not in audio[folder]:
                stat["miss"] += 1
                r.err("%s 第 %d 条(code %d) 播放 %s/%r，但 audio/%s/ 下没有这个文件"
                      % (where, i, c["code"], folder, nm, folder))

    tilesets = jload(os.path.join(data_dir, "Tilesets.json"))
    n_ts = 0
    for f in sorted(os.listdir(data_dir)):
        if not (f.startswith("Map") and f[3:4].isdigit()):
            continue
        mp = jload(os.path.join(data_dir, f))
        mtag = "地图 %s" % f[3:6].lstrip("0")
        for e in [x for x in mp.get("events", []) if x]:
            for pi, pg in enumerate(e["pages"]):
                scan_audio(pg["list"],
                           "%s 事件#%s(%s) 第%d页" % (mtag, e["id"], e["name"], pi))
        tid = mp.get("tilesetId")
        if not isinstance(tid, int) or tid <= 0:
            r.err("%s 的 tilesetId=%r 非法" % (mtag, tid))
            continue
        if tid >= len(tilesets) or not tilesets[tid]:
            r.err("%s 用图块集 id=%d，Tilesets.json 里没有这一条" % (mtag, tid))
            continue
        for nm in tilesets[tid]["tilesetNames"]:
            if not nm:
                continue
            n_ts += 1
            if nm not in tileset_imgs:
                stat["miss"] += 1
                r.err("%s 用的图块集《%s》缺图 img/tilesets/%s.png"
                      % (mtag, tilesets[tid]["name"], nm))

    n_pic = 0
    for key, folder, pool in (("title1Name", "titles1", titles1),
                              ("title2Name", "titles2", titles2)):
        nm = sysj.get(key)
        if not nm:
            continue
        n_pic += 1
        if nm not in pool:
            stat["miss"] += 1
            r.err("System.json 的 %s=%r 在 img/%s/ 下找不到" % (key, nm, folder))

    print("      事件音频 %d 条、图块集 %d 张、标题图 %d 项"
          % (stat["n"], n_ts, n_pic))
    if not stat["miss"]:
        r.ok("数据引用到的 %d 项素材全部存在（音频/图块集/标题图）"
             % (stat["n"] + n_ts + n_pic))

    # --- 6. 道具 ---
    # 这一节的每一个检查，对应都是一种**静默失败**：
    #   $dataItems[未定义 id] 不报错 —— hasItem(undefined) 恒 false（条件永远走 else），
    #   gainItem(undefined) 里 itemContainer 返回 null 直接跳过（给了没给）。
    #   于是「条件分支 + 给道具」写错了，表现是剧情整个走岔，一句错都不报。
    #   iconIndex 越界同理：不报错，只是菜单里画不出图标。
    print("\n[6] 道具")
    items = jload(os.path.join(data_dir, "Items.json"))
    n_icon = 0
    iconset = os.path.join(root, "img", "system", "IconSet.png")
    if os.path.isfile(iconset):
        with open(iconset, "rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            iw, ih = struct.unpack(">II", head[16:24])
            n_icon = (iw // 32) * (ih // 32)
    defined = {}
    for i, it in enumerate(items):
        if not it:
            continue
        if it.get("id") != i:
            r.err("Items.json 第 %d 项声明 id=%s —— 引擎按 id 取 $dataItems，必须对齐"
                  % (i, it.get("id")))
        if it.get("itypeId") not in (1, 2):
            r.err("道具 %r 的 itypeId=%s 非法（1=通常物品 2=关键物品）"
                  % (it.get("name"), it.get("itypeId")))
        if n_icon and not (0 <= it.get("iconIndex", 0) < n_icon):
            r.err("道具 %r 的 iconIndex=%s 超出 IconSet 的 %d 格"
                  % (it.get("name"), it.get("iconIndex"), n_icon))
        defined[i] = it.get("name")

    # 事件真正引用到的道具 id（111 条件 type 8 / 126 增减）必须真的有定义。
    missing = {}
    for m in map_infos:
        p = os.path.join(data_dir, "Map%03d.json" % m["id"])
        if not os.path.isfile(p):
            continue
        for e in [x for x in jload(p).get("events", []) if x]:
            for c in e["pages"][0]["list"]:
                iid = None
                if c["code"] == 111 and c["parameters"][0] == 8:
                    iid = c["parameters"][1]
                elif c["code"] == 126:
                    iid = c["parameters"][0]
                if iid is not None and iid not in defined:
                    missing.setdefault(iid, []).append(
                        "地图%s#%s(%s)" % (m["id"], e["id"], e["name"]))
    for iid, where in sorted(missing.items()):
        r.err("事件引用了不存在的道具 id=%s —— %s（条件会永远走 else / 给了等于没给）"
              % (iid, "、".join(where)))
    if defined and not missing:
        r.ok("道具 %d 件、id 与下标对齐、图标索引在范围内；事件引用的 id 全部有定义"
             % len(defined))
    elif not defined:
        r.warn("Items.json 里一件道具都没有")

    # --- 7. 全局开关 ---
    # 跟道具同一类静默失败：`$gameSwitches.setValue(未定义 id, true)` 照写不误，
    # 而 `value(未定义 id)` 读回来恒 false —— 于是「开关永远打不开」，
    # 在剧情上的表现就是某个分支永远进不去，一句错都不报。
    #
    # 另外这里专门查一个**参数个数**：111 的开关条件（type 0）是三个参数，
    # 第三位是"判开还是判关"（`value(id) === (params[2] === 0)`）。
    # 只写两个的话 params[2] 是 undefined，`undefined === 0` 为假 ——
    # 条件永远判"关"，同样不报错。道具条件（type 8）反而是两个参数，别顺手抄。
    print("\n[7] 全局开关")
    sw_table = sysj.get("switches") or []
    named = {i: n for i, n in enumerate(sw_table) if n}
    if named:
        r.ok("$dataSystem.switches 共 %d 条，已命名 %d 个：%s"
             % (len(sw_table), len(named),
                "、".join("%d=%s" % (i, n) for i, n in sorted(named.items()))))
    else:
        r.warn("$dataSystem.switches 里一个开关都没命名")

    missing_sw, bad_arity = {}, {}
    for m in map_infos:
        p = os.path.join(data_dir, "Map%03d.json" % m["id"])
        if not os.path.isfile(p):
            continue
        for e in [x for x in jload(p).get("events", []) if x]:
            tag = "地图%s#%s(%s)" % (m["id"], e["id"], e["name"])
            for c in e["pages"][0]["list"]:
                ids = []
                if c["code"] == 121:
                    ids = list(range(c["parameters"][0], c["parameters"][1] + 1))
                elif c["code"] == 111 and c["parameters"][0] == 0:
                    if len(c["parameters"]) < 3:
                        bad_arity.setdefault(tag, []).append(
                            "111 开关条件只有 %d 个参数" % len(c["parameters"]))
                        continue
                    ids = [c["parameters"][1]]
                for i in ids:
                    if i not in named:
                        missing_sw.setdefault(i, []).append(tag)
    for i, where in sorted(missing_sw.items()):
        r.err("事件读写了没有命名的开关 id=%s —— %s（条件会永远走 else）"
              % (i, "、".join(sorted(set(where)))))
    for tag, what in sorted(bad_arity.items()):
        r.err("%s 的 %s —— 引擎会拿 undefined 比 0，条件永远为假" % (tag, what[0]))
    if named and not missing_sw and not bad_arity:
        r.ok("事件引用的开关 id 全部有命名，且开关条件参数个数正确")

    # --- 8. 脸图接线 ---
    # 第 5 节已经查过"引用了不存在的脸图"，这里查**反面**：
    # 脸图文件在包里躺着，却没有任何一处对话引用它 —— 也就是「素材做出来了没接上」。
    # 2026-09-24 就是这么被骗的：M4 三条事件的脸图位写成了文件名短名（"Zai"/"Guard"），
    # 构建时查不到就静默退化成"不显示脸图"，于是新画的宰那张**白做了**，
    # 而第 5 节一个字都没报（空脸图名是合法的）。
    # 现在构建期已经会当场炸（build_project.face_file），这条是二道防线：
    # 它不依赖数据层，只看最终产物，能抓住任何原因造成的"图没接上"。
    #
    # 只盯 **144x144** 的，因为那是本工程自己做的脸图的规格（`import_faces.compose` 的
    # 产物）。img/faces/ 里另外两批都刻意排除：MZ 模板自带的 16 张整表（Actor1…SF_People1）
    # 和库存包剩下的那两张 576x288 整表（ChengQi 成妻 / HatMan，卡通八格表情表）——
    # 把它们都算孤儿，会一次刷出十几条警告，警告一多就没人看了。
    # **代价**：576x288 的老素材漏接查不出来（成妻那张就是这种：三处对话在用它，
    # 但真要漏接也报不出来）。成名原本也在这批里，2026-09-24 换成 144x144 后就归本管线管了。
    #
    # 引用**不止对话这一条路**：`Actors.json` 的 faceName 也算 —— 菜单状态栏画的就是它。
    # 只数 101 的话，主角那张脸图一入库就会被误报成孤儿（2026-09-24 成名入库时踩到，
    # 他全篇没有一句台词，因为玩家就是他）。误报比漏报更坏：警告一假，真警告就没人信了。
    print("\n[8] 脸图接线")
    used_faces, n_101 = set(), 0
    for m in map_infos:
        p = os.path.join(data_dir, "Map%03d.json" % m["id"])
        if not os.path.isfile(p):
            continue
        for e in [x for x in jload(p).get("events", []) if x]:
            for c in e["pages"][0]["list"]:
                if c["code"] == 101:
                    n_101 += 1
                    if c["parameters"][0]:
                        used_faces.add(c["parameters"][0])
    n_actor = 0
    for a in jload(os.path.join(data_dir, "Actors.json"))[1:]:
        if a and a.get("faceName"):
            used_faces.add(a["faceName"])
            n_actor += 1
    orphan = []
    for f in sorted(os.listdir(os.path.join(root, "img", "faces"))):
        if os.path.splitext(f)[0] in used_faces:
            continue
        with open(os.path.join(root, "img", "faces", f), "rb") as fp:
            head = fp.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            continue
        if struct.unpack(">II", head[16:24]) == (144, 144):
            orphan.append(os.path.splitext(f)[0])
    r.ok("%d 处对话 + %d 条 Actors.faceName 共用到 %d 张脸图"
         % (n_101, n_actor, len(used_faces)))
    for f in orphan:
        r.warn("脸图 %r（144x144，是这条管线画的）在包里但没有任何对话或状态栏引用它 —— "
               "多半是 NPC 事件的脸图位填空了，或填成了文件名短名" % f)

    # --- 汇总 ---
    print("\n" + "=" * 46)
    if r.errors:
        print("结果： FAIL —— %d 项错误 / %d 项检查" % (len(r.errors), r.checks))
        for e in r.errors:
            print("   - %s" % e)
        return 1
    print("结果： PASS —— %d 项检查全部通过，%d 条提示" % (r.checks, len(r.warnings)))
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        r"C:\Users\lenovo\WorkBuddy\2026-09-22-19-16-43\rpgmaker-ai-pipeline", "CuzhiDemo"
    )
    sys.exit(main(target))
