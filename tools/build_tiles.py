# -*- coding: utf-8 -*-
"""明代素材 -> RPG Maker MZ 图块集图片

设计决策（重要）：
  全部走「普通图块」，**完全不使用 autotile**（A2/A3/A4）。
  autotile 需要 48/16 种边界过渡形状，用户素材里没有过渡美术；
  地面纹理无缝、墙面可平铺，俯视 2D 里硬边界完全可接受。
  绕开 autotile = 绕开一整个类别的 bug。

  纹理类（地面/墙面/屋顶）：不盲目镜像（会产生万花筒图案），
  改为在源图上**搜索接缝代价最低的 192x192 窗口**，用数字说话。

  物件类：横排素材表里物件会横向重叠，按列间隙切不干净；
  改用 **2D 连通域 + 列占用局部极小值二次切分**。

产物（assets/img/tilesets/）：
  Ming_A1..A4.png  全透明占位（Tilesets.json 会引用，缺图 -> 加载即崩）
  Ming_A5.png      384x768   地面：每种材质一个 4x4 整块，每行两块
  Ming_D.png       768x768   墙面 / 屋顶纹理（各一个 4x4 整块）
  Ming_B/C/E.png   768x768   物件

清单（build/tiles_manifest.json）**直接记录 tileId**，
地图构建器只认 id，不再自己重算槽位——换算只在一个地方写、只错一次。

图块槽位换算（来自 rmmz_core.js Tilemap._addNormalTile，已核对）：
  A5(tileId 1536..1663): id = 1536 + col + 8 * row
  B/C/D/E(tileId 0..1023): id = base + (col % 8) + 8 * row + 128 * (col // 8)
    base: B=0  C=256  D=512  E=768
  所以 B..E 的图在 col 8..15 的那半张映射到 +128 的号段，矩形**不能跨 col 8 分界**。
"""
import os
import json
import numpy as np
from PIL import Image, ImageDraw

TILE = 48
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = r"C:\Users\lenovo\Downloads\ming_tilesets"
OUT = os.path.join(ROOT, "assets", "img", "tilesets")
BUILD = os.path.join(ROOT, "build")

MAT_TILES = 4          # 每种纹理占 4x4 格
PATCH = MAT_TILES * TILE
OBJ_SCALE = 0.18       # 物件统一缩放（树 ~4 格高，方桌 ~2 格宽）
ALPHA_MIN = 64
GRID = 16              # B/C/D/E 为 16x16 格

# 纹理取样的大致方位（避免取到屋脊/山墙/背景），实际窗口由搜索+有效性筛决定。
# 屋顶两张是整栋 45° 插画（画布角落是黑底），一开始靠有效性筛在全图里自己挑，
# 结果挑中了**屋脊**和**檐下木墙**——两者都又平又匀，接缝代价最低，但铺出来一条浅色横带。
# 依据 _grid_*.png（原图切 5x5 打上行列号）手工指定整片瓦面的方位。
#
# 教训：**接缝代价只是个筛选器，不能当选优标准**。茅草是斜向草丝，任何 48x48 窗口
# 都不可能真正无缝，代价必然高（27+）；而木墙这种平直纹理代价只有 11。数值上木墙更好看，
# 视觉上却完全不是屋顶。唯一可信的验收是看 2x2 平铺图（_prev_d.png）。
TEXTURE_HINT = {
    "brick_wall":  (0.20, 0.25, 0.75, 0.80),
    "earth_wall":  (0.15, 0.25, 0.80, 0.85),
    "thatch_roof": (0.02, 0.18, 0.30, 0.50),    # 左上那片纯草面，避开屋脊与檐下木墙
    "tile_roof":   (0.56, 0.55, 1.00, 0.99),    # 右下那片筒瓦，避开正脊与垂脊
}


def blank(w, h):
    return Image.new("RGBA", (w, h), (0, 0, 0, 0))


# ---- 引擎图块槽位 <-> tileId 的换算（源头：rmmz_core.js Tilemap._addNormalTile）----
#   setNumber = 4 (A5) / 5+floor(tileId/256) (B..E)
#   sx = ((floor(tileId/128) % 2) * 8 + tileId % 8) * w
#   sy = (floor((tileId % 256) / 8) % 16) * h
BASE = {"Ming_A5": 1536, "Ming_B": 0, "Ming_C": 256, "Ming_D": 512, "Ming_E": 768}


