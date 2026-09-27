# -*- coding: utf-8 -*-
"""促织 —— 工程构建器（模板层）

把 tools/game_data.py 里的内容数据翻译成 RPG Maker MZ 的工程 JSON。

设计上分两层，就是为了让「内容」和「引擎细节」互不污染：
  game_data.py     剧本级的东西：地图长什么样、谁说什么话
  build_project.py 引擎级的东西：JSON 形状、tileId 换算、通行度位、字段补丁

用法：
    python tools/build_project.py
前置：
    python tools/build_tiles.py     （产出 assets/img/tilesets + build/tiles_manifest.json）
"""
import json
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import game_data as G
import prune_assets as P
from build_tiles import cell_of      # 仅用于渲染自检，不参与写盘

MZ = r"D:\Steam\steamapps\common\RPG Maker MZ"
TEMPLATE = os.path.join(MZ, "newdata")
TARGET = os.path.join(ROOT, "CuzhiDemo")
ASSETS = os.path.join(ROOT, "assets")
MANIFEST = os.path.join(ROOT, "build", "tiles_manifest.json")

# assets/ 下不进游戏包的子目录。参照图只服务于「出需求单」，引擎不读。
NO_SHIP = {"portraits"}

TILESET_ID = 7
TILE_ID_MAX = 8192
# 通行度位（源头 rmmz_objects.js Game_Map.checkPassage / Tilemap._isHigherTile）：
#   0x01 下 0x02 左 0x04 右 0x08 上（置位 = 该方向被挡）
#   0x10 星标：画在角色之上，且**跳过通行判定**（所以绝不要给要挡路的东西加星标）
#   0x20 梯子  0x40 草丛（减速）  0x80 柜台
#   0x100 以上是地形标记，本工程不用 -> 一律 0
BLOCK_ALL = 0x0F
STAR = 0x10


