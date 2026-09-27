# -*- coding: utf-8 -*-
"""把用户给的群像表切成逐格编号的对照图，供人工辨认「第几格是谁」。

为什么不用等分网格：这些图是 AI 生成的拼图，格子间距并不严格等宽
（#2 第二行只有 3 格、右半边留白），而且角色宽袖会互相贴边。
所以用**投影找空白间隔**来定位每格的真实边界，再按边界裁剪编号。
"""
import os
import sys
import numpy as np
from PIL import Image, ImageDraw

# 剪贴板图片目录每台机器不一样，用环境变量指；默认值是本机那套。
CLIP = os.environ.get("PORTRAIT_CLIP", r"C:\Users\lenovo\.workbuddy\clipboard-images")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "accept", "portraits")
TAG = 8                      # 像素值低于「背景中位数 - TAG」视为前景
# 连续多少列/行没有前景才算分隔。这个值必须够大：角色自己的宽袖/帽翅之间
# 也会有 10~20px 的窄缝，gap 取小了会把一个角色劈成两半（实测 gap=10 时
# #9 的 3 行被劈成 7 行）。40 是扫过 10/20/30/40/60/80 后与目视完全一致的值。
GAP = 40


def fg_mask(im, tag=TAG):
    """前景遮罩：用「与背景色的偏离度」判定。

    背景是淡灰棋盘格（压成 jpg 后有噪点），角色是彩色的深色块。
    基准取「最亮 10% 的中位数」= 棋盘格白格；另外彩色度（通道极差）也是
    强信号 —— 棋盘格几乎无彩，而角色的衣袍一定有色。
    """
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    if a.size == 0:
        return np.zeros(a.shape[:2], bool)
    lum = a.mean(axis=2)
    bg = np.median(lum[lum > np.percentile(lum, 90)])   # 白格
    sat = a.max(axis=2) - a.min(axis=2)
    return (lum < bg - tag) | (sat > 28)


def runs(proj, gap=GAP, min_len=20):
    """一维投影里被 >=gap 个零隔开的段"""
    on = proj > 0
    out, s = [], None
    for i in range(len(on) + 1):
        v = on[i] if i < len(on) else False
        if v and s is None:
            s = i
        elif not v and s is not None:
            out.append([s, i])
            s = None
    # 把「中间断了一小截」的段并回去（宽袖遮挡会让某几列投影为 0）
    merged = []
    for seg in out:
        if merged and seg[0] - merged[-1][1] < gap:
            merged[-1][1] = seg[1]
        else:
            merged.append(seg)
    return [(a, b) for a, b in merged if b - a >= min_len]


def locate(im):
    """返回 (列区间列表, 行区间列表)"""
    m = fg_mask(im)
    cols = runs(m.sum(axis=0), GAP)
    rows = runs(m.sum(axis=1), GAP)
    return cols, rows


def longest_span(proj, frac=0.5):
    """一维投影里最长的一段连续非零，返回 (起点, 终点)。

    用来把一个格子的包围盒收到「角色主体」上：按 row/col run 切出来的格子里，
    经常粘着邻居行的一小条脚或帽翅（行间隙在那一列恰好不足 GAP）。
    主体在投影上是一大段连续非零，那些碎边则是独立的小段，直接丢掉即可。
    兜底：段长不足全长的 frac 时认为主体本身就是断的，退回全范围。
    """
    on = proj > 0
    best, s = None, None
    for i in range(len(on) + 1):
        v = on[i] if i < len(on) else False
        if v and s is None:
            s = i
        elif not v and s is not None:
            if best is None or i - s > best[1] - best[0]:
                best = (s, i)
            s = None
    if best is None or best[1] - best[0] < frac * len(on):
        return 0, len(on)
    return best


def render(path, label, cw=340, pad=18):
    im = Image.open(path).convert("RGB")
    cols, rows = locate(im)
    print("%s  %s  检出 %d 列 x %d 行" % (label, os.path.basename(path), len(cols), len(rows)))

    n = 0
    cells = []
    for r, (ry0, ry1) in enumerate(rows):
        for c, (cx0, cx1) in enumerate(cols):
            art = im.crop((cx0, ry0, cx1, ry1))
            if art.width < 2 or art.height < 2:
                continue
            # 该格内可能没东西（比如 #2 第二行右半边留白）—— 用前景占比过滤
            mm = fg_mask(art)
            if mm.size == 0 or mm.mean() < 0.03:
                continue
            # 行方向收碎边（邻居行的脚/帽翅），列方向保持原区间：
            # 帽翅、斗笠这些是**与主体左右分离**的部分，列投影上自成一段，
            # 在列方向取 longest_span 会把它们当碎边剪掉（实测斗笠被削平）。
            y0, y1 = longest_span(mm.sum(axis=1))
            art = art.crop((0, y0, art.width, y1))
            art.thumbnail((cw - 2 * pad, cw - 2 * pad), Image.LANCZOS)
            n += 1
            cells.append((r, c, n, art))

    COLS = max(c for _, c, _, _ in cells) + 1
    grid_h = {}
    for r, c, i, _ in cells:
        grid_h[r] = max(grid_h.get(r, 0), _.height)
    row_y, y = {}, 0
    for r in sorted(grid_h):
        row_y[r] = y + 30
        y += grid_h[r] + 30 + 26

    cv = Image.new("RGB", (COLS * cw, y + 30), (34, 34, 40))
    d = ImageDraw.Draw(cv)
    for r, c, i, art in cells:
        x, yy = c * cw, row_y[r]
        bg = Image.new("RGB", (cw - 2 * pad + 8, art.height + 8), (248, 248, 250))
        bg.paste(art, (4, 4))
        cv.paste(bg, (x + pad - 4, yy - 4))
        d.rectangle([x + pad - 5, yy - 5, x + pad + bg.width - 4, yy + bg.height - 4],
                    outline=(120, 120, 132))
        d.text((x + pad, yy + art.height + 10), "#%d   R%dC%d" % (i, r + 1, c + 1),
               fill=(255, 214, 102))
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, label + ".png")
    cv.save(dst)
    print("   -> %s  (%d 格, %dx%d)" % (dst, len(cells), cv.width, cv.height))
    return dst


if __name__ == "__main__":
    TARGETS = [
        ("01-831-84336e89", "clipboard-2026-09-22T12-53-34-831Z-84336e89.jpg"),
        ("02-833-d9d26d68", "clipboard-2026-09-22T12-53-34-833Z-d9d26d68.jpg"),
        ("09-842-f7913b71", "clipboard-2026-09-22T12-53-34-842Z-f7913b71.jpg"),
        ("11-846-9e1de04f", "clipboard-2026-09-22T12-53-34-846Z-9e1de04f.jpg"),
    ]
    for label, fn in TARGETS:
        p = os.path.join(CLIP, fn)
        assert os.path.exists(p), "缺图：%s" % p
        render(p, label)
