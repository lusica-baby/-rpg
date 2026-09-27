# -*- coding: utf-8 -*-
"""把一张立绘集切成逐格、统一高度并排 —— 用来判断它到底是什么规格。

为什么需要这个工具：光看整张原图**会判错**。第一版我按整张缩略图看，
以为行 2/3 的格子里有腿有靴，判成「全身行走图」；把每格按自己的前景
包围盒裁紧、统一到同一高度再并排，才看清全是**半身胸像、没有腿**。
统一高度这一步是关键 —— 各格原尺寸差得远（这里 273 / 345 / 239），
不统一就只能靠脑补比大小。

用途：一张群像表到手，先跑这个看它是 MZ 行走图（3 列 x 4 行）、
MZ 脸图（4 列 x 2 行）还是「一格一个人物」的立绘集。都不是，就只能逐格挑。

用法：
    python tools/preview_portrait_sheet.py <原图路径> <输出名>
    python tools/preview_portrait_sheet.py            # 跑内置的两张
"""
import os
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import label_portraits as lp   # noqa: E402

OUT_DIR = os.path.join(ROOT, "docs", "accept", "portraits")
H = 420          # 每格统一到这个高度
COLS = 4

try:
    FONT = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 30)
    FONT_S = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22)
except OSError:
    FONT = FONT_S = ImageFont.load_default()


def tight_cells(path):
    """按 label_portraits 的切法取格，再按各自前景包围盒裁紧"""
    src = Image.open(path).convert("RGB")
    cols, rows = lp.locate(src)
    out = []
    n = 0
    for r, (ry0, ry1) in enumerate(rows):
        for c, (cx0, cx1) in enumerate(cols):
            art = src.crop((cx0, ry0, cx1, ry1))
            m = lp.fg_mask(art)
            if m.size == 0 or m.mean() < 0.03:
                continue
            ys, xs = np.where(m)
            art = art.crop((int(xs.min()), int(ys.min()),
                            int(xs.max()) + 1, int(ys.max()) + 1))
            n += 1
            out.append((n, r + 1, c + 1, art))
    return src, out


def render(path, out_name):
    src, cells = tight_cells(path)
    if not cells:
        print("  %s -> 没切出任何格" % os.path.basename(path))
        return
    big = [(n, r, c, a, a.resize((max(1, int(a.width * H / a.height)), H), Image.LANCZOS))
           for n, r, c, a in cells]
    CW = max(b.width for *_, b in big) + 20
    RH = H + 78
    nrow = (len(big) + COLS - 1) // COLS
    cv = Image.new("RGB", (COLS * CW + 12, nrow * RH + 12), (24, 24, 28))
    d = ImageDraw.Draw(cv)
    for n, r, c, art, b in big:
        x = 6 + ((n - 1) % COLS) * CW
        y = 6 + ((n - 1) // COLS) * RH
        cv.paste(b, (x + (CW - b.width) // 2, y + 60))
        d.text((x, y), "%d   R%dC%d" % (n, r, c), fill=(255, 225, 120), font=FONT)
        d.text((x, y + 32), "bbox %dx%d" % (art.width, art.height),
               fill=(180, 220, 255), font=FONT_S)
        d.line([(x, y + 58), (x + CW - 4, y + 58)], fill=(90, 90, 100), width=1)
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, out_name)
    cv.save(p)
    print("  %s -> %s  %s  共 %d 格" % (os.path.basename(path), out_name, cv.size, len(cells)))
    for n, r, c, a in cells:
        print("      %2d  R%dC%d  bbox %3dx%-4d" % (n, r, c, a.width, a.height))


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        render(sys.argv[1], sys.argv[2])
    else:
        render(os.path.join(lp.CLIP, "clipboard-2026-09-22T12-53-34-831Z-84336e89.jpg"),
               "01-逐格.png")
