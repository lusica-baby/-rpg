# -*- coding: utf-8 -*-
"""把转换好的素材拼成两张预览：脸图 + 行走图（行走图放大并标出 MZ 的四行朝向）。"""
import os
from PIL import Image, ImageDraw

R = r"C:\Users\lenovo\WorkBuddy\2026-09-22-19-16-43\rpgmaker-ai-pipeline"
FACES = [("ChengMing", "成名"), ("ChengZi", "成子"), ("Youth", "村中少年")]
CHARS = [("$ChengMing", "成名"), ("$ChengZi", "成子"), ("$LiXu", "里胥"),
         ("$Witch", "驼背巫"), ("$Zai", "宰"), ("$Guard", "差役(备用)")]
MZ_ROWS = ["DOWN 下", "LEFT 左", "RIGHT 右", "UP 上"]

# ---------- 脸图 ----------
DARK = (42, 39, 50)
PAD, LABEL = 12, 26
S = 1
W = PAD * 2 + 576 * S
H = PAD + len(FACES) * (288 * S + LABEL + PAD)
c1 = Image.new("RGB", (W, H), DARK)
d1 = ImageDraw.Draw(c1)
y = PAD
for key, disp in FACES:
    im = Image.open(os.path.join(R, "assets", "img", "faces", key + ".png")).convert("RGBA")
    if S != 1:
        im = im.resize((im.width * S, im.height * S), Image.NEAREST)
    bg = Image.new("RGB", im.size, (230, 228, 236))
    bg.paste(im, (0, 0), im)
    c1.paste(bg, (PAD, y + LABEL))
    for i in range(5):
        d1.line([(PAD + i * 144 * S, y + LABEL), (PAD + i * 144 * S, y + LABEL + 288 * S)],
                fill=(140, 126, 168))
    for j in range(3):
        d1.line([(PAD, y + LABEL + j * 144 * S), (PAD + 576 * S, y + LABEL + j * 144 * S)],
                fill=(140, 126, 168))
    d1.text((PAD, y + 6), "faces/%s.png  (%s)" % (key, disp), fill=(238, 230, 248))
    y += 288 * S + LABEL + PAD
out1 = os.path.join(R, "docs", "素材对照-脸图成品.png")
c1.save(out1)
print("wrote", out1, c1.size)

# ---------- 行走图 ----------
Z = 3
CW, CH = 144 * Z, 192 * Z
GAP = 26
W2 = PAD * 2 + 3 * (CW + GAP)
H2 = PAD + 2 * (CH + LABEL + GAP)
c2 = Image.new("RGB", (W2, H2), DARK)
d2 = ImageDraw.Draw(c2)
for i, (key, disp) in enumerate(CHARS):
    r, c = divmod(i, 3)
    p = os.path.join(R, "assets", "img", "characters", key + ".png")
    im = Image.open(p).convert("RGBA").resize((CW, CH), Image.NEAREST)
    # 每行一块浅色底，方便看清行边界
    bg = Image.new("RGB", (CW, CH), (232, 230, 238))
    bg.paste(im, (0, 0), im)
    x = PAD + c * (CW + GAP)
    yy = PAD + r * (CH + LABEL + GAP) + LABEL
    c2.paste(bg, (x, yy))
    for j in range(1, 4):
        d2.line([(x, yy + j * 48 * Z), (x + CW, yy + j * 48 * Z)], fill=(120, 180, 240), width=1)
    for j in range(4):
        d2.text((x + 4, yy + j * 48 * Z + 3), MZ_ROWS[j][:4], fill=(30, 60, 110))
    d2.text((x, yy - 20), "%s.png  (%s)  %dx%d" % (key, disp, im.width, im.height),
            fill=(238, 230, 248))
out2 = os.path.join(R, "docs", "素材对照-行走图成品.png")
c2.save(out2)
print("wrote", out2, c2.size)
