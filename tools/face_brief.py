# -*- coding: utf-8 -*-
"""脸图清单 —— 从 game_data.CAST 生成两张给美术看的图

为什么要有这个：角色名册（CAST）是唯一真源，但「谁缺脸图」必须拿磁盘上的实际
文件去核，不能凭印象。所以这里一边读 CAST，一边扫 assets/img/{characters,faces}/，
两侧对不上就报出来（行走图缺 = 更严重的错，直接断言）。

产出（都在 docs/accept/portraits/）：
  脸图缺口清单.png   每个角色一行：行走图 / 脸图有无 / 造型提示
  脸图规格.png       画布多大、怎么构图、命名怎么给

用法：python tools/face_brief.py
"""
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game_data as G  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_CHAR = os.path.join(ROOT, "assets", "img", "characters")
DIR_FACE = os.path.join(ROOT, "assets", "img", "faces")
OUT_DIR = os.path.join(ROOT, "docs", "accept", "portraits")

FONT_PATH = "C:/Windows/Fonts/msyh.ttc"
INK = (28, 30, 38, 255)
DIM = (120, 126, 140, 255)
RED = (176, 42, 42, 255)
GREEN = (32, 122, 82, 255)
LINE = (206, 210, 220, 255)
CARD = (252, 252, 254, 255)
WARN = (255, 243, 240, 255)
OKBG = (243, 250, 246, 255)


def font(size):
    if not os.path.exists(FONT_PATH):
        raise SystemExit("缺中文字体 %s，装了微软雅黑再跑" % FONT_PATH)
    return ImageFont.truetype(FONT_PATH, size)


# 折行的最小单位：要么是一整个英文/路径 token（不能被劈成 "assets/i" + "mg/faces/"），
# 要么是单个汉字。逐字符量宽度会把路径和 python 命令切得没法读。
TOKEN = re.compile(r"[A-Za-z0-9_\-/.,]+|\s+|.", re.S)


def wrap(draw, text, fnt, max_w):
    """按像素宽度折行。中英混排：汉字逐字断，ASCII 词整块搬。"""
    lines, cur = [], ""
    for tok in TOKEN.findall(text):
        if draw.textlength(cur + tok, font=fnt) <= max_w:
            cur += tok
            continue
        if cur.strip():
            lines.append(cur.rstrip())
        cur = "" if tok.isspace() else tok
        while draw.textlength(cur, font=fnt) > max_w:  # 单个 token 比整行还宽，只能硬切
            cut = len(cur)
            while cut > 1 and draw.textlength(cur[:cut], font=fnt) > max_w:
                cut -= 1
            lines.append(cur[:cut])
            cur = cur[cut:]
    if cur.strip():
        lines.append(cur.rstrip())
    return lines


def dashed_rect(d, box, color, dash=10, gap=6, width=2):
    x0, y0, x1, y1 = box
    for x in range(x0, x1, dash + gap):
        d.line([(x, y0), (min(x + dash, x1), y0)], fill=color, width=width)
        d.line([(x, y1), (min(x + dash, x1), y1)], fill=color, width=width)
    for y in range(y0, y1, dash + gap):
        d.line([(x0, y), (x0, min(y + dash, y1))], fill=color, width=width)
        d.line([(x1, y), (x1, min(y + dash, y1))], fill=color, width=width)


def thumb(path, size, cell):
    """从素材表里抠第 0 格，贴到白底上再返回 —— 直接 alpha_composite 到整图会把
    透明区留成背景色，看图时分不清「素材本身是透明底」和「我贴歪了」。"""
    im = Image.open(path).convert("RGBA").crop((0, 0, cell, cell))
    im = im.resize((size, size), Image.NEAREST)
    bg = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    bg.alpha_composite(im)
    return bg