def tile_id(sheet, pcol, prow):
    """图块图上的格子坐标 -> 地图 data 数组里要写的 tileId"""
    if sheet == "Ming_A5":
        return 1536 + pcol + 8 * prow          # A5 只占 col 0..7
    return BASE[sheet] + (pcol % 8) + 8 * prow + 128 * (pcol // 8)


def block_ids(sheet, pcol, prow, wt, ht):
    """一个 wt x ht 的整格块，逐格展开成 tileId 的二维表（行优先，与地图写入顺序一致）"""
    return [[tile_id(sheet, pcol + i, prow + j) for i in range(wt)] for j in range(ht)]


def cell_of(sheet, tid):
    """tile_id 的逆运算：tileId -> 图块图上的格子坐标。

    行号的 `% 16` 不是多余的：col 8..15 那半张映射到 +128 号段，
    t//8 会算到 16、超出图块图高度，取模让它回绕到第 0 行。
    引擎源码正是 `Math.floor((tileId % 256) / 8) % 16`。
    """
    if sheet == "Ming_A5":
        t = tid - 1536
        return t % 8, (t // 8) % 16
    t = tid - BASE[sheet]
    return (t % 8) + 8 * ((t // 128) % 2), (t // 8) % 16


def best_window(arr, side, hint, step=16, keep=40, min_luma=45.0, min_std=7.0):
    """在 hint 比例范围内找「可平铺」的 side x side 窗口。

    两个阶段，缺一不可：
      1) 按接缝代价排序（便宜，向量化）
      2) 在代价最低的 keep 个候选里**筛有效性**：均值亮度 / 标准差不能太低

    为什么必须筛：AI 出的屋顶图是整栋 45° 插画，画布角落是纯黑背景。
    接缝代价在纯黑区恒等于 0 —— 「最便宜」的窗口恰恰是最没用的那一块。
    （实测 thatch_roof / tile_roof 就是这么变成一张全黑图的）
    """
    H, W, _ = arr.shape
    gx0, gy0, gx1, gy1 = hint
    x_lo, x_hi = int(gx0 * W), int(gx1 * W)
    y_lo, y_hi = int(gy0 * H), int(gy1 * H)
    x_hi = max(x_lo + 1, min(x_hi, W) - side + 1)
    y_hi = max(y_lo + 1, min(y_hi, H) - side + 1)
    xs = list(range(x_lo, x_hi, step)) or [x_lo]

    cands = []                                  # (cost, x, y)
    for y in range(y_lo, y_hi, step):
        hc = np.abs(arr[y, :W - side + 1] - arr[y + side - 1, :W - side + 1]).mean(axis=1)
        band = arr[y:y + side]
        vc = np.abs(band[:, :W - side + 1] - band[:, side - 1:]).mean(axis=(0, 2))
        tot = hc + vc
        for x in xs:
            cands.append((float(tot[x]), x, y))
    if not cands:
        return (x_lo, y_lo), 0.0

    cands.sort()
    for cost, x, y in cands[:keep]:
        win = arr[y:y + side, x:x + side].astype(np.float32)
        if win.mean() >= min_luma and win.std() >= min_std:
            return (x, y), cost
    # 全都没过筛（例如整张图就是深色的）：退回接缝代价最低的那个，别崩
    return (cands[0][1], cands[0][2]), cands[0][0]


def cut_tiles(im, n=MAT_TILES):
    return [im.crop(((i % n) * TILE, (i // n) * TILE,
                     (i % n) * TILE + TILE, (i // n) * TILE + TILE))
            for i in range(n * n)]


class Sheet:
    """一张 16x16 格的 B/C/D/E 图，货架式装箱。

    不能按「线性游标 += wt*ht」推进：矩形是 wt 列 x ht 行，线性跨步会
    让后一件压到前一件的下一行格子上（实测 indoor#0 和 #4 抢同一批格子，
    两件物件互相串味）。改成标准货架：一行排满就换下一段。
    """
    def __init__(self):
        self.img = blank(GRID * TILE, GRID * TILE)
        self.x = self.y = self.h = 0

    def fits(self, wt, ht):
        x, y, h = self.x, self.y, self.h
        if x + wt > GRID:
            y, x, h = y + h, 0, 0
        return y + ht <= GRID

    def put(self, art, wt, ht):
        """把美术放进 wt x ht 的整格盒子：水平居中、底对齐。

        引擎是按「格子盒」渲染的（按 col/row 切 48x48 画），
        盒内偏移是美术自己的事，对外只需给出**盒子左上角**。
        """
        # 不能跨 8 列分界：tileId 映射里 col 8..15 属于另外 128 个号段，
        # 一个矩形若横跨分界，就得拆成两段 tileId，写入逻辑立刻复杂化。
        if self.x % 8 + wt > 8 or self.x + wt > GRID:
            nx = (self.x // 8 + 1) * 8
            if nx + wt > GRID:                 # 本行剩下的半区也放不下 -> 换行
                self.y += self.h
                self.x = self.h = 0
            else:
                self.x = nx
        assert self.y + ht <= GRID, "图块集装满"
        assert art.width <= wt * TILE and art.height <= ht * TILE, "美术装不进整格盒"
        cx, cy = self.x * TILE, self.y * TILE
        ox = (wt * TILE - art.width) // 2
        oy = ht * TILE - art.height            # 底对齐
        self.img.paste(art, (cx + ox, cy + oy), art)
        self.x += wt
        self.h = max(self.h, ht)
        return [cx, cy, ox, oy, wt, ht]

    @property
    def used_rows(self):
        return self.y + self.h


# ---------------------------------------------------------------- 物件切分
def _shift(m, ax, sh, fill):
    s = np.roll(m, sh, axis=ax)
    if ax == 0:
        s[0 if sh > 0 else -1, :] = fill
    else:
        s[:, 0 if sh > 0 else -1] = fill
    return s


def _morph(m, grow, it=1):
    """grow=True 为膨胀（去小黑点），grow=False 为腐蚀（去小白点）"""
    for _ in range(it):
        if grow:
            a = np.zeros_like(m)
            for sh in (1, -1):
                a |= _shift(m, 0, sh, False) | _shift(m, 1, sh, False)
        else:
            a = np.ones_like(m)
            for sh in (1, -1):
                a &= _shift(m, 0, sh, True) & _shift(m, 1, sh, True)
        m = a
    return m


def _propagate(labels, mask):
    """种子标签沿连通域铺满 mask（每轮四向 np.maximum，收敛到不动点）"""
    while True:
        new = labels.copy()
        for ax, sh in ((0, 1), (0, -1), (1, 1), (1, -1)):
            np.maximum(new, _shift(labels, ax, sh, 0), out=new)
        new[~mask] = 0
        if np.array_equal(new, labels):
            return labels
        labels = new


def _row_runs(flags, min_w, seed_into, row0, row1, nid):
    """把一行布尔里的连续段各分配一个新标签，返回新的 nid"""
    s = None
    for i in range(len(flags) + 1):
        v = flags[i] if i < len(flags) else False
        if v and s is None:
            s = i
        elif not v and s is not None:
            if i - s >= min_w:
                nid += 1
                seed_into[row0:row1 + 1, s:i] = nid
            s = None
    return nid


def split_objects(im, band_h=0.10, min_w=16, min_px=600):
    """切出横排物件表里的每个物件 —— 自适应基线 + 底部种子洪水填充。

    为什么不能按列间隙切：AI 素材表里树冠会横跨到邻居上方、柴堆贴着树干，
    整行一个空白列都没有（实测 outdoor 表 1385px 内 0 个间隙）。

    流程：
      1. 形态学开运算去噪 —— 表里到处是 1~2px 杂点，会把包围盒撑到全高
      2. 自动找**基线**（最后一条还有实质质量的扫描行；三张表分别是 72%/78%/70%，
         不能写死；也不能取行占用峰值，峰值在物体中段）
      3. 基线带里的每段 = 一个种子，沿连通域扩散，一个标签一个物件
         —— 树冠会归给最近的树干，正是要的效果
      4. 兜底：浮在基线上方的悬挂物（灯笼、挂轴）没有种子，
         对剩余未标注区域逐轮补种，直到标完
      5. **按各自标签遮罩裁剪** —— 相邻物件的像素互不串味
    """
    W, H = im.size
    raw = np.asarray(im.getchannel("A")) > ALPHA_MIN
    mask = _morph(_morph(raw, False, 1), True, 1)

    rs = np.convolve(mask.sum(axis=1).astype(float), np.ones(41) / 41, mode="same")
    sub = rs[H // 3:]
    yb = int(np.max(np.where(sub > 0.06 * sub.max())[0])) + H // 3

    # 1/2 降采样做标签扩散（速度优先）
    m2, y2 = mask[::2, ::2], yb // 2
    y0 = max(0, y2 - int(m2.shape[0] * band_h))
    seeds = np.zeros(m2.shape, np.int32)
    nid = _row_runs(m2[y0:y2 + 1, :].any(axis=0), max(1, min_w // 2), seeds, y0, y2, 0)

    lab = _propagate(seeds, m2) if nid else np.zeros(m2.shape, np.int32)
    # 兜底补种：悬挂物（灯笼/挂轴）浮在基线上方，基线带里没有它们的种子。
    # 对剩余未标注区域，取它**最宽的一行**（= 主体）做种子带 ——
    # 不能取最低行：灯笼最低处只有 1px 宽的穗子，够不上最小宽度。
    for _ in range(40):
        left = m2 & (lab == 0)
        if not left.any():
            break
        yb2 = int(np.argmax(left.sum(axis=1)))
        a, b = max(0, yb2 - 15), min(m2.shape[0] - 1, yb2 + 15)
        before = nid
        nid = _row_runs(left[a:b + 1].any(axis=0), max(1, min_w // 2), lab, a, b, nid)
        if nid == before:
            break
        lab = _propagate(lab, m2)

    lab = np.repeat(np.repeat(lab, 2, axis=0), 2, axis=1)[:H, :W]

    out = []
    for k in range(1, nid + 1):
        m = raw & (lab == k)
        if m.sum() < min_px:
            continue
        rows = np.where(m.any(axis=1))[0]
        cols = np.where(m.any(axis=0))[0]
        x0, y0b = int(cols[0]), int(rows[0])
        x1, y1b = int(cols[-1]) + 1, int(rows[-1]) + 1
        art = im.crop((x0, y0b, x1, y1b))
        a = np.asarray(art.getchannel("A")).copy()
        a[~m[y0b:y1b, x0:x1]] = 0
        art.putalpha(Image.fromarray(a))
        out.append({"box": (x0, y0b, x1, y1b), "art": art})
    out.sort(key=lambda o: o["box"][0])
    return out


# ---------------------------------------------------------------- 主流程
def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(BUILD, exist_ok=True)
    log = {}
    man = {"textures": [], "objects": []}

    for i, (w, h) in enumerate([(768, 576), (768, 576), (768, 384), (768, 480)], 1):
        blank(w, h).save(os.path.join(OUT, "Ming_A%d.png" % i))
    log["A1..A4"] = "全透明占位"

    def lay_texture(sheet, canvas, name, im, hint, step, bc, br):
        """在 (bc,br) 处铺一个 4x4 的地面/墙面纹理块，返回其 16 个 tileId"""
        arr = np.asarray(im).astype(np.int16)
        (x, y), cost = best_window(arr, PATCH, hint, step=step)
        crop = im.crop((x, y, x + PATCH, y + PATCH)).convert("RGBA")
        ids = []
        for j, t in enumerate(cut_tiles(crop)):
            pcol, prow = bc + j % MAT_TILES, br + j // MAT_TILES
            canvas.paste(t, (pcol * TILE, prow * TILE))
            ids.append(tile_id(sheet, pcol, prow))
        man["textures"].append({"sheet": sheet, "name": name, "block": [bc, br],
                                "src_xy": [x, y], "tile_ids": ids,
                                "seam_cost": round(cost, 2)})
        log.setdefault(sheet, []).append(
            "%-22s 块(%d,%d) 窗口(%4d,%4d) 接缝代价 %5.2f  id %d..%d"
            % (name, bc, br, x, y, cost, ids[0], ids[-1]))

    # ---- A5：地面（8 列 x 16 行；每种材质一个 4x4 整块，每行放两块）----
    a5 = blank(8 * TILE, 16 * TILE)
    gdir = os.path.join(SRC, "ground")
    for k, n in enumerate(sorted(os.listdir(gdir))):
        lay_texture("Ming_A5", a5, n,
                    Image.open(os.path.join(gdir, n)).convert("RGB"),
                    (0.05, 0.05, 0.95, 0.95), 24,
                    (k % 2) * MAT_TILES, (k // 2) * MAT_TILES)
    a5.save(os.path.join(OUT, "Ming_A5.png"))

    # ---- D：墙面 / 屋顶纹理 ----
    dimg = blank(GRID * TILE, GRID * TILE)
    wdir = os.path.join(SRC, "walls_roofs")
    for k, n in enumerate(sorted(os.listdir(wdir))):
        lay_texture("Ming_D", dimg, n,
                    Image.open(os.path.join(wdir, n)).convert("RGB"),
                    TEXTURE_HINT[os.path.splitext(n)[0]], 16,
                    (k % 4) * MAT_TILES, (k // 4) * MAT_TILES)
    dimg.save(os.path.join(OUT, "Ming_D.png"))

    # ---- B/C/E：物件 ----
    sheets, snames = [Sheet(), Sheet(), Sheet()], ["Ming_B", "Ming_C", "Ming_E"]
    odir = os.path.join(SRC, "objects")
    cut_log = []
    for n in sorted(os.listdir(odir)):
        im = Image.open(os.path.join(odir, n)).convert("RGBA")
        objs_here = split_objects(im)
        cut_log.append("%s: %d 件" % (n, len(objs_here)))
        for i, o in enumerate(objs_here):
            art = o["art"]
            w = max(1, round(art.width * OBJ_SCALE))
            h = max(1, round(art.height * OBJ_SCALE))
            art = art.resize((w, h), Image.LANCZOS)
            wt, ht = max(1, -(-w // TILE)), max(1, -(-h // TILE))
            sh = next((s for s in sheets if s.fits(wt, ht)), None)
            assert sh, "三张物件表都装满了"
            cx, cy, ox, oy, wt, ht = sh.put(art, wt, ht)
            sn = snames[sheets.index(sh)]
            man["objects"].append({"name": "%s#%d" % (os.path.splitext(n)[0], i),
                                   "sheet": sn,
                                   "box": [cx, cy], "art_off": [ox, oy],
                                   "src_box": list(o["box"]), "tiles": [wt, ht],
                                   "tile_ids": block_ids(sn, cx // TILE, cy // TILE, wt, ht)})
    for s, nm in zip(sheets, snames):
        s.img.save(os.path.join(OUT, nm + ".png"))

    # ---- 星标 id：高物件的「上半身」 ----
    # 引擎里带 0x10 的图块走 _upperLayer（z=4），**画在角色之上**。
    # 这是 MZ 表现「能走到树后面」的正规机制：树干那行普通阻挡，
    # 树冠几行标星 -> 玩家站到树冠格时被叶子盖住，而不是踩在树上。
    # 只标到倒数第二行为止；最后一行是落脚点，必须留在普通层当墙。
    star = set()
    for o in man["objects"]:
        wt, ht = o["tiles"]
        for j in range(ht - 1):
            star.update(o["tile_ids"][j])
    man["star_ids"] = sorted(star)
    log["星标_物件上半身"] = "%d 个 tileId（%d 件高物件）" % (
        len(star), sum(1 for o in man["objects"] if o["tiles"][1] >= 2))

    log["A5_用量"] = "%d/128 格" % (len(os.listdir(gdir)) * MAT_TILES * MAT_TILES)
    log["D_用量"] = "%d/256 格" % (len(os.listdir(wdir)) * MAT_TILES * MAT_TILES)
    log["objects"] = cut_log
    log["B/C/E_已用行数"] = "%d / %d / %d  (各 16)" % tuple(s.used_rows for s in sheets)
    log["物件清单"] = ["%-22s %-6s %-4s id %s" % (o["name"], o["sheet"],
                       "%dx%d" % tuple(o["tiles"]),
                       ", ".join(str(c) for r in o["tile_ids"] for c in r))
                       for o in man["objects"]]

    # 把切出来的物件框 + 遮罩结果画回原图，人工核对
    for n in sorted(os.listdir(odir)):
        im = Image.open(os.path.join(odir, n)).convert("RGBA")
        vis = Image.new("RGB", im.size, (245, 245, 245))
        vis.paste(im, (0, 0), im)
        dr = ImageDraw.Draw(vis)
        for i, o in enumerate(split_objects(im)):
            bx = o["box"]
            dr.rectangle([bx[0], bx[1], bx[2] - 1, bx[3] - 1], outline=(220, 0, 0), width=4)
            dr.text((bx[0] + 8, bx[1] + 8), str(i), fill=(0, 90, 200))
        vis.save(os.path.join(ROOT, "_cut_" + os.path.splitext(n)[0] + ".png"))

    json.dump(man, open(os.path.join(BUILD, "tiles_manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(json.dumps(log, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
