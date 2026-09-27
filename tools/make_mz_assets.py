# -*- coding: utf-8 -*-
"""把 AI 生成的素材图转成 RPG Maker MZ 能用的规格。

素材现状（实测，决定了这里为什么这么写）：
  * 全是 JPEG、RGB、**无 alpha**。背景是"画上去的棋盘格"，不是真透明。
  * 所以不能按颜色阈值直接抠图 —— 角色身上有白衣、白靴、白脸高光，会被一起抠掉。
    必须用**从四边出发的连通域洪泛**：只删与画面边缘连通的那片背景。
  * 右下角有"豆包AI生成"水印，需在洪泛前抹掉。
  * 脸图恰好 4 列 2 行 = 8 张，与 MZ 的 faces 规格（576×288，单张 144×144）一致。
  * 行走图是 4 列 2~3 行，MZ 要的是 3 列 4 行，**列数不符且缺"朝上"那一行**。

子命令：
    faces  <src.jpg> <out.png>                      # 固定 4×2 → 576×288
    chars  <src.jpg> <out.png> --src-rows N --src-order DOWN,LEFT,RIGHT
"""

import os
import sys
from collections import deque

from PIL import Image

# MZ 行走图的行序是写死的，由引擎 (direction - 2) / 2 决定，不能改
MZ_ROWS = ["DOWN", "LEFT", "RIGHT", "UP"]

# --- 去背参数 ---------------------------------------------------------------
# mn 是 RGB 三通道的最小值。棋盘格的两种灰都在 230+，角色最亮的白靴约 240 但
# 被深色描边围着，不参与边缘连通，所以安全。
BG_MIN_CHANNEL = 190   # 三通道都高于此值才可能是背景
BG_MAX_SPREAD = 16     # 且三通道差值小于此值（背景是中性灰，不含彩色）

WATERMARK_W = 320      # 右下角水印矩形（原图尺度）
WATERMARK_H = 84


def is_background(c):
    r, g, b = c[0], c[1], c[2]
    return min(r, g, b) > BG_MIN_CHANNEL and (max(r, g, b) - min(r, g, b)) < BG_MAX_SPREAD


def erase_watermark(im):
    """把右下角一片矩形涂成背景色，让随后的洪泛把它一并吃掉。"""
    w, h = im.size
    x0, y0 = max(0, w - WATERMARK_W), max(0, h - WATERMARK_H)
    px = im.load()
    for y in range(y0, h):
        for x in range(x0, w):
            px[x, y] = (246, 246, 246)
    return im


def cut_frames(src_path, cols, rows, watermark=True):
    """把整图等分成 cols×rows 格，逐格去背，返回 RGBA 帧列表（行优先）。"""
    im = Image.open(src_path).convert("RGB")
    if watermark:
        im = erase_watermark(im)
    W, H = im.size
    cw, ch = W // cols, H // rows
    frames = []
    for r in range(rows):
        for c in range(cols):
            box = (c * cw, r * ch, (c + 1) * cw, (r + 1) * ch)
            frames.append(_strip_bg(im.crop(box)))
    return frames, (cw, ch)


def _strip_bg(tile):
    """从四条边洪泛，删掉与边缘连通的背景。保留被描边围住的白（衣、靴、脸）。"""
    tile = tile.convert("RGBA")
    w, h = tile.size
    px = tile.load()

    seen = bytearray(w * h)
    q = deque()

    def push(x, y):
        i = y * w + x
        if not seen[i] and is_background(px[x, y]):
            seen[i] = 1
            q.append((x, y))

    for x in range(w):
        push(x, 0)
        push(x, h - 1)
    for y in range(h):
        push(0, y)
        push(w - 1, y)

    while q:
        x, y = q.popleft()
        if x > 0:
            push(x - 1, y)
        if x < w - 1:
            push(x + 1, y)
        if y > 0:
            push(x, y - 1)
        if y < h - 1:
            push(x, y + 1)

    for y in range(h):
        row = y * w
        for x in range(w):
            if seen[row + x]:
                px[x, y] = (0, 0, 0, 0)
    return tile


def content_bbox(frame):
    return frame.getchannel("A").getbbox()