def build_list():
    f_title, f_head, f_name, f_hint, f_tag = font(40), font(22), font(30), font(21), font(20)
    M, NAME_W, ART_W, HINT_W, GAP = 30, 168, 136, 560, 18
    HEAD_H, ROW_H = 48, 196
    title_h = 104

    # 名册顺序即 CAST 顺序，但先列出「缺」的，做完的沉到底部
    rows = []
    for name, (walk, face, hint) in G.CAST.items():
        wp = os.path.join(DIR_CHAR, walk + ".png")
        assert os.path.exists(wp), "行走图缺失：%s（角色 %s）" % (wp, name)
        if face == "":
            state, fp = "none", None
        elif face is None:
            state, fp = "todo", None
        else:
            fp = os.path.join(DIR_FACE, face + ".png")
            if not os.path.exists(fp):
                raise SystemExit("CAST 说 %s 有脸图 %s，但文件不在" % (name, face))
            state = "have"
        rows.append((name, walk, face, hint, fp, state))
    # 待画的最上面 —— 那是要找美术要的；已挂载次之；明确不配的沉底
    rows.sort(key=lambda r: {"todo": 0, "have": 1, "none": 2}[r[5]])

    W = M * 2 + NAME_W + ART_W * 2 + HINT_W + GAP * 3
    H = title_h + HEAD_H + ROW_H * len(rows) + 96 + M
    img = Image.new("RGBA", (W, H), (247, 247, 250, 255))
    d = ImageDraw.Draw(img)

    d.text((M, 30), "促织 · 脸图缺口清单", font=f_title, fill=INK)
    miss = [r[0] for r in rows if r[5] == "todo"]
    d.text((M, 78), "待画 %d 张：%s　（%d 个角色，行走图已齐）"
           % (len(miss), "、".join(miss), len(rows)),
           font=f_hint, fill=RED)

    y = title_h
    for label, x, w in [("角色", M, NAME_W), ("行走图（已有）", M + NAME_W + GAP, ART_W),
                        ("脸图 144×144", M + NAME_W + ART_W + GAP * 2, ART_W),
                        ("造型提示", M + NAME_W + ART_W * 2 + GAP * 3, HINT_W)]:
        d.text((x, y + 12), label, font=f_head, fill=DIM)
    y += HEAD_H
    d.line([(M, y), (W - M, y)], fill=LINE, width=2)

    for i, (name, walk, face, hint, fp, state) in enumerate(rows):
        bg = {"have": OKBG, "todo": WARN, "none": (243, 244, 247, 255)}[state]
        d.rectangle([M, y + 6, W - M, y + ROW_H - 6], fill=bg)
        x0 = M + NAME_W + GAP
        x1 = x0 + ART_W + GAP
        # 行走图
        box = (x1 + 8, y + 14, x1 + ART_W - 8, y + ART_W)
        img.alpha_composite(thumb(os.path.join(DIR_CHAR, walk + ".png"), ART_W - 16, 48),
                            (x0 + 8, y + 14))
        d.text((x0 + 8, y + ROW_H - 36), walk, font=f_tag, fill=DIM)
        # 脸图：三种状态各自给个一眼能分的记号
        if state == "have":
            img.alpha_composite(thumb(fp, ART_W - 16, 144), (x1 + 8, y + 14))
            d.text((x1 + 8, y + ROW_H - 36), face, font=f_tag, fill=GREEN)
        else:
            dashed_rect(d, box, RED if state == "todo" else DIM)
            mid = (box[0] + box[2]) // 2
            d.text((mid - 23, y + 52), "缺" if state == "todo" else "—",
                   font=font(46), fill=RED if state == "todo" else DIM)
            d.text((x1 + 8, y + ROW_H - 36), "待画" if state == "todo" else "不配脸图",
                   font=f_tag, fill=RED if state == "todo" else DIM)
        # 名字 + 提示
        d.text((M, y + 26), name, font=f_name, fill=INK)
        ty = y + 76
        for ln in wrap(d, hint, f_hint, HINT_W - 8)[:3]:
            d.text((M + NAME_W + ART_W * 2 + GAP * 3, ty), ln, font=f_hint, fill=INK)
            ty += 28
        y += ROW_H

    # 库存里没被任何角色引用的脸图 —— 弃用素材别悄悄躺在这儿，得写出来
    used = {r[2] for r in rows if r[2]}
    idle = sorted(n[:-4] for n in os.listdir(DIR_FACE)
                  if n.endswith(".png") and n[:-4] not in used)
    y += 14
    d.line([(M, y), (W - M, y)], fill=LINE, width=2)
    msg = ("库存未挂载的脸图：%s —— 留着给 M2「村中」的村人，不入 CAST 就不显示。"
           % "、".join(idle)) if idle else "库存里没有多余脸图。"
    for ln in wrap(d, msg, f_hint, W - M * 2):
        y += 8
        d.text((M, y), ln, font=f_hint, fill=DIM)
        y += 26

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "脸图缺口清单.png")
    img.convert("RGB").save(out)
    print("写好了", os.path.relpath(out, ROOT))
    print("缺脸图：", "、".join(miss))
    print("未挂载：", "、".join(idle) or "无")


