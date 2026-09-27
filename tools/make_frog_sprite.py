"""把单张蛤蟆像素图转成 RPG Maker MZ 可用的单角色行走图。

MZ 行走图规格：
  - `$` 前缀 = 单角色（区别于 `!` 的对象图与普通 8 角色图）
  - 布局 3 列 × 4 行 = 12 帧；列 = 行走动画 3 帧，行 = 下/左/右/上 四方向
  - 每帧 48×48，故成品 144×192
  - 角色须画在帧的底部（脚踩格子），背景必须透明

输入是带纯色背景的截图，所以要先整体去背再缩放。

用法：
    python make_frog_sprite.py <源图> <输出 $Frog.png> [--preview <预览图>]
"""

import sys
import os
from collections import deque

from PIL import Image

FRAME = 48
COLS, ROWS = 3, 4
BG_SAMPLE = (104, 90, 122)   # 源图四角实测背景色
BG_THRESH = 60               # 与背景色的最大通道差，小于此值且连通才判为背景
WIDTH_RATIO = 0.92           # 蛤蟆宽度占帧宽比例，留出边距
BOTTOM_MARGIN = 2            # 距帧底部留白像素


def flood_mask(im, bg, thresh):
    """从四边向内扩散，只吃掉与背景色接近的连通区域。"""
    w, h = im.size
    px = im.load()
    seen = [[False] * w for _ in range(h)]
    q = deque()

    def close(c):
        return max(abs(c[i] - bg[i]) for i in range(3)) < thresh

    for x in range(w):
        for y in (0, h - 1):
            if not seen[y][x] and close(px[x, y]):
                seen[y][x] = True
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if not seen[y][x] and close(px[x, y]):
                seen[y][x] = True
                q.append((x, y))

    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and close(px[nx, ny]):
                seen[ny][nx] = True
                q.append((nx, ny))
    return seen


def bleed_transparent_rgb(im, transparent, rounds=6):
    """把透明像素的 rgb 换成最近可见像素的颜色。

    Pillow 缩放 RGBA 时对四个通道独立插值，透明区残留的底色会被混进可见边缘。
    本例中底色是紫色，于是蛤蟆右侧凭空多出一条紫边。先把透明区 rgb 填成邻近
    真实颜色再缩放，污染就变成了蛤蟆自己的颜色，肉眼不可见。
    """
    w, h = im.size
    px = im.load()
    known = [[not transparent[y][x] for x in range(w)] for y in range(h)]
    for _ in range(rounds):
        nxt = [row[:] for row in known]
        for y in range(h):
            for x in range(w):
                if known[y][x]:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and known[ny][nx]:
                        r, g, b, _ = px[nx, ny]
                        px[x, y] = (r, g, b, 0)
                        nxt[y][x] = True
                        break
        known = nxt


def trim_and_scale(src_path):
    im = Image.open(src_path).convert("RGBA")
    w, h = im.size
    mask = flood_mask(im, BG_SAMPLE, BG_THRESH)

    px = im.load()
    for y in range(h):
        for x in range(w):
            if mask[y][x]:
                r, g, b, _ = px[x, y]
                px[x, y] = (r, g, b, 0)

    bleed_transparent_rgb(im, mask)
    bbox = im.getbbox()
    if bbox is None:
        raise SystemExit("去背后整张图都是透明的，阈值需要调整")
    sprite = im.crop(bbox)

    tw = int(FRAME * WIDTH_RATIO)
    th = max(1, round(sprite.height * tw / sprite.width))
    if th > FRAME - BOTTOM_MARGIN:
        th = FRAME - BOTTOM_MARGIN
        tw = max(1, round(sprite.width * th / sprite.height))
    sprite = sprite.resize((tw, th), Image.LANCZOS)
    return sprite, bbox


def build_sheet(sprite):
    sheet = Image.new("RGBA", (FRAME * COLS, FRAME * ROWS), (0, 0, 0, 0))
    ox = (FRAME - sprite.width) // 2
    oy = FRAME - BOTTOM_MARGIN - sprite.height
    for row in range(ROWS):
        for col in range(COLS):
            sheet.paste(sprite, (col * FRAME + ox, row * FRAME + oy), sprite)
    return sheet


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    src, out = sys.argv[1], sys.argv[2]
    preview = None
    if "--preview" in sys.argv:
        preview = sys.argv[sys.argv.index("--preview") + 1]

    sprite, bbox = trim_and_scale(src)
    sheet = build_sheet(sprite)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    sheet.save(out)

    print("source        :", os.path.basename(src), Image.open(src).size)
    print("bbox after cut:", bbox)
    print("sprite size   :", sprite.size)
    print("sheet size    :", sheet.size, "(expect 144x192)")
    print("saved         :", out)

    if preview:
        S = 4
        big = sheet.resize((sheet.width * S, sheet.height * S), Image.NEAREST)
        big.save(preview)
        print("preview (x4)  :", preview)


if __name__ == "__main__":
    main()
