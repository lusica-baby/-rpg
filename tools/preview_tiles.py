# -*- coding: utf-8 -*-
"""图块集验收图：证明「素材 -> 图块集 -> tileId」这条链是通的。

三张对照图：
  _prev_a5.png       6 种地面纹理各铺 3x3 块，检验无缝
  _prev_d.png        4 种墙面/屋顶纹理各铺 3x3 块，检验可平铺
  _prev_objects.png  31 件物件的整格盒内容，检验无串味、无溢出

关键点：地面/墙面的平铺图**按 manifest 里的 tile_ids 取格**，不是按 slot 顺序猜，
所以图连续 = id 映射正确。
"""
import os
import sys
import json
from PIL import Image, ImageDraw

TILE = 48
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
T = os.path.join(ROOT, "assets", "img", "tilesets")
MAN = json.load(open(os.path.join(ROOT, "build", "tiles_manifest.json"), encoding="utf-8"))

sys.path.insert(0, HERE)
from build_tiles import cell_of      # 取格换算只有这一处实现

_cache = {}


def load(n):
    if n not in _cache:
        _cache[n] = Image.open(os.path.join(T, n)).convert("RGBA")
    return _cache[n]


def tile_at(sheet, tid):
    c, r = cell_of(sheet, tid)
    src = load(sheet + ".png")
    return src.crop((c * TILE, r * TILE, c * TILE + TILE, r * TILE + TILE))


def seamless(sheet, ids, reps=3, side=4):
    """把 4x4 的 id 表当图案平铺 reps x reps 次，接缝不合会一眼看出来"""
    out = Image.new("RGBA", (side * TILE * reps,) * 2)
    for ry in range(reps):
        for rx in range(reps):
            for j, tid in enumerate(ids):
                out.paste(tile_at(sheet, tid),
                          (rx * side * TILE + (j % side) * TILE,
                           ry * side * TILE + (j // side) * TILE))
    return out


def checker(size, cell=24):
    im = Image.new("RGB", size, (48, 48, 52))
    d = ImageDraw.Draw(im)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2:
                d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=(72, 72, 78))
    return im


def sheet_grid(name, refs, cols, cellw, cellh, note_key):
    """把若干 4x4 纹理块平铺预览，排成 cols 列的网格"""
    cv = Image.new("RGB", (cols * cellw, -(-len(refs) // cols) * cellh), (20, 20, 20))
    d = ImageDraw.Draw(cv)
    for k, t in enumerate(refs):
        p = seamless(t["sheet"], t["tile_ids"]).resize((cellw - 8, cellw - 8), Image.LANCZOS)
        cx, cy = (k % cols) * cellw + 4, (k // cols) * cellh
        cv.paste(p.convert("RGB"), (cx, cy))
        d.text((cx, cy + cellw - 2), "%s  %s %.1f" % (t["name"], note_key, t["seam_cost"]),
               fill=(232, 232, 232))
    cv.save(os.path.join(ROOT, "_prev_%s.png" % name))


tex = [t for t in MAN["textures"] if t["sheet"] == "Ming_A5"]
wall = [t for t in MAN["textures"] if t["sheet"] == "Ming_D"]
objs = MAN["objects"]
sheet_grid("a5", tex, 3, 240, 264, "seam")
sheet_grid("d", wall, 4, 240, 264, "seam")

# ---- 物件：逐件按其所属图块集与整格盒内容放大 ----
COLS, SCALE = 6, 2
CW = max(o["tiles"][0] for o in objs) * TILE * SCALE + 14
CH = max(o["tiles"][1] for o in objs) * TILE * SCALE + 32
cv = Image.new("RGB", (COLS * CW, -(-len(objs) // COLS) * CH), (24, 24, 24))
d = ImageDraw.Draw(cv)
for n, o in enumerate(objs):
    wt, ht = o["tiles"]
    bx, by = o["box"]
    patch = load(o["sheet"] + ".png").crop((bx, by, bx + wt * TILE, by + ht * TILE))
    patch = patch.resize((wt * TILE * SCALE, ht * TILE * SCALE), Image.NEAREST)
    bg = checker(patch.size, TILE * SCALE)
    bg.paste(patch, (0, 0), patch)
    ImageDraw.Draw(bg).rectangle([0, 0, bg.width - 1, bg.height - 1], outline=(230, 60, 60))
    cx, cy = (n % COLS) * CW + 7, (n // COLS) * CH + 4
    cv.paste(bg, (cx, cy + CH - 30 - bg.height))
    d.text((cx, cy + CH - 24), "%s %s %dx%d" % (o["name"], o["sheet"].replace("Ming_", ""), wt, ht),
           fill=(220, 220, 220))
cv.save(os.path.join(ROOT, "_prev_objects.png"))

print("A5 %d 种地面 / D %d 种墙屋顶 / 物件 %d 件" % (len(tex), len(wall), len(objs)))
print("-> _prev_a5.png  _prev_d.png  _prev_objects.png")
