# -*- coding: utf-8 -*-
"""把已生成的 Map00N.json 渲染成 PNG —— 开游戏之前先自查。

它按**引擎的取图规则**逐格解码（tileId -> 图块集 + 格子），
所以「渲染出来是对的」和「游戏里是对的」是同一件事：
只要这份图没错位、没空洞、没串图，游戏里就不会有。

用法：python tools/render_map.py [地图id...]      缺省渲染全部
"""
import json
import os
import sys
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from build_tiles import cell_of

TILE = 48
TILESETS = os.path.join(ROOT, "CuzhiDemo", "img", "tilesets")
DATA = os.path.join(ROOT, "CuzhiDemo", "data")
OUT = os.path.join(ROOT, "docs", "accept")
# tileId 号段 -> 图块集名（A1..A4 是本工程的透明占位，画出来等于没画）
RANGES = [(0, 256, "Ming_B"), (256, 512, "Ming_C"), (512, 768, "Ming_D"),
          (768, 1024, "Ming_E"), (1536, 1664, "Ming_A5")]

_cache = {}


def sheet_of(tid):
    for lo, hi, name in RANGES:
        if lo <= tid < hi:
            return name
    return None


def tile_img(sheet, tid):
    if sheet not in _cache:
        _cache[sheet] = Image.open(os.path.join(TILESETS, sheet + ".png")).convert("RGBA")
    c, r = cell_of(sheet, tid)
    return _cache[sheet].crop((c * TILE, r * TILE, c * TILE + TILE, r * TILE + TILE))


def render(mid):
    m = json.load(open(os.path.join(DATA, "Map%03d.json" % mid), encoding="utf-8"))
    w, h, data = m["width"], m["height"], m["data"]
    cv = Image.new("RGBA", (w * TILE, h * TILE), (0, 0, 0, 255))
    for z in range(6):
        for y in range(h):
            for x in range(w):
                tid = data[(z * h + y) * w + x]
                if not tid:
                    continue
                sh = sheet_of(tid)
                if not sh:
                    continue
                im = tile_img(sh, tid)
                # 必须带 mask：物件图块四周是真透明，不带遮罩会把透明像素的
                # alpha=0 直接写进画布，最后 convert("RGB") 一压就成黑框。
                cv.paste(im, (x * TILE, y * TILE), im)

    ov = Image.new("RGBA", cv.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for e in m["events"]:
        if not e:
            continue
        x, y = e["x"] * TILE, e["y"] * TILE
        d.rectangle([x + 2, y + 2, x + TILE - 3, y + TILE - 3], outline=(255, 40, 40, 230), width=3)
        d.rectangle([x + 2, y + h * 0 + TILE - 18, x + TILE - 3, y + TILE - 3], fill=(255, 40, 40, 200))
        d.text((x + 6, y + TILE - 16), e["name"], fill=(255, 255, 255, 255))
    out = Image.alpha_composite(cv, ov).convert("RGB")
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "map%d_%s.png" % (mid, m["displayName"]))
    out.save(p)

    # 空洞自检：z0 为 0 的格子 = 引擎会画黑的地方
    holes = [(x, y) for y in range(h) for x in range(w) if not data[y * w + x]]
    print("M%d「%s」 %dx%d  ->  %s" % (mid, m["displayName"], w, h, os.path.relpath(p, ROOT)))
    print("     z0 空洞 %d 格 %s" % (len(holes), holes[:12] if holes else ""))
    return not holes


if __name__ == "__main__":
    ids = [int(a) for a in sys.argv[1:]] or [1]
    ok = all(render(i) for i in ids)
    print("自检：%s" % ("通过（无 z0 空洞）" if ok else "**失败 —— 有格子没铺地面**"))
    sys.exit(0 if ok else 1)
