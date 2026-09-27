# -*- coding: utf-8 -*-
"""美术需求单 —— 把「还缺哪些图、每张什么规格、为什么」整理成两张给美术看的图。

和 face_brief.py 的分工：那张清单回答**有没有**，这张单子回答**要改成什么样**。
`docs/accept/portraits/脸图实尺对照.png` 只把八张脸并排放出来（客观事实），
这张单子往前一步：指出哪几张必须重画、参照哪一张、以及标题背景怎么画。

产出：
  docs/accept/标题背景规格.png        816x624 画布 + 两块禁区（引擎实测值）
  docs/accept/portraits/脸图重画需求.png  还要重画的脸，1:1 现状 + 参照 + 理由
                                        （2026-09-24 起 REDRAW 清空 —— 八张全部定稿。
                                        这张图转为「需求单」的存档格式，记录在 foot 里）

用法：python tools/art_brief.py
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game_data as G                     # noqa: E402
from face_brief import font, wrap, dashed_rect  # noqa: E402  复用折行与字体

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_FACE = os.path.join(ROOT, "assets", "img", "faces")
OUT_MAIN = os.path.join(ROOT, "docs", "accept")
OUT_PORT = os.path.join(OUT_MAIN, "portraits")

INK = (28, 30, 38, 255)
DIM = (120, 126, 140, 255)
RED = (176, 42, 42, 255)
GREEN = (32, 122, 82, 255)
LINE = (208, 212, 222, 255)
PAGE = (247, 247, 250, 255)

# 引擎实测值（.scratch/probe_title.py 量出来的，别手改）：
#   Graphics 816x624 / box 808x616 / 命令窗 x284 y364 w240 h156
#   「促织」由引擎自己画：fontSize 72 + outlineWidth 8，x=20 起、居中、y=156 高 48
T = dict(W=816, H=624, TX=20, TY=156, TH=48,
         CX=284, CY=364, CW=240, CH=156)


def checker(size, sq=12):
    """棋盘格底：透明区要跟「白色像素」区分开，不然看不出抠没抠干净。"""
    img = Image.new("RGB", (size, size), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for y in range(0, size, sq):
        for x in range(0, size, sq):
            if (x // sq + y // sq) % 2:
                d.rectangle([x, y, x + sq - 1, y + sq - 1], fill=(226, 228, 234))
    return img


def face_cell(name, size=144):
    """取脸图第 0 格贴到棋盘格上。老素材是 576x288 满表，必须裁 —— 不能整张缩放。"""
    path = os.path.join(DIR_FACE, name + ".png")
    assert os.path.exists(path), "脸图不在：%s" % path
    src = Image.open(path).convert("RGBA").crop((0, 0, 144, 144))
    bg = checker(size)
    bg.paste(src, (0, 0), src)
    return bg


def notes_h(d, items, fnt, max_w, gap=16):
    """只量高度不画 —— 右栏字数不确定，页面高度得先算出来再定，不能拍一个数。"""
    return sum(len(wrap(d, it, fnt, max_w)) * (fnt.size + 9) + gap for it in items)


def notes(d, xy, items, fnt, max_w, gap=16, fill=None):
    """编号条目左对齐排下来，返回底边 y。续行缩进 22px，跟编号拉开层级。"""
    x, y = xy
    fill = INK if fill is None else fill
    for it in items:
        for j, ln in enumerate(wrap(d, it, fnt, max_w)):
            d.text((x + (0 if j == 0 else 22), y), ln, font=fnt, fill=fill)
            y += fnt.size + 9
        y += gap
    return y


def fit_cell(path, size=144, bg=(255, 255, 255)):
    """把一张参照图等比装进正方格，白底补边。

    参照图的长宽比五花八门（成子 1444x1536、成名 1014x1426、宰的头部 691x504），
    直接 resize 会把人拉扁 —— 画脸的人照着一张变形的图去画就全错了。
    """
    src = Image.open(path).convert("RGB")
    z = min(size / src.width, size / src.height)
    im = src.resize((max(1, round(src.width * z)), max(1, round(src.height * z))),
                    Image.LANCZOS)
    out = Image.new("RGB", (size, size), bg)
    out.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    return out


# ------------------------------------------------------------------ 标题背景
def build_title():
    """标题背景规格：画布按 1:1 画出来，把「引擎自己会画什么」标在上面。

    只标两块**禁区**，不铺彩色安全区 —— 安全区一多，图就变成花花绿绿的说明书，
    反而看不清「你的画放哪」。
    """
    f_title, f_note, f_small, f_tag = font(40), font(21), font(18), font(19)
    M, ART_X, NOTE_W = 74, 74, 486
    HEAD, GAP = 152, 26
    art_x1 = ART_X + T["W"]
    nx = art_x1 + 46

    sec1 = [
        "■ 尺寸",
        "画布正好 816 × 624，PNG，不透明满幅。引擎按 max(816/宽, 624/高, 1.0) "
        "缩放后居中：小了会被放大并裁掉四边，大了被缩小 —— 只有正好这个尺寸才是 1:1。",
        "文件名随意（如 Cuzhi.png），给我之后构建器会写进 System.json 的 title1Name。",
        "可选第二层前景：title2Name 现在是空的，再给一张带透明通道的 816×624 会叠在上面。"
        "想加暗角或前景枝叶才用，非必需。",
    ]
    sec2 = [
        "■ 两块别放东西的地方",
        "红带 y=156~204：标题字是引擎画的，这条带要暗、平、无细节，"
        "否则黑描边的字会糊进背景里。",
        "蓝框 x=284~524, y=364~520：三行菜单盖住这里，画了也看不见。",
    ]
    sec3 = [
        "■ 可以放手画的地方",
        "最上面一条 y=0~150、左右两侧 x<280 与 x>530、最下面一条 y=520~624。"
        "主体放在上三分之一或两侧最稳。",
        "题材：秋夜、冷月、荒村土墙、一盏油灯、蟋蟀（剪影或陶罐）。"
        "青灰夜色 + 一点灯火的暖黄。忌高饱和，忌亮块压在红带上。",
        "现有这张是冷月 + 荒草坡，缺一只蟋蟀 —— 想补就在 title2Name 加一层前景，"
        "把蟋蟀剪影叠上去；也可以就这么留着。",
    ]
    all_notes = sec1 + sec2 + sec3
    foot_notes = [
        "左图是现在真机上的第一眼 —— 已经换成月夜那张了，右下角的水印也清掉了，"
        "这一项不用再画。留着这张单子是为了记住两块禁区的位置和尺寸。",
        "想换风格时照这两块避开即可：标题字那条带要暗、平、无细节；菜单窗那块画了也看不见。"
        "素材放 assets/img/titles1/，跑 build_project.py 挂载、playtest.py 出图验收。",
    ]

    H_notes = notes_h(ImageDraw.Draw(Image.new("RGB", (1, 1))),
                      all_notes, f_note, NOTE_W)
    THUMB_W = 256
    H_left = T["H"] + GAP + 26 + round(THUMB_W * 624 / 816) + 26
    H = HEAD + max(H_left, H_notes) + (GAP if H_notes > H_left else 0) + 34
    W = nx + NOTE_W + M
    img = Image.new("RGBA", (W, H), PAGE)
    d = ImageDraw.Draw(img)

    d.text((M, 30), "促织 · 标题背景需求", font=f_title, fill=INK)
    d.text((M, 84), "816 × 624 px ／ PNG ／ 放 assets/img/titles1/ ／ "
                    "这是别人点开链接看到的第一眼", font=f_note, fill=RED)

    # ---- 画布（1:1）----
    x0, y0 = ART_X, HEAD
    x1, y1 = x0 + T["W"], y0 + T["H"]
    d.rectangle([x0, y0, x1, y1], fill=(58, 62, 74, 255))
    d.rectangle([x0, y0, x1, y1], outline=INK, width=2)
    d.text((x0 + 14, y0 + 12), "你的画布 816 × 624（1:1 画在这里）",
           font=f_small, fill=(206, 210, 222, 255))

    for gx in range(0, T["W"] + 1, 100):          # 刻度尺
        d.line([(x0 + gx, y0 - 8), (x0 + gx, y0)], fill=DIM, width=2)
        d.text((x0 + gx - 6, y0 - 28), str(gx), font=f_small, fill=DIM)
    for gy in range(0, T["H"] + 1, 100):
        d.line([(x0 - 8, y0 + gy), (x0, y0 + gy)], fill=DIM, width=2)
        d.text((x0 - 48, y0 + gy - 9), str(gy), font=f_small, fill=DIM)

    tb = [x0 + T["TX"], y0 + T["TY"], x0 + T["TX"] + T["W"] - 40, y0 + T["TY"] + T["TH"]]
    d.rectangle(tb, fill=(176, 42, 42, 92))
    dashed_rect(d, tb, RED, dash=14, gap=8, width=3)
    d.text((tb[0] + 16, tb[1] + 13), "「促织」两个字引擎自己画在这儿（72px + 8px 黑描边）",
           font=f_tag, fill=(255, 228, 228, 255))

    cb = [x0 + T["CX"], y0 + T["CY"], x0 + T["CX"] + T["CW"], y0 + T["CY"] + T["CH"]]
    d.rectangle(cb, fill=(48, 96, 184, 160))
    dashed_rect(d, cb, (162, 198, 255, 255), dash=14, gap=8, width=3)
    d.text((cb[0] + 12, cb[1] + 12), "菜单窗", font=f_tag, fill=(232, 240, 255, 255))
    d.text((cb[0] + 12, cb[1] + 38), "240 × 156", font=f_small, fill=(214, 228, 255, 255))

    # ---- 左栏页脚：现在长什么样 ----
    fy = y1 + GAP + 26
    d.line([(ART_X, fy - 14), (art_x1, fy - 14)], fill=LINE, width=2)
    shot = os.path.join(OUT_MAIN, "m1", "01-title.png")
    if os.path.exists(shot):
        s = Image.open(shot).convert("RGB")
        s = s.resize((THUMB_W, round(THUMB_W * s.size[1] / s.size[0])))
        img.paste(s, (ART_X, fy))
        d.rectangle([ART_X, fy, ART_X + s.size[0], fy + s.size[1]], outline=DIM, width=2)
        d.text((ART_X, fy + s.size[1] + 6), "现在：01-title.png（月夜已上线）",
               font=f_small, fill=DIM)
        notes(d, (ART_X + s.size[0] + 30, fy + 4), foot_notes, f_note,
              art_x1 - ART_X - s.size[0] - 30, gap=10)
    else:
        notes(d, (ART_X, fy), foot_notes, f_note, T["W"], gap=10)

    # ---- 右栏 ----
    ny = HEAD
    ny = notes(d, (nx, ny), sec1, f_note, NOTE_W)
    ny = notes(d, (nx, ny), sec2, f_note, NOTE_W)
    notes(d, (nx, ny), sec3, f_note, NOTE_W)

    os.makedirs(OUT_MAIN, exist_ok=True)
    out = os.path.join(OUT_MAIN, "标题背景规格.png")
    img.convert("RGB").save(out)
    print("写好了", os.path.relpath(out, ROOT), img.size)


# ------------------------------------------------------------------ 脸图重画
# 每行：角色 / 现状文件 / 笔法样板 / 形象参照图 / 为什么 / 提示词
#
# 「笔法样板」和「形象参照」是两件事，别合并：
#   笔法样板（成妻）管**怎么画** —— 平滑半写实、柔边、细轮廓，跟现有八张是一族；
#   形象参照（立绘）管**画成谁** —— 拿成妻的脸去画成子，出来的是成妻的妹妹。
# 立绘图在 assets/portraits/，由 tools/import_refs.py 从用户给的原图整理入库。
REDRAW = [
    # 2026-09-24 清空：成名入库（tools/import_chengming_face.py），八张脸图全部定稿。
    # 要再加需求，照下面这五个字段追加一项即可：
    #   name=角色名（须在 G.CAST 里） / cur=现状文件名 / style=笔法样板文件名
    #   shape=assets/portraits/ 下的形象参照图 / why=为什么要重画 / prompt=给画师的提示词
]


def build_faces():
    """要重画的脸并排给出四样东西：现状 / 笔法样板 / 形象参照 / 理由 + 提示词。"""
    f_title, f_name, f_note, f_small, f_tag = (
        font(40), font(32), font(21), font(18), font(19))
    M, NAME_W, CELL, GAP, NOTE_W = 30, 118, 144, 24, 630
    HEAD, TAG_H = 156, 34

    x_cur = M + NAME_W + GAP
    x_style = x_cur + CELL + GAP
    x_shape = x_style + CELL + GAP
    x_note = x_shape + CELL + GAP
    W = x_note + NOTE_W + M

    foot = [
        "■ 八张全部定稿：成名 / 成妻 / 成子 / 里胥 / 驼背巫 / 宰 / 守卫 / 村中少年。"
        "宰与成名是最后两张 —— 分别切自 tools/import_zai_face.py 与 import_chengming_face.py。",
        "■ 成名这张的来路：用户给的双人半身像（剪贴板 671）的**左半**。右半是成妻，"
        "「豆包AI生成」压在她衣袍上，所以裁窗右界止于 x=900，连去水印都省了。",
        "■ 仍有一处不同族：成妻 ChengQi 取自库存包（576×288 八格表情表，卡通大眼），"
        "而 M1 有三处对话在用她。要统一的话，671 的右半就是她的源料（那张要先去水印）。",
        "■ HatMan.png（斗笠壮汉）是同一个库存包剩下的，CAST 里没有这个人，"
        "在包里躺着未挂载 —— face_brief 会一直报「未挂载」，是已知状态。",
        "■ 完整参照图（不是缩略图）都在 assets/portraits/。标题背景已上线"
        "（月夜，816×624，水印已清）。",
    ]
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    FOOT = notes_h(dummy, foot, f_note, W - M * 2, gap=10) + 34

    # 行高得按理由 + 提示词的实际行数算 —— 三行的字数差一倍，拍一个固定值必然有的挤有的空
    heights = []
    for r in REDRAW:
        h = notes_h(dummy, [r["why"]], f_note, NOTE_W, gap=10)
        h += notes_h(dummy, ["■ 提示词：" + r["prompt"]], f_note, NOTE_W, gap=0)
        heights.append(max(CELL + TAG_H + 20, h + 20))

    H = HEAD + sum(heights) + FOOT
    img = Image.new("RGBA", (W, H), PAGE)
    d = ImageDraw.Draw(img)

    d.text((M, 30), "促织 · 脸图重画需求", font=f_title, fill=INK)
    if REDRAW:
        d.text((M, 86), "共 %d 张。规格与现有八张完全一致：144×144、PNG 全透明底、只画到肩、"
                        "底边把肩膀切掉（细则见 脸图规格.png）" % len(REDRAW),
               font=f_note, fill=INK)
        d.text((M, 118), "画完放 assets/img/faces/，文件名用下面的英文名（大写照抄）",
               font=f_small, fill=DIM)
    else:
        d.text((M, 86), "0 张 —— 八张脸图全部定稿入库，这一单已清。",
               font=f_note, fill=INK)
        d.text((M, 118), "下面的记录留着：以后要加新需求，照文件里 REDRAW 的注释追加一项",
               font=f_small, fill=DIM)

    y = HEAD
    for i, r in enumerate(REDRAW):
        h = heights[i]
        d.line([(M, y - 14), (W - M, y - 14)], fill=LINE, width=2)

        d.text((M, y + 26), r["name"], font=f_name, fill=INK)
        d.text((M, y + 70), r["cur"], font=f_tag, fill=DIM)

        for x, im, outline, label in (
                (x_cur, face_cell(r["cur"], CELL), RED, "现状（要换掉）"),
                (x_style, face_cell(r["style"], CELL), GREEN, r["style_label"]),
                (x_shape, fit_cell(os.path.join(ROOT, "assets", "portraits", r["shape"]), CELL),
                 DIM, "形象参照")):
            img.paste(im, (x, y))
            if outline is RED:
                dashed_rect(d, (x, y, x + CELL, y + CELL), outline, width=3)
            else:
                d.rectangle([x, y, x + CELL, y + CELL], outline=outline, width=3)
            d.text((x, y + CELL + 8), label, font=f_small, fill=outline)

        ny = notes(d, (x_note, y), [r["why"]], f_note, NOTE_W, gap=10)
        notes(d, (x_note, ny), ["■ 提示词：" + r["prompt"]], f_note, NOTE_W,
              gap=0, fill=GREEN)
        y += h

    fy = y
    d.line([(M, fy - 14), (W - M, fy - 14)], fill=LINE, width=2)
    notes(d, (M, fy), foot, f_note, W - M * 2, gap=10)

    os.makedirs(OUT_PORT, exist_ok=True)
    out = os.path.join(OUT_PORT, "脸图重画需求.png")
    img.convert("RGB").save(out)
    print("写好了", os.path.relpath(out, ROOT), img.size)


# ------------------------------------------------- 角色形象卡（按行走图取色）
# 部位 -> (纵向比例区间, 横向比例区间)，取的是 48x48 正面站立帧（第 1 行第 2 列）
REF_REGIONS = [
    ("头发", (0.02, 0.30), (0.34, 0.68)),
    ("皮肤", (0.36, 0.54), (0.38, 0.62)),
    ("上衣", (0.58, 0.70), (0.36, 0.66)),
    ("裤子", (0.74, 0.86), (0.36, 0.66)),
    ("布鞋", (0.88, 1.00), (0.28, 0.72)),
]
REF_FEATURES = [
    "圆脸、下巴短而圆；两颊各一点淡腮红。",
    "细单线眉，短；细线眼，眼距偏宽；嘴是小小一点。",
    "黑发在头顶偏后挽成一个小发包（不是双总角），额前碎发两三撮。",
    "暗红交叉领短上衣 + 褐色裤子 + 米色布鞋 —— 颜色照右侧色板，别自己调。",
    "斜挎一根深色背带（布口袋的带子），过左肩；画到肩的部分要留出来。",
]
REF_STYLE = [
    "脸图已定稿：直接用用户给的那张正面立绘切出来的，144×144。"
    "切法见 tools/import_portrait_face.py（去水印 + 抠白底 + 按高度缩到 138）。",
    "笔法与另几张不同族：这张是柔边厚涂、没有轮廓线；配角那 5 张是带线稿的半写实。"
    "素材原样如此，保持不动 —— 换笔法等于重画，没有理由。",
    "这张卡留作**成子的形象档案**：以后画他的任何衍生素材（表情差分、别的姿势）都以它为准。"
    "配色和头身比例仍是行走图说了算，立绘只用来认人。",
]
REF_PROMPT = ("成子已定稿，不用再画。以后要出他的衍生素材，照上面这张立绘的长相，"
              "照左下行走图的配色与头身比例。")


def ref_palette(name):
    """按部位取色。用中位数而不是众数 —— 这张表是放大过的，同色被插值糊成了几百种。"""
    im = Image.open(os.path.join(ROOT, "assets", "img", "characters", "$%s.png" % name))
    frame = np.asarray(im.convert("RGBA").crop((48, 0, 96, 48))).astype(int)
    a = frame
    op = a[:, :, 3] > 180
    out = []
    for label, (y0, y1), (x0, x1) in REF_REGIONS:
        ys, ye = int(y0 * 48), int(y1 * 48)
        xs, xe = int(x0 * 48), int(x1 * 48)
        m = op[ys:ye, xs:xe]
        assert m.sum() > 20, "取色区太窄：%s %s 只有 %d 个像素" % (name, label, m.sum())
        px = a[ys:ye, xs:xe][:, :, :3][m]
        med = np.median(px, 0).astype(int)
        lum = px.sum(1)
        hi = np.median(px[lum >= np.percentile(lum, 85)], 0).astype(int)
        # 鞋子例外：中位色取到的是深色鞋底，而这块料的「主色」其实是米色鞋面，
        # 深色只占一小圈。浅色当主色摆出来才对得上眼睛看到的东西。
        if label == "布鞋":
            med, hi = hi, med
        out.append((label, tuple(med), tuple(hi)))
    return out


def build_refcard(name, fname, ref_file, feats, style, prompt, out_name):
    """形象卡：顶上摆参照立绘，左下是行走图，右下是取色 + 特征 + 来历 + 备注。

    为什么要有它：立绘用来认人（长相、发式、衣色），行走图定配色和头身比例 ——
    两者打架时以行走图为准，因为它才是游戏里真正跑动的那个东西。
    成子的脸图就是从这张立绘切出来的，所以这张卡同时是**他的形象档案**：
    以后出表情差分、别的姿势，都照它。
    """
    f_title, f_sub, f_note, f_small, f_hex = (
        font(40), font(21), font(20), font(18), font(16))
    M, S = 30, 3
    sheet = Image.open(os.path.join(ROOT, "assets", "img", "characters", "$%s.png" % fname))
    sheet = sheet.convert("RGBA")
    art_w, art_h = sheet.width * S, sheet.height * S
    GAP = 44
    nx = M + art_w + GAP
    NOTE_W = 636
    W = nx + NOTE_W + M

    # 参照大图按整幅宽等比缩放，高度随原图比例走
    ref_path = os.path.join(ROOT, "assets", "portraits", ref_file)
    assert os.path.exists(ref_path), "参照图不在：%s" % ref_path
    ref = Image.open(ref_path).convert("RGBA")
    band_w = W - M * 2
    band_h = round(ref.height * band_w / ref.width)
    band = ref.resize((band_w, band_h), Image.LANCZOS)
    HEAD = 150
    BODY = HEAD + band_h + 56          # 大图 + 图注之后才是正文

    pal = ref_palette(fname)
    SW_W, SW_H, SW_GAP, SW_COLS = 200, 92, 16, 3
    pal_rows = (len(pal) + SW_COLS - 1) // SW_COLS
    pal_h = 40 + pal_rows * (SW_H + SW_GAP)

    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    def block_h(items):
        return 40 + notes_h(dummy, items, f_note, NOTE_W, gap=12)
    prompt_lines = wrap(dummy, prompt, f_note, NOTE_W - 60)
    right_h = (pal_h + 34 + block_h(feats) + 24 + block_h(style) + 24
               + 52 + len(prompt_lines) * (f_note.size + 10) + 34)

    # 左下整块留给行走图：配色以它为准，五官形体也以它为准 —— 它才是游戏里那个东西
    CLOSE_Y = BODY + art_h + 74
    tail = wrap(dummy, "上面是参照立绘，下面是他的行走图（游戏里实际用的，放大 %d 倍）。"
                       "立绘用来认人，配色和头身比例以行走图为准。" % S, f_small, art_w)
    left_h = CLOSE_Y - BODY + len(tail) * 24 + 14

    H = BODY + max(left_h, right_h) + 34

    img = Image.new("RGBA", (W, H), PAGE)
    d = ImageDraw.Draw(img)

    d.text((M, 30), "促织 · %s 形象卡" % name, font=f_title, fill=INK)
    d.text((M, 84), "脸图已定稿 —— 就是照这张立绘切的，不用再画。",
           font=f_sub, fill=RED)
    d.text((M, 118), "立绘用来认人；配色与头身比例以他的行走图为准。",
           font=f_small, fill=DIM)

    # ---- 顶：参照大图 ----
    img.paste(band, (M, HEAD))
    d.rectangle([M, HEAD, M + band_w, HEAD + band_h], outline=DIM, width=2)
    d.text((M, HEAD + band_h + 10),
           "%s　（原图 %d × %d，来自 assets/portraits/）" % (ref_file, ref.width, ref.height),
           font=f_small, fill=DIM)

    # ---- 左下：行走图放大 ----
    big = Image.new("RGB", (art_w, art_h), (255, 255, 255))
    for r in range(4):
        for c in range(3):
            fr = sheet.crop((c * 48, r * 48, c * 48 + 48, r * 48 + 48))
            fr = fr.resize((48 * S, 48 * S), Image.NEAREST)
            tmp = Image.new("RGB", (48 * S, 48 * S), (255, 255, 255))
            tmp.paste(fr, (0, 0), fr)
            big.paste(tmp, (c * 48 * S, r * 48 * S))
    img.paste(big, (M, BODY))
    for r in range(5):
        y = BODY + r * 48 * S
        d.line([(M, y), (M + art_w, y)], fill=(224, 226, 232, 255), width=2)
    for c in range(4):
        x = M + c * 48 * S
        d.line([(x, BODY), (x, BODY + art_h)], fill=(224, 226, 232, 255), width=2)
    d.rectangle([M, BODY, M + art_w, BODY + art_h], outline=DIM, width=2)
    d.text((M, BODY + art_h + 8), "$%s.png ／ 144 × 192 ／ 3 列 × 4 行" % fname,
           font=f_small, fill=DIM)

    ny = CLOSE_Y
    for ln in tail:
        d.text((M, ny), ln, font=f_small, fill=DIM)
        ny += 24

    # ---- 右下：色板 ----
    y = BODY
    d.text((nx, y), "配色（取自他的行走图）", font=f_sub, fill=INK)
    y += 40
    for i, (label, main, hi) in enumerate(pal):
        x = nx + (i % SW_COLS) * (SW_W + SW_GAP)
        yy = y + (i // SW_COLS) * (SW_H + SW_GAP)
        d.rectangle([x, yy, x + SW_W, yy + 46], fill=main + (255,), outline=LINE, width=2)
        d.rectangle([x + SW_W - 62, yy, x + SW_W, yy + 46], fill=hi + (255,), outline=LINE, width=2)
        d.text((x, yy + 50), label, font=f_small, fill=INK)
        d.text((x, yy + 70), "#%02x%02x%02x" % main, font=f_hex, fill=DIM)

    y += pal_h + 34
    d.text((nx, y), "五官与装扮", font=f_sub, fill=INK)
    y = notes(d, (nx, y + 40), feats, f_note, NOTE_W, gap=12) + 24
    d.text((nx, y), "脸图来历与笔法", font=f_sub, fill=INK)
    y = notes(d, (nx, y + 40), style, f_note, NOTE_W, gap=12) + 24
    card = [nx, y, W - M, y + 52 + len(prompt_lines) * (f_note.size + 10) + 34]
    d.rounded_rectangle(card, radius=14, fill=(240, 245, 240, 255), outline=GREEN, width=3)
    d.text((nx + 22, y + 16), "备注", font=f_sub, fill=GREEN)
    ty = y + 54
    for ln in prompt_lines:
        d.text((nx + 26, ty), ln, font=f_note, fill=INK)
        ty += f_note.size + 10

    os.makedirs(OUT_PORT, exist_ok=True)
    out = os.path.join(OUT_PORT, out_name)
    img.convert("RGB").save(out)
    print("写好了", os.path.relpath(out, ROOT), img.size)


if __name__ == "__main__":
    # 名册是唯一真源：重画清单里提到的脸图与参照图必须真的存在。
    # 缺了不会报错，只会安静地画一张错的单子 —— 等画的人照着画完才发现。
    for _r in REDRAW:
        assert _r["name"] in G.CAST, "重画清单里的 %s 不在 CAST 名册里" % _r["name"]
        for _f in (_r["cur"], _r["style"]):
            _p = os.path.join(DIR_FACE, _f + ".png")
            assert os.path.exists(_p), "脸图不在：%s" % _p
        _p = os.path.join(ROOT, "assets", "portraits", _r["shape"])
        assert os.path.exists(_p), "形象参照图不在：%s（先跑 tools/import_refs.py）" % _p
    build_title()
    build_faces()
    build_refcard("成子", "ChengZi", "成子_立绘参照.png", REF_FEATURES, REF_STYLE,
                  REF_PROMPT, "形象卡_成子.png")