def build_template():
    """一张 144×144 的全透明 PNG，给美术当画布底 —— 省得自己裁尺寸裁错。"""
    out = os.path.join(OUT_DIR, "脸图模板_144x144.png")
    os.makedirs(OUT_DIR, exist_ok=True)
    Image.new("RGBA", (144, 144), (0, 0, 0, 0)).save(out)
    print("写好了", os.path.relpath(out, ROOT))


def build_scale():
    """实尺对照：把每张脸按**原尺寸 144px** 并排贴出来，不缩放。

    为什么非要原尺寸看：脸图分两批 —— 老的三张取自 576x288 满表（只取左上那一格），
    新的五张就是 144x144 单格。**两批在各自 144 格里的占位不一样**，谁占得满，
    在同一个对话框里就显得大。缩放对比图会把这个差别抹掉，所以这张图不许 resize。
    """
    CELL, GAP, PAD = 144, 26, 30
    COLS = 4
    rows = []
    for name, (_walk, face, _hint) in G.CAST.items():
        if not face:
            continue
        fp = os.path.join(DIR_FACE, face + ".png")
        if not os.path.exists(fp):
            continue
        im = Image.open(fp).convert("RGBA").crop((0, 0, CELL, CELL))
        a = np.asarray(im)[:, :, 3] > 0
        bb = im.getchannel("A").getbbox()
        rows.append((name, face, im, a.mean(), bb))

    ROWS = (len(rows) + COLS - 1) // COLS
    LBL = 34
    W = PAD * 2 + COLS * CELL + (COLS - 1) * GAP
    H = 118 + ROWS * (CELL + LBL) + (ROWS - 1) * GAP + PAD
    img = Image.new("RGBA", (W, H), (247, 247, 250, 255))
    d = ImageDraw.Draw(img)
    f_title, f_note, f_tag, f_small = font(40), font(21), font(19), font(18)

    d.text((PAD, 28), "促织 · 脸图实尺对照", font=f_title, fill=INK)
    d.text((PAD, 80), "全部按 144×144 原尺寸贴出，未缩放 —— 看的是「谁在格子里占得满」",
           font=f_note, fill=DIM)

    for i, (name, face, im, cover, bb) in enumerate(rows):
        r, c = divmod(i, COLS)
        x = PAD + c * (CELL + GAP)
        y = 118 + r * (CELL + LBL + GAP)
        # 对话框底色：脸贴在窗口上，不是贴在白纸上
        d.rectangle([x, y, x + CELL, y + CELL], fill=(32, 38, 58, 255))
        img.alpha_composite(im, (x, y))
        d.rectangle([x, y, x + CELL, y + CELL], outline=LINE, width=1)
        d.text((x, y + CELL + 4), "%s  %s" % (name, face), font=f_tag, fill=INK)
        d.text((x, y + CELL + 20), "占格 %.0f%%" % (cover * 100), font=f_small,
               fill=RED if cover > 0.66 else DIM)

    out = os.path.join(OUT_DIR, "脸图实尺对照.png")
    os.makedirs(OUT_DIR, exist_ok=True)
    img.convert("RGB").save(out)
    print("写好了", os.path.relpath(out, ROOT), "%dx%d" % img.size)