def jload(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def jdump(p, obj):
    """按 MZ 自己的写法落盘：单行、不转义非 ASCII、紧凑分隔符。"""
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


# ------------------------------------------------------------------ 图块集
def load_manifest():
    man = jload(MANIFEST)
    tex = {}
    for t in man["textures"]:
        assert len(t["tile_ids"]) == 16, t["name"]
        tex[t["name"]] = [t["tile_ids"][j * 4:j * 4 + 4] for j in range(4)]   # 4x4
    obj = {o["name"]: o for o in man["objects"]}
    return tex, obj


def install_tileset():
    """把 Ming_*.png 复制进工程，并在 Tilesets.json 里登记一个新图块集。

    两个必须遵守的引擎契约（都是踩出来的）：

    一、`$dataTilesets` **按 id 对齐下标**：`[null, id1, id2, ...]`。
        引擎取图用的是 `$dataTilesets[this._mapData.tilesetId]`，
        所以新建的图块集必须落在 `[id]` 那个位置上，不能只是 append。
        （append 过一版：$dataTilesets[7] 是 undefined，flags 全 undefined，
        判定一律落到「可通行」—— 墙全都能穿过去，而且不报任何错。）

    二、`flags[0]` 必须是 **0x10 星标**。
        Game_Map.allTiles() 会把**空图层的 tileId 0 也塞进判定列表**，
        而 layeredTiles() 是 z3 -> z0 降序，所以 0 排在最前面：
          flags[0] = 0x00 -> 第一个 tile 就返回「可通行」，墙形同虚设
          flags[0] = 0x0F -> 每个格子都不可通行，人一步都走不了
        0x10 的语义是「跳过，不影响通行判定」，循环才会继续走到真正的墙。
        官方模板里 flags[0] 就是 16，不是巧合。

    flags 长度必须 8192（= TILE_ID_MAX），索引即 tileId：
      * B/C/D/E 号段 0..1023 默认**全部阻挡** —— 里面装的是物件和墙面、屋顶
      * A5 号段 1536..1663 保持 0 = 可通行 —— 里面装的是地面
    默认全挡、地面显式放开，比反过来安全：漏配一格最多是走不过去，
    反过来就是穿墙。
    """
    src = os.path.join(ASSETS, "img", "tilesets")
    dst = os.path.join(TARGET, "img", "tilesets")
    os.makedirs(dst, exist_ok=True)
    names = ["Ming_A1", "Ming_A2", "Ming_A3", "Ming_A4",
             "Ming_A5", "Ming_B", "Ming_C", "Ming_D", "Ming_E"]
    for n in names:
        p = os.path.join(src, n + ".png")
        assert os.path.exists(p), "缺图块集：%s（先跑 tools/build_tiles.py）" % p
        shutil.copyfile(p, os.path.join(dst, n + ".png"))

    tp = os.path.join(TARGET, "data", "Tilesets.json")
    by_id = {t["id"]: t for t in jload(tp) if t}
    flags = [0] * TILE_ID_MAX            # 默认全放行，再显式挡上该挡的
    for i in range(1024):                # B/C/D/E 段：物件与墙面屋顶都在这
        flags[i] = BLOCK_ALL
    flags[0] = STAR                      # 空图层的占位 id，必须「不影响判定」
    # 1536..1663 是 A5 地面段，保持 0 = 可通行；2048+ 是 A1..A4 透明占位，也留 0

    # 高物件的上半身标星：画到角色之上，且跳过通行判定。
    # 于是「树干一行挡路、树冠几行可穿且盖住玩家」，走到树后面才是对的。
    star = set(jload(MANIFEST).get("star_ids", []))
    for i in star:
        flags[i] = STAR
    by_id[TILESET_ID] = {
        "id": TILESET_ID,
        "mode": 1,
        "name": G.TILESET_NAME,
        "note": "",
        "tilesetNames": names + [""],
        "flags": flags,
    }
    top = max(by_id)
    ts = [None] + [by_id.get(i) for i in range(1, top + 1)]     # 下标 == id
    assert len(ts) - 1 == top and ts[TILESET_ID]["name"] == G.TILESET_NAME
    jdump(tp, ts)
    return len(names), sum(1 for f in flags if f == BLOCK_ALL)


# ------------------------------------------------------------------ 素材契约
def png_size(path):
    """只读 PNG 头取宽高。用 stdlib 而不是 PIL —— 构建器不该为一件小事多背一个依赖。"""
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", "不是 PNG：%s" % path
    return struct.unpack(">II", head[16:24])


def check_cast_assets():
    """CAST 里的每个文件都得满足引擎的取格契约 —— 尺寸不对引擎**不报错**，
    只是静默画不出来或画出半张脸，等真机看到才发现就晚了。

    行走图：`$` 前缀 = 单角色，引擎按 3 列 x 4 行切、单帧 48px -> 必须 144x192。
    脸图：本工程 System.json 没有 faceSize，恒 144；对话索引恒 0 ->
          引擎 crop(0,0,144,144)，所以图**必须 >= 144x144**（小了 drawImage 直接裁空）。
          老素材是 576x288 满表，取第 0 格正好是正脸，同样合法。
    """
    n_face = 0
    for name, (walk, face, _hint) in G.CAST.items():
        wp = os.path.join(TARGET, "img", "characters", walk + ".png")
        assert os.path.exists(wp), "行走图缺：%s（角色 %s）" % (wp, name)
        assert png_size(wp) == (144, 192), \
            "%s.png 必须 144x192（3 列 x 4 行），实为 %s" % (walk, png_size(wp))
        if not face:                     # None = 待画，"" = 明确不配（癞头蟆）
            continue
        fp = os.path.join(TARGET, "img", "faces", face + ".png")
        assert os.path.exists(fp), "脸图缺：%s（角色 %s）" % (fp, name)
        w, h = png_size(fp)
        assert w >= 144 and h >= 144, \
            "%s.png 至少 144x144，实为 %dx%d —— 小了对话里画不出来" % (face, w, h)
        n_face += 1
    return len(G.CAST), n_face


# ------------------------------------------------------------------ 界面术语
def install_title_bg(sj):
    """写 $dataSystem.title1Name，并守住「正好 816x624」这条契约。

    引擎 Graphics 取标题背景是 max(816/宽, 624/高, 1.0) 缩放后居中：
    给大了会被缩小、给小了会被放大并裁掉四边，两种都不报错，只是构图悄悄变样。
    所以尺寸必须在这里 assert 住 —— 这是全工程唯一会「默默变丑」的素材契约。
    """
    if not G.TITLE_BG:
        return None
    rel = os.path.join("img", "titles1", G.TITLE_BG + ".png")
    p = os.path.join(TARGET, rel)
    assert os.path.exists(p), "标题背景缺：%s（先跑 tools/import_refs.py）" % p
    assert png_size(p) == (816, 624), \
        "标题背景必须正好 816x624，实为 %s —— 不然引擎会缩放并裁边" % (png_size(p),)
    sj["title1Name"] = G.TITLE_BG
    return rel


def patch_terms(sj):
    """把 $dataSystem.terms 里的英文按索引换成中文，返回改了几条。

    为什么按索引改：引擎用固定下标取词（commands[18]=New Game、[19]=Continue、
    [11]=Options，见 rmmz_managers.js:1662-1685）。整表替换一旦少一个元素，
    后面全体错位 —— 且不报错，只是词全串了。索引覆盖最多漏翻，不会串。
    """
    n = 0
    for key, table, override in (("commands", sj["terms"]["commands"], G.TERMS_COMMANDS),
                                 ("basic", sj["terms"]["basic"], G.TERMS_BASIC),
                                 ("params", sj["terms"]["params"], G.TERMS_PARAMS)):
        for i, text in override.items():
            assert i < len(table), \
                "terms.%s 只有 %d 条，却要改第 %d 条 —— MZ 模板换版本了" % (key, len(table), i)
            if table[i] != text:
                table[i] = text
                n += 1
    for k, text in G.TERMS_MESSAGES.items():
        assert k in sj["terms"]["messages"], "terms.messages 没有 %s 这个键" % k
        if sj["terms"]["messages"][k] != text:
            sj["terms"]["messages"][k] = text
            n += 1
    return n


# ------------------------------------------------------------------ 地图
def blank_map():
    """一张空地图的字段骨架 —— 照模板的 Map001.json 抄，不写死字段名。

    硬编码字段清单的写法会在引擎换版本时静静失效（少一个字段 = 编辑器能开、运行时缺项），
    抄模板则永远跟引擎同步。只清掉两张跟内容绑定的表：data（瓦片）与 events。
    """
    m = jload(os.path.join(TEMPLATE, "data", "Map001.json"))
    m["data"] = []
    m["events"] = [None]
    return m


def paint(mapdef, tex, obj):
    """ASCII -> Map00N.json 的 data 数组 + events 列表

    data 的索引公式（源头 rmmz_core.js Tilemap._readMapData）：
        index = (z * height + y) * width + x
    即 z 最外层、y 次之、x 最内 —— 不是「按格存 6 层」，是「按层存整张图」。
    """
    rows = mapdef["rows"]
    h = len(rows)
    w = mapdef["width"]
    # 宽度取**数据里声明的那个**，不是 rows[0] 的长度。
    # 取 rows[0] 的话，「整行少打一个字符」会被当成新的标准宽度，一路静静地放过去 ——
    # 症状是地图右边缺一条、物件越界报一堆看不懂的错。声明 + assert 才是真防线。
    for y, r in enumerate(rows):
        assert len(r) == w, "地图第 %d 行长度 %d != 声明的 %d" % (y, len(r), w)
    data = [0] * (w * h * 6)

    def put(z, x, y, tid):
        data[(z * h + y) * w + x] = tid

    for y, r in enumerate(rows):
        for x, ch in enumerate(r):
            assert ch in G.LEGEND, "第 %d 行第 %d 列有未定义的字符 %r" % (y, x, ch)
            floor_tex, over_tex, _ = G.LEGEND[ch]
            put(0, x, y, tex[G.TEX[floor_tex]][y % 4][x % 4])
            if over_tex:
                put(1, x, y, tex[G.TEX[over_tex]][y % 4][x % 4])

    # 物件：数据给的是底边中心格，换算成整格盒的左上角
    covered = set()                  # 被物件画到的格子，下面查「隐形交互点」要用
    for name, bx, by in mapdef["objects"]:
        assert name in obj, "物件清单里没有 %s" % name
        o = obj[name]
        wt, ht = o["tiles"]
        x0, y0 = bx - (wt - 1) // 2, by - ht + 1
        assert 0 <= x0 and x0 + wt <= w and 0 <= y0 and y0 + ht <= h, \
            "物件 %s 越界：盒 (%d,%d) %dx%d" % (name, x0, y0, wt, ht)
        for j in range(ht):
            for i in range(wt):
                assert rows[y0 + j][x0 + i] not in "#^\"%", \
                    "物件 %s 压在墙/屋顶上 (%d,%d)" % (name, x0 + i, y0 + j)
                put(1, x0 + i, y0 + j, o["tile_ids"][j][i])
                covered.add((x0 + i, y0 + j))

    # 没有行走图的交互点必须**看得见** —— 会挡路的隐形格就是一堵空气墙。
    # 这类事件是 priority 1（与玩家同层），而 MZ 里同层事件一律参与碰撞
    # （Game_Character.isCollidedWithEvents -> isNormalPriority），
    # 所以落在空地上的隐形事件，玩家会**撞到什么都没有的一格**，还找不出原因。
    # 反过来，踩上去的传送格是 priority 0，不挡路，所以不受这条约束。
    # 合格的做法只有两种：压在可见的东西上（井压在石井、碑压在石碑），
    # 或者本身就是门洞 —— `D` 是墙上的缺口，缺口自己就是视觉。
    for t in mapdef.get("npcs", []):
        nm, x, y, char = t[0], t[1], t[2], t[4]
        if char or rows[y][x] == "D" or (x, y) in covered:
            continue
        raise AssertionError(
            "M%s「%s」@(%d,%d)：无行走图、同格又无物件 —— 玩家会撞到空气墙"
            % (mapdef["name"], nm, x, y))
    return w, h, data


# ------------------------------------------------------------------ 道具
def install_items():
    """把数据层声明的道具写进 Items.json，返回 {名: id}。

    为什么这一步非做不可：`$dataItems[未定义 id]` **不会报错**。
      * gainItem() -> itemContainer(undefined) -> null -> 静默跳过（给了没给）
      * hasItem(undefined) -> `item && numItems(...)>0` -> 恒 false（条件永远走 else）
    于是道具漏登记的表现是「剧情整个走岔」，一句错都不报。所以这里 assert 死：
    id 必须等于它在字典里的下标（引擎是按 id 取 $dataItems 的），
    被事件引用的名字必须真的有定义。

    形状照模板的 Items[1] 抄，只改必须改的：不可消耗、关键物品、无效果、scope 0。
    关键物品（itypeId 2）在 MZ 里的原生语义就是「进物品栏、看得见、不可使用」——
    正合这些只是剧情痕迹的东西，也省掉「从菜单使用会弹选人窗」那一堆麻烦。
    """
    path = os.path.join(TARGET, "data", "Items.json")
    items = jload(path)
    by_name = {}
    base = None
    for i, (name, spec) in enumerate(G.ITEMS.items()):
        iid, icon, itype, desc = spec
        assert icon in G.ICON, "道具「%s」的图标短名 %r 不在 ICON 表里" % (name, icon)
        if base is None:
            base = iid
        assert iid == base + i, \
            "道具「%s」声明 id=%d，但按顺序应当是 %d —— id 必须连续且与顺序对齐" \
            % (name, iid, base + i)
        while len(items) <= iid:
            items.append(None)                  # 模板只到 id 30，中间不能留洞
        items[iid] = {
            "id": iid, "animationId": 0, "consumable": False,
            "damage": {"critical": False, "elementId": 0, "formula": "0",
                       "type": 0, "variance": 20},
            "description": desc, "effects": [], "hitType": 0,
            "iconIndex": G.ICON[icon], "itypeId": itype, "name": name, "note": "",
            "occasion": 0, "price": 0, "repeats": 1, "scope": 0, "speed": 0,
            "successRate": 100, "tpGain": 0,
        }
        by_name[name] = iid
    jdump(path, items)
    return by_name


def item_id(name):
    """道具名 -> id。名字写错就当场炸，不让它变成「静默走 else」。"""
    assert name in G.ITEMS, \
        "事件里引用了未登记的道具 %r —— 它不在 game_data.ITEMS 里" % name
    return G.ITEMS[name][0]


def switch_id(name):
    """开关名 -> id。跟 item_id 同一条理由：$gameSwitches 是**按 id 存布尔值**的，
    引用一个没登记的 id 不会报错 —— setValue 照写、value 读回来恒 false ——
    于是「开关永远打不开」在剧情上的表现就是某个分支永远进不去。
    """
    assert name in G.SWITCHES, \
        "事件里引用了未登记的开关 %r —— 它不在 game_data.SWITCHES 里" % name
    return G.SWITCHES[name]


def install_switches(sj):
    """把数据层声明的开关名写进 $dataSystem.switches，返回 {名: id}。

    **按索引覆盖，不整表替换** —— 跟 patch_terms 一个道理：编辑器与引擎都靠
    下标取开关，整表重写的风险远大于收益，而且错了不报错。

    名字本身引擎不读（$gameSwitches 里存的是 true/false），但它是这次改动的
    **可见印记**：编辑器里点开开关列表，看到的是「失虫 / 投井 / 斗虫 / 献虫 / 复旧」，
    而不是五个空白 —— 回头查一个开关是干什么用的，不必再翻代码。
    """
    table = sj["switches"]
    ids = {}
    for i, (name, sid) in enumerate(G.SWITCHES.items()):
        assert sid == i + 1, \
            "开关「%s」声明 id=%d，但按顺序应当是 %d —— id 必须连续且与顺序对齐" \
            % (name, sid, i + 1)
        assert sid < len(table), \
            "开关「%s」要 id=%d，而 $dataSystem.switches 只有 %d 条 —— MZ 模板换版本了" \
            % (name, sid, len(table))
        table[sid] = name
        ids[name] = sid
    return ids


# ------------------------------------------------------------------ 对话
def face_file(face):
    """事件里的脸图位 -> 脸图文件名（101 的第 1 个参数）。

    填的是 **CAST 的角色名**（如「宰」），不是文件名短名。
    2026-09-24 踩过：M4 三条写成了 "Zai" / "Guard"（文件名），
    `CAST.get()` 查不到就落到默认值 —— 对话框照常开，左边只是空一块，
    一句错都不报（宰那张新脸图因此白做了）。所以查不到一律当场炸。
    """
    if not face:
        return ""
    assert face in G.CAST, (
        "事件的对话脸图位写的是 %r，CAST 名册里没有这个角色 —— "
        "这里要填角色名（如「宰」），不是脸图文件名。" % face)
    return G.CAST[face][1] or ""


# ---------------------------------------------------------------- 台词折行
# **这台引擎不折行。** `Window_Base.flushTextState`（rmmz_windows.js:266）拿
# `textWidth(text)` 当宽度 `drawText` 一次画完，而 drawText 只是 canvas 填字
# （rmmz_core.js:1661）—— 没有 wordWrap，也不按 maxWidth 折。超宽的部分被
# 位图边界**静默裁掉**：不报错、不崩、日志里空白，只是那几个字从没上过屏。
# 唯一的换行来源是控制字符 `\n`（processNewLine，rmmz_windows.js:339）。
#
# 所以折行在**构建期**做掉，数据层只管写自然句子（写多长都不怕）。
# 可用宽度取自引擎 `Window_Message.newLineX`（4887）：
#     margin = 有脸 standardFaceWidth+20 / 无脸 4
#     innerWidth 实测 784 → 可用 620 / 780
#
# 宽度模型是**实测复现**，不是估算：2026-09-25 量了脚本用到的 702 个字符，
# 「逐字相加 vs 整行 measureText」在全部 170 行上偏差 **0px**（逐字宽度可加），
# ASCII 一律 13、CJK 一律 26，唯一例外是 U+2014「—」13px。
# 换字体（System.json 的 fontFace / fallbackFonts / fontSize）要重跑
# `.scratch/probe_charwidth.py` 复查：模型偏小才会溢出，验收量的是真宽度。
W_HALF, W_FULL, W_ICON = 13, 26, 36
W_EXCEPT = {"—": W_HALF}
W_LIMIT = {True: 620, False: 780}          # 有脸 / 无脸

# 折在标点**之后**（两行都还是完整的话）；收尾标点不得落到行首（禁则）。
BREAK_AFTER = "，。；：、！？"
NO_LINE_START = frozenset("，。；：、！？…—」』）")


def _tokens(text):
    """一行台词 -> [(片段, 宽度)]。`\\I[n]` 整段算一个 token（步进 36）。

    只认 `\\I[n]` 这一种转义（数据层也确实只用它）。别的反斜杠一律当场炸 ——
    引擎的 `\\C[5]` 会变成颜色控制码（宽度 0），我若按正文算宽，两边的账就对不上。
    """
    toks, i, n = [], 0, len(text)
    while i < n:
        if text[i] == "\\":
            assert text.startswith("\\I[", i), \
                "台词里只支持 \\I[n] 图标转义，遇到 %r" % text[max(0, i - 6):i + 6]
            j = text.find("]", i)
            assert j > i, "图标转义没闭合：%r" % text[i:i + 8]
            toks.append((text[i:j + 1], W_ICON))
            i = j + 1
        else:
            ch = text[i]
            toks.append((ch, W_EXCEPT.get(ch, W_HALF if ord(ch) < 0x80 else W_FULL)))
            i += 1
    return toks


def text_width(text):
    """按模型算一行有多宽。与引擎 `textWidth` 逐字一致（见上面的实测）。"""
    return sum(w for _t, w in _tokens(text))


def _cat(toks, a, b):
    return "".join(t for t, _w in toks[a:b])


def _wrap_para(para, limit):
    """没有 `\\n` 的一段文字 -> 装得下的若干行。

    切点只取「标点之后」（`BREAK_AFTER`），且不让收尾标点落到行首（禁则）；
    一整段里没有标点时按宽度硬断 —— 宁可断得难看，也绝不截掉。
    """
    toks = _tokens(para)
    pref = [0]
    for _t, w in toks:
        pref.append(pref[-1] + w)
    total = pref[-1]
    if total <= limit:
        return [para]
    # 能断的位置：卡在标点之后，且下一个字符不是收尾标点
    cands = [i for i in range(1, len(toks))
             if toks[i - 1][0][-1] in BREAK_AFTER and toks[i][0] not in NO_LINE_START]

    # 恰好两行：在候选里取**长边最短**的那个切点。
    # 贪心会先把第一行填满，于是把 5 个字的尾巴甩成孤儿行
    # （「……走到院里来，」/「仰头看天。」）——读起来是断的。
    # 22 条待折台词里 21 条正好两行，拉平一下很值。
    if total <= 2 * limit:
        fit = [i for i in cands if pref[i] <= limit and total - pref[i] <= limit]
        if fit:
            cut = min(fit, key=lambda i: max(pref[i], total - pref[i]))
            return [_cat(toks, 0, cut), _cat(toks, cut, len(toks)).lstrip(" ")]

    # 三行及以上：贪心 —— 每行尽量填满，断在最后一个能断的标点之后。
    segs, start = [], 0
    while start < len(toks):
        k = start
        while k < len(toks) and pref[k + 1] - pref[start] <= limit:
            k += 1
        if k == len(toks):
            segs.append(_cat(toks, start, k))
            break
        cut = next((i for i in reversed(cands) if start < i <= k), None)
        if cut is None:
            # 一整段里没标点 -> 硬断。`max(k, start+1)` 而不是直接 `k`：
            # 只有当**单个 token 本身就超过 limit** 时 k 才等于 start（当前
            # 最宽的 token 是图标 36 < 620，不会发生），但那时 `cut = k = start`
            # 会切出空行并原地打转。宁可切出一个超宽行 —— 它马上会被下面的
            # 断言抓住，死循环则连报错都没有。
            cut = max(k, start + 1)
        segs.append(_cat(toks, start, cut))
        start = cut
    return [segs[0]] + [s.lstrip(" ") for s in segs[1:]]


def wrap_line(text, face):
    """一行台词 -> 装得下的一至多行。

    模型是精确的（实测偏差 0px），所以这里的断言不是估算兜底，而是把
    「构建器绝不产出超宽行」这条不变式钉死在代码里 —— 将来谁改了折行规则，
    在构建期就炸，不会拖到六分钟后的真机走查。
    """
    limit = W_LIMIT[bool(face)]
    out = []
    for para in text.split("\n"):
        out.extend(_wrap_para(para, limit))
    for seg in out:
        assert text_width(seg) <= limit, \
            "折行后仍超宽 %d > %d：%r" % (text_width(seg), limit, seg)
    return out


def build_dialogue(face, speaker, lines, indent=0):
    """一段文字框 -> 指令序列。101 = 显示文字（脸图名/索引/背景/位置/说话人）

    脸图索引恒 0：drawFace 是按 (index%4)*pw, (index//4)*ph 抠 144x144 的
    （rmmz_windows.js:462），pw 来自 $dataSystem.faceSize，本工程没设 → 恒 144。
    所以一张 144x144 的图用 index 0 完全成立；老素材的 8 格表第 0 格也正好是正脸。

    indent **必须跟着调用方走**，不能写死 0：文字框落在分支体内时，
    indent 掉回 0 会让 skipBranch() 以为"分支到此为止"，条件为假也不跳 ——
    于是真段照样执行，整个条件分支形同虚设，而且一句错都不报。

    **每一行都过 `wrap_line`** —— 数据层写自然句子，装不下由这里按标点折。
    分页不用管：引擎 `needsNewPage`（rmmz_windows.js:5129）是按竖向溢出自动分页的，
    折行只是把行数变多，页数由引擎自己算。
    """
    face_name = face_file(face)
    # 反面：说话人明摆着是某个已配脸的角色，脸图位却空着 —— 对照不上的后果是
    # 对话框左边白空一块、图白画了，同样不报错。癞头蟆的脸图位是 ""（明确不配），
    # 所以判据要看 CAST 里那张脸到底有没有，而不是"说话人认不认识"。
    if not face and speaker in G.CAST and G.CAST[speaker][1]:
        raise AssertionError(
            "「%s」的台词没有配脸图，但 CAST 里已经给他配了 %r —— "
            "要么把脸图位填上角色名，要么说明这个说话人本来就不该露脸。"
            % (speaker, G.CAST[speaker][1]))
    cmds = [{"code": 101, "indent": indent, "parameters": [face_name, 0, 0, 2, speaker]}]
    for line in lines:
        for seg in wrap_line(line, face_name):    # 宽度上限看有没有脸
            cmds.append({"code": 401, "indent": indent, "parameters": [seg]})
    return cmds


def emit_lines(lines, face, speaker, indent=0):
    """数据层的 lines -> 指令序列（递归，支持分支）。

    缩进契约（源头 rmmz_objects.js command111 / command411 / skipBranch）：
        111 在 indent n，它的体内是 indent n+1，411 与 412 都回到 indent n。
        skipBranch() 是「往后跳，直到 indent <= 当前」——
        而 **412 在引擎里根本没有对应的 command412**，它只是让解释器继续往下走。
        所以缩进给错不会报错、不会崩，只是整个走飞。

    另一个必须遵守的：command101 会**一口气吃掉紧跟其后的所有 401**
    （`while (this.nextEventCode() === 401)`），所以每一段连续台词都得
    有自己的 101 —— 台词中间的夹角动作会把一段断成两段，正是我们要的。
    """
    cmds, buf = [], []

    def flush():
        # 累积的台词合成一段文字框。空 buf 不生成 101（否则会插出一个空框）。
        if buf:
            cmds.extend(build_dialogue(face, speaker, buf, indent))
            del buf[:]

    for item in lines:
        if isinstance(item, str):
            buf.append(item)
            continue
        assert isinstance(item, tuple) and item, "lines 里只认 str 和动作元组：%r" % (item,)
        kind = item[0]
        flush()
        if kind in ("给", "收"):
            n = item[2] if len(item) > 2 else 1
            # 126 = 增减道具，参数 [道具id, 0=增/1=减, 0=常量/1=变量, 个数]
            # 减到负数由 gainItem 内部 clamp 到 0（`Math.max(this.numItems(item)-n, 0)`），
            # 所以"收"一件此刻不在手上的东西不会变成 -1。
            cmds.append({"code": 126, "indent": indent,
                         "parameters": [item_id(item[1]), 0 if kind == "给" else 1, 0, n]})
        elif kind == "开":
            # 121 = 开关操作，参数 [起 id, 止 id, 0=开/1=关]。
            # 起止是给"一次管一段"用的；本工程一次只动一个，两个都填同一个 id。
            sid = switch_id(item[1])
            cmds.append({"code": 121, "indent": indent, "parameters": [sid, sid, 0]})
        elif kind == "声":
            # 250 = 播放 SE
            cmds.append({"code": 250, "indent": indent, "parameters": [dict(item[1])]})
        elif kind == "乐":
            # 249 = 播放 ME。跟 250 是同一个形状，唯一的区别在引擎那一侧：
            # ME 播的时候正在放的 BGM 会让位，播完自动接回来 ——
            # 于是"情绪拐点"不需要自己记「原来放的是哪首」再切回去。
            cmds.append({"code": 249, "indent": indent, "parameters": [dict(item[1])]})
        elif kind == "分支":
            assert 3 <= len(item) <= 4, "分支要 (条件, 真段[, 假段])：%r" % (item,)
            cond = item[1]
            if cond[0] == "道具":
                # 111 的条件类型 8 = 道具。**只有一个参数**（道具 id）——
                # 武器/护甲那两种（case 9/10）才多一个"含装备"，别照抄。
                params = [8, item_id(cond[1])]
            elif cond[0] == "开关":
                # 类型 0 = 开关，**三个参数**：`$gameSwitches.value(id) === (params[2] === 0)`。
                # 第三个参数不能省 —— 省略后 params[2] 是 undefined，
                # `undefined === 0` 为假，于是这个条件**永远判"关"**，
                # 而且不报错，只是分支永远走 else。
                # （踩点：光看数据层的 ("开关", 名) 根本看不出还差一个 0。）
                params = [0, switch_id(cond[1]), 0]
            else:
                raise AssertionError("不认识的条件 %r（只认 道具 / 开关）" % (cond,))
            cmds.append({"code": 111, "indent": indent, "parameters": params})
            cmds.extend(emit_lines(item[2], face, speaker, indent + 1))
            if len(item) == 4:
                cmds.append({"code": 411, "indent": indent, "parameters": []})
                cmds.extend(emit_lines(item[3], face, speaker, indent + 1))
            cmds.append({"code": 412, "indent": indent, "parameters": []})
        else:
            raise AssertionError("不认识的动作 %r（见 game_data 的事件词汇注释）" % (kind,))
    flush()
    return cmds


def build_page(image, commands, priority=1, trigger=0):
    """事件页。

    priorityType / trigger 必须**配对**着用，配错了不报错、只是永远触发不了：

      同层 + 按确定键   priority=1 trigger=0   NPC、门牌。站到它面前按确定键。
      下层 + 玩家接触   priority=0 trigger=1   传送格。走上去就触发。

    依据（都读自 rmmz_objects.js）：
      * Game_CharacterBase.isNormalPriority() = (priorityType === 1)；
        isCollidedWithEvents() 只把 priorityType===1 的事件算作挡路 ——
        所以 priority=0 的格子**踩得上去**。
      * Game_Player.updateNonmoving() 里，走完一步会调
        checkEventTriggerHere([1,2]) -> startMapEvent(x, y, [1,2], normal=false)，
        而 startMapEvent 要求 `event.isNormalPriority() === normal` ——
        即**只有 priorityType===0 的事件**会在「踩上去」这条路上被触发。
        面对面那条路（checkEventTriggerThere）传 normal=true 且只用 trigger 0，
        所以「priority=1 + trigger=1」的组合卡在两条路的缝里，谁都不认。
    """
    return {
        "conditions": {
            "actorId": 1, "actorValid": False,
            "itemId": 1, "itemValid": False,
            "selfSwitchCh": "A", "selfSwitchValid": False,
            "switch1Id": 1, "switch1Valid": False,
            "switch2Id": 1, "switch2Valid": False,
            "variableId": 1, "variableValid": False, "variableValue": 0,
        },
        "directionFix": False,
        "image": image,
        "list": commands + [{"code": 0, "indent": 0, "parameters": []}],
        "moveFrequency": 3,
        "moveRoute": {"list": [{"code": 0, "parameters": []}],
                      "repeat": True, "skippable": False, "wait": False},
        "moveSpeed": 3,
        "moveType": 0,
        "priorityType": priority,
        "stepAnime": False,
        "through": False,
        "trigger": trigger,
        "walkAnime": True,
    }


def build_transfer(t):
    """门 / 路口 -> 指令码 201（场所移动）的指令序列。

    参数契约（源头 rmmz_objects.js Game_Interpreter.prototype.command201）：
        [0, mapId, x, y, direction, fadeType]
    第 0 位 0 = 坐标直接指定（1 = 用变量），fadeType 0 = 黑场淡入淡出。
    command201 末尾自带 `this.setWaitMode("transfer")`，解释器会一直等到换图完成，
    所以后面不用再补等待指令。

    页的形状固定成 priority=0 + trigger=1（见 build_page 的注释）：传送格得
    **踩得上去**才可能被触发。图上不放角色，视觉上是「门 / 路的尽头」本身在起作用。
    """
    _name, _x, _y, _d, tmid, tx, ty, td = t
    return [{"code": 201, "indent": 0, "parameters": [0, tmid, tx, ty, td, 0]}]


def check_branch_structure(cmds, where):
    """指令序列的分支缩进必须自洽 —— 不查就是静默走飞。

    契约（rmmz_objects.js command111 / command411 / skipBranch）：
      111 落在 indent n，体内一律 indent n+1，411 与 412 都回到 n。
      skipBranch() 是「往后跳，直到 indent <= 当前」—— 所以只要体内混进
      一条 indent <= n 的指令（比如文字框掉了缩进），条件为假时它**不会跳**，
      真段照样执行。而 412 在引擎里**根本没有对应的 command412**，
      它只靠缩进被 skipBranch 追上、然后自然往下走。

    也就是说：缩进错了，引擎不报错、不崩，只是整个条件失控。
    所以结构必须在这里算出来断言 —— 人眼扫指令表是查不出来的
    （这个函数就是为了兜住一次真实踩坑：build_dialogue 曾把 indent 写死成 0）。
    """
    stack = []              # 每层: [该 111 的 indent, 是否已经过 411]
    for i, c in enumerate(cmds):
        code, ind = c["code"], c["indent"]
        inner = (stack[-1][0] + 1) if stack else 0
        if code == 111:
            assert ind == inner, \
                "%s：第 %d 条是 111，缩进 %d 应为 %d" % (where, i, ind, inner)
            stack.append([ind, False])
        elif code == 411:
            assert stack and stack[-1][0] == ind and not stack[-1][1], \
                "%s：第 %d 条 411 缩进 %d 与所属的 111 对不上（或重复出现）" % (where, i, ind)
            stack[-1][1] = True
        elif code == 412:
            assert stack and stack[-1][0] == ind, \
                "%s：第 %d 条 412 缩进 %d 找不到对应的 111" % (where, i, ind)
            stack.pop()
        else:
            assert ind == inner, \
                "%s：第 %d 条 code=%d 缩进 %d 应为 %d —— 缩进掉了，" \
                "分支条件为假时会照样执行" % (where, i, code, ind, inner)
    assert not stack, "%s：有 111 没有 412 收尾" % where


def build_events(mid):
    """一张图的事件表。顺序取自 G.events_of(mid) —— 顺序即 id，只留一处定义。"""
    evs = [None]
    for i, (kind, t) in enumerate(G.events_of(mid), 1):
        if kind == "npc":
            name, x, y, d, char, face, lines, se = t
            cmds = []
            if se:
                # 250 = 播放 SE。参数是**一个音频对象**，不是平铺的多个参数。
                # 事件级 SE 是无条件播的；"只在某条分支上响"要用 ("声", …) 动作。
                cmds.append({"code": 250, "indent": 0, "parameters": [dict(se)]})
            cmds += emit_lines(lines, face, name)
            check_branch_structure(cmds, "M%d「%s」" % (mid, name))
            img = {"tileId": 0, "characterName": char, "direction": d,
                   "pattern": 1, "characterIndex": 0}
            page = build_page(img, cmds)
        else:
            name, x, y, d = t[0], t[1], t[2], t[3]
            img = {"tileId": 0, "characterName": "", "direction": d,
                   "pattern": 1, "characterIndex": 0}
            page = build_page(img, build_transfer(t), priority=0, trigger=1)
        evs.append({"id": i, "name": name, "note": "",
                    "pages": [page], "x": x, "y": y})
    return evs


# ------------------------------------------------------------------ 主流程
def main():
    tex, obj = load_manifest()
    print("[1/7] 图块清单：%d 种纹理 / %d 件物件" % (len(tex), len(obj)))

    if os.path.isdir(TARGET):
        shutil.rmtree(TARGET)
    shutil.copytree(TEMPLATE, TARGET)
    print("[2/7] 模板已复制 -> %s" % TARGET)

    n_asset = 0
    if os.path.isdir(ASSETS):
        # assets/ 是**筹备目录**，布局仿引擎；但里面的参照图不能跟着进包 ——
        # portraits/ 是给美术看的（原图、立绘、对照图，7MB 起），引擎一个字都不读。
        # 全量拷过去，将来往 GitHub Pages 一推就是白送几兆流量。
        for d in sorted(os.listdir(ASSETS)):
            if d in NO_SHIP:
                continue
            src_, dst_ = os.path.join(ASSETS, d), os.path.join(TARGET, d)
            if os.path.isdir(src_):
                shutil.copytree(src_, dst_, dirs_exist_ok=True)
                n_asset += sum(len(fs) for _, _, fs in os.walk(src_))
            else:
                shutil.copyfile(src_, dst_)
                n_asset += 1
    n_cast, n_face = check_cast_assets()
    print("[3/7] 自制素材注入 %d 个文件（名册 %d 人，脸图 %d 张，尺寸契约已过）"
          % (n_asset, n_cast, n_face))

    with open(os.path.join(TARGET, "game.rmmzproject"), "w",
              encoding="utf-8", newline="\n") as f:
        f.write("RPGMZ 1.0.1")

    n_img, n_block = install_tileset()
    items = install_items()
    print("[4/7] 图块集「%s」已登记 id=%d：%d 张图 / %d 格判定为阻挡"
          % (G.TILESET_NAME, TILESET_ID, n_img, n_block))
    print("      道具已登记 %d 件：%s"
          % (len(items), "、".join("%s(id%d)" % (k, v) for k, v in items.items())))

    # ---- System.json ----
    sp = os.path.join(TARGET, "data", "System.json")
    sj = jload(sp)
    mid, sx, sy, sd = G.START
    sj["gameTitle"] = G.TITLE
    sj["startMapId"], sj["startX"], sj["startY"] = mid, sx, sy
    sj["editMapId"] = mid
    # 单人队、不显示跟随者：模板的 [1,4,6,7] 里 4/6/7 是 Michelle/Kasey/Eliot，
    # 行走图是 MZ 自带的现代装 Actor1 —— 三个现代小人跟着成名，既出戏又挡石径。
    sj["partyMembers"] = list(G.PARTY)
    sj["optFollowers"] = G.FOLLOWERS
    n_term = patch_terms(sj)
    switches = install_switches(sj)
    sj["advanced"]["fallbackFonts"] = G.FALLBACK_FONTS
    # 官方 newdata 模板缺这个字段，而引擎 Game_System.windowOpacity() 是零兜底引用 ——
    # 不补则一进标题画面就 `Cannot read properties of undefined (reading 'clamp')`。
    # 永久防线：tools/check_system_contract.py
    sj["advanced"]["windowOpacity"] = sj["advanced"].get("windowOpacity", 192)
    rel_bg = install_title_bg(sj)
    sj["versionId"] = (sj.get("versionId") or 0) + 1
    jdump(sp, sj)

    # ---- Actors.json ----
    ap = os.path.join(TARGET, "data", "Actors.json")
    actors = jload(ap)
    for a in actors:
        if a and a["id"] == 1:
            a.update({"name": "成名", "nickname": "成名",
                      "characterName": "$ChengMing", "characterIndex": 0,
                      "faceName": "ChengMing", "faceIndex": 0})
    jdump(ap, actors)
    print("[5/7] System/Actors 已修：标题=%s 起点=(%d,%d) 朝向=%d 队伍=%s 跟随=%s"
          " 术语中文化 %d 条"
          % (G.TITLE, sx, sy, sd, list(G.PARTY), G.FOLLOWERS, n_term))
    print("      标题背景 = %s" % (rel_bg or "（未设，仍是 MZ 自带的 Ruins）"))
    print("      开关已命名 %d 个：%s"
          % (len(switches), "、".join("%s(id%d)" % (k, v) for k, v in switches.items())))

    # ---- 地图 ----
    # 模板工程只有一张图（Map001 + MapInfos 里一条）。第 2 张起，文件与索引都得自己造：
    #   * Map00N.json 缺了就**照模板 Map001 抄一份字段骨架**再覆盖 —— 不硬编码字段名，
    #     引擎加字段时这里自动跟上；
    #   * MapInfos 缺条目就补。不补的话编辑器看不见这张图，
    #     而 validate_project 又是按 MapInfos 遍历的 —— 会连带漏检。
    infos = jload(os.path.join(TARGET, "data", "MapInfos.json"))
    have = {it["id"] for it in infos if it}
    for mid in sorted(G.MAPS):
        if mid not in have:
            infos.append({"id": mid, "expanded": False, "name": "",
                          "order": max([it["order"] for it in infos if it] + [0]) + 1,
                          "parentId": 0, "scrollX": 0, "scrollY": 0})
            print("      + MapInfos 补登记 地图 %d" % mid)

    report = []
    for mid in sorted(G.MAPS):
        md = G.MAPS[mid]
        w, h, data = paint(md, tex, obj)
        evs = build_events(mid)
        p = os.path.join(TARGET, "data", "Map%03d.json" % mid)
        m = jload(p) if os.path.exists(p) else blank_map()
        m.update({"width": w, "height": h, "data": data, "events": evs,
                  "tilesetId": TILESET_ID, "displayName": md["name"]})
        for key, folder in (("bgm", "bgm"), ("bgs", "bgs")):
            # 地图自带音效：数据层只给**名字**，声音对象在这里拼。
            # 名字写错不会报错，只会静默无声 —— validate_project 会查它存不存在。
            m["autoplay" + key.capitalize()] = bool(md.get(key))
            if md.get(key):
                m[key] = {"name": md[key], "pan": 0, "pitch": 100, "volume": 90}
        jdump(p, m)
        for it in infos:
            if it and it["id"] == mid:
                it["name"] = md["name"]
                it["scrollX"], it["scrollY"] = md["scroll"]
        n_port = len(md.get("portals", []))
        report.append("      M%d「%s」 %dx%d  物件 %d  事件 %d（含门口 %d）  音 %s"
                      % (mid, md["name"], w, h, len(md["objects"]), len(evs) - 1,
                         n_port, md.get("bgm") or "静默"))
    jdump(os.path.join(TARGET, "data", "MapInfos.json"), infos)
    print("[6/7] 地图已生成：")
    print("\n".join(report))

    # ---- 素材裁剪（必须是最后一步）----
    # 上面第 [2/7] 步 copytree(newdata) 会把模板全套 RTP 搬进来（约 92 MB 的
    # img+audio），而游戏真正引用到的只有零头。不裁的话：
    #   * 仓库 148 MB，clone / Pages 部署都慢一个数量级；
    #   * MZ 的 EULA 允许"随作品分发素材"，但仓库里躺着 40 首没用过的 BGM、
    #     90 多张没引用过的战斗背景，那更像"素材副本"而不是"随作品分发"。
    # 判据与"为什么宁可多留"见 tools/prune_assets.py 的模块头。
    # 裁剪发生在这里而不是更早，是因为要等所有 data/*.json 落盘后才能算引用面。
    st = P.prune(TARGET)
    print("\n[7/7] 素材裁剪：保留 %s 个 / 删除 %s 个（省下 %.2f MB）"
          % (st["keep"], st["drop"], st["drop_bytes"] / 1048576))
    print("\n完成。工程目录：%s" % TARGET)


if __name__ == "__main__":
    main()