def fit_into(frame, box_w, box_h, anchor="bottom"):
    """按 alpha 裁边后等比缩放，放进 box_w×box_h 的透明画布。"""
    bb = content_bbox(frame)
    canvas = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    if bb is None:
        return canvas, None
    sprite = frame.crop(bb)
    ratio = min(box_w / sprite.width, box_h / sprite.height)
    nw = max(1, int(round(sprite.width * ratio)))
    nh = max(1, int(round(sprite.height * ratio)))
    sprite = sprite.resize((nw, nh), Image.LANCZOS)
    x = (box_w - nw) // 2
    y = box_h - nh if anchor == "bottom" else (box_h - nh) // 2
    canvas.paste(sprite, (x, y), sprite)
    return canvas, bb


# --- faces -----------------------------------------------------------------
def build_faces(src, out, cols=4, rows=2, cell=144):
    frames, size = cut_frames(src, cols, rows)
    print("源格尺寸 %dx%d，共 %d 帧" % (size[0], size[1], len(frames)))
    sheet = Image.new("RGBA", (cell * 4, cell * 2), (0, 0, 0, 0))
    for i in range(min(8, len(frames))):
        fitted, bb = fit_into(frames[i], cell, cell, anchor="center")
        sheet.paste(fitted, ((i % 4) * cell, (i // 4) * cell), fitted)
        print("  帧%-2d bbox=%s" % (i, bb))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    sheet.save(out)
    print("写出 %s  %dx%d" % (out, sheet.width, sheet.height))


# --- chars ------------------------------------------------------------------
def build_chars(src, out, src_rows, src_order, cell=48, pick=3, col=None):
    """src_order 说明源图每一排画的是哪个朝向，例如 "DOWN,LEFT,LEFT"。

    素材只有三视图，MZ 却要四排（下左右上），于是：

      * **RIGHT 用 LEFT 的水平镜像**。像素风镜像无损，比「拿正面顶替」贴近真实朝向。
      * UP 确实没有背面素材，只能用 DOWN 顶替 —— 角色朝上走时显示正面。
        这是降级，引擎不校验，视觉上能接受。

    col 用于「列=角色」的素材：有些图把多个角色的三视图拼在一起，列才是角色、
    行是朝向，这时只抽指定列。
    """
    frames, size = cut_frames(src, 4, src_rows)
    if col is None:
        rows = [[frames[r * 4 + c] for c in range(4)] for r in range(src_rows)]
        layout = "%d 排 × 4 列（列=动画帧）" % src_rows
    else:
        rows = [[frames[r * 4 + col]] for r in range(src_rows)]
        layout = "%d 排 × 第 %d 列（列=角色）" % (src_rows, col)
    print("源格尺寸 %dx%d，%s" % (size[0], size[1], layout))

    def resolve(direction):
        if direction in src_order:
            i = src_order.index(direction)
            return rows[i], "源排%d" % i, False
        if direction == "RIGHT" and "LEFT" in src_order:
            i = src_order.index("LEFT")
            return rows[i], "源排%d 镜像" % i, True
        i = src_order.index("DOWN")
        return rows[i], "源排%d 顶替（无背面素材）" % i, False

    sheet = Image.new("RGBA", (cell * 3, cell * 4), (0, 0, 0, 0))
    for d, name in enumerate(MZ_ROWS):
        frameset, note, mirror = resolve(name)
        if len(frameset) < pick:                    # 单帧素材：复制成 pick 帧
            frameset = (frameset * pick)[:pick]
        for c in range(pick):
            fitted, _ = fit_into(frameset[c], cell, cell, anchor="bottom")
            if mirror:
                fitted = fitted.transpose(Image.FLIP_LEFT_RIGHT)
            sheet.paste(fitted, (c * cell, d * cell), fitted)
        print("  行%d %-5s <- %s" % (d, name, note))

    os.makedirs(os.path.dirname(out), exist_ok=True)
    sheet.save(out)
    print("写出 %s  %dx%d" % (out, sheet.width, sheet.height))


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        return 1
    mode, src, out = sys.argv[1], sys.argv[2], sys.argv[3]
    argv = sys.argv[4:]

    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default

    if mode == "faces":
        build_faces(src, out, int(opt("--cols", 4)), int(opt("--rows", 2)),
                    int(opt("--cell", 144)))
    elif mode == "chars":
        col = opt("--col")
        build_chars(src, out,
                    int(opt("--src-rows", 3)),
                    opt("--src-order", "DOWN,LEFT,LEFT").split(","),
                    int(opt("--cell", 48)),
                    int(opt("--pick", 3)),
                    int(col) if col is not None else None)
    else:
        print("未知模式:", mode)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