def build_spec():
    """规格图：画多大、怎么构图、文件放哪。画布放大 3 倍画，实际尺寸写在标注里。

    图里不放中文 —— 432px 的框图内塞字会跟色带打架，统一改成「色块 + 右侧图例」。
    高度先按足够大建，画完再按实际用掉的高度裁掉 —— 省得去算文本折了几行。
    """
    S, CELL, M, NOTE_W = 3, 144, 30, 486
    TITLE_H = 128
    W, H_MAX = M * 2 + CELL * S + 46 + NOTE_W, 1500
    img = Image.new("RGBA", (W, H_MAX), (247, 247, 250, 255))
    d = ImageDraw.Draw(img)
    f_title, f_note, f_small = font(40), font(22), font(19)

    d.text((M, 30), "脸图规格 · RPG Maker MZ", font=f_title, fill=INK)
    d.text((M, 84), "144 × 144 px ／ PNG 透明底 ／ 只画到肩，不要下半身",
           font=f_note, fill=RED)

    # 画布示意
    x0, y0 = M, TITLE_H
    x1, y1 = x0 + CELL * S, y0 + CELL * S
    top = y0 + 8 * S
    chin = y0 + int(CELL * 0.60) * S
    d.rectangle([x0, y0, x1, y1], fill=CARD, outline=INK, width=2)
    d.rectangle([x0, y0, x1, top], fill=(255, 234, 234, 255))
    d.line([(x0, top), (x1, top)], fill=(214, 118, 118, 255), width=2)
    d.line([(x0, chin), (x1, chin)], fill=(120, 150, 214, 255), width=3)
    d.line([(x0, y1), (x1, y1)], fill=INK, width=4)
    d.line([(x0, y1 + 30), (x1, y1 + 30)], fill=DIM, width=2)
    for xx in (x0, x1):
        d.line([(xx, y1 + 22), (xx, y1 + 38)], fill=DIM, width=2)
    d.text(((x0 + x1) // 2 - 54, y1 + 38), "144 px", font=f_small, fill=DIM)

    legends = [("hband", "红带 = 头顶留白 6~10px，别贴顶"),
               ("hline", "蓝线 = 下巴线，约在 60% 高度"),
               ("edge", "底边 = 肩部出画，不要画到腰")]
    notes = [
        "先看清单图里成名 / 成妻 / 成子那三格，画风照它们来。",
        "画布 144×144，PNG，背景全透明 —— 不要白底。",
        "只画上半身，脸占画面宽 60~70%，比行走图的头略大一号。",
        "像素风、深色轮廓、明暗两级；不加白边 / 投影 / 背景色块。",
        "一张图一格就够：引擎按 index 0 取左上 144×144。",
        "给 8 格表情表（4 列 × 2 行）也行，正脸放左上第 0 格。",
        "文件名用 CAST 第二列的名字，放 assets/img/faces/。",
        "画完跑 tools/build_project.py 挂载，再跑 tools/playtest.py 看图。",
    ]
    nx = x1 + 46
    ny = TITLE_H + 6
    for key, text in legends:
        if key == "hband":
            d.rectangle([nx, ny + 3, nx + 26, ny + 19], fill=(255, 234, 234, 255),
                        outline=(214, 118, 118, 255), width=2)
        elif key == "hline":
            d.line([(nx, ny + 11), (nx + 26, ny + 11)], fill=(120, 150, 214, 255), width=4)
        else:
            d.rectangle([nx, ny + 2, nx + 26, ny + 20], fill=CARD, outline=LINE, width=1)
            d.line([(nx, ny + 17), (nx + 26, ny + 17)], fill=INK, width=4)
        for ln in wrap(d, text, f_note, NOTE_W - 46):
            d.text((nx + 38, ny), ln, font=f_note, fill=INK)
            ny += 28
        ny += 10
    ny += 10
    d.line([(nx, ny), (W - M, ny)], fill=LINE, width=2)
    ny += 18
    for t in notes:
        for ln in wrap(d, t, f_note, NOTE_W):
            d.text((nx, ny), ln, font=f_note, fill=INK)
            ny += 28
        ny += 12

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "脸图规格.png")
    img.crop((0, 0, W, max(ny + M, y1 + 96))).convert("RGB").save(out)
    print("写好了", os.path.relpath(out, ROOT))


if __name__ == "__main__":
    build_list()
    build_scale()
    build_spec()
    build_template()
