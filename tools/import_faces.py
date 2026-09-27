# -*- coding: utf-8 -*-
"""配角脸图入库 —— 把 4×2 合成表切成 5 张 144×144 的 MZ 脸图

素材：`assets/portraits/配角脸图表.png`（用户给的 1920×960 合成表）。
表里第 6/7/8 格（乱发少年 / 空白 / 重甲兵）这次不用 —— 右下角「豆包AI生成」水印
正好落在不用的那格，不影响前五格。

三个坑，都是这张图特有的：

1. **网格不是整数等分**。每格 453~464px 不等，所以 1920/4 切不准。改成从图上量：
   贯穿整高、且**段宽 ≤ 8px** 的深色窄条就是网格线，线之间的宽区间才是内容。
   段宽这个条件是必须的 —— 第一行格子底部角色的肩/衣连着几十行 90%+ 深色，
   不滤掉就会被当成一条 46px 宽的「线」，把格子劈成两半。
2. **棋盘格被烘进像素了**。这张是截图转 JPG，AI 用来表示透明的那层棋盘格成了真实
   像素（`254,255,254` 与 `237,238,238` 交错）。两步去掉：先用 floodfill 从四角啃
   （两档的通道差之和是 51，thresh=60 能跨过去），再按颜色补一刀扫掉被角色围住的
   孤岛 —— 判据是**中性且亮度 ≥ 224**（JPEG 把格子边界糊成 224~255 的连续带）。
   **不能用全局阈值**：角色身上有浅色衣领，一刀切会切出洞；所以判据里必须带「中性」
   （通道差 ≤ 20），米色/肤色这类带黄调的都会自动躲开。
3. **构图要统一**。格内人物位置各格不一，先按前景包围盒裁紧，再**按高度**缩到
   138px、顶部留 6px、水平居中 —— 底部正好被 144 的画布切掉，即规格里的「肩部出画」。
   按宽度缩放不行：各格头肩宽比不同，会得到大小不一的头。

用法：python tools/import_faces.py
产出：assets/img/faces/{LiXu,Witch,Zai,Guard,Youth}.png
      docs/accept/portraits/配角脸图_切分对照.png（含没用上的格子，标出来）
"风格对比"那张图由 `face_brief.py` 出（脸图实尺对照.png），本脚本不再重复生成。
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game_data as G  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets", "portraits", "配角脸图表.png")
OUT_FACES = os.path.join(ROOT, "assets", "img", "faces")
OUT_DOCS = os.path.join(ROOT, "docs", "accept", "portraits")

FACE_PX, TOP_PAD = 144, 6
EDGE_PAD = 8                   # 切格时往内让出的像素（躲开网格线的 JPEG 渗出带）
MAGIC = (255, 0, 255)          # floodfill 的填充色，用完就转成透明
FLOOD_THRESH = 60              # 白 -> 棋盘灰 的通道差之和是 51，60 够跨过去
LINE_THR, LINE_MAX_W, MIN_CELL = 0.93, 8, 120

# 格序 -> (角色名, 文件名)。用户指定「前 5 格依次」；第 6/7/8 格这次不用。
# 文件名走 ASCII：老素材也是英文名，网页版部署时中文名会被 URL 编码，少一个变量。
SLOTS = [((0, 0), "里胥", "LiXu"), ((0, 1), "驼背巫", "Witch"), ((0, 2), "宰", "Zai"),
         ((0, 3), "守卫", "Guard"), ((1, 0), "村中少年", "Youth")]
UNUSED = {(1, 1): "乱发少年", (1, 2): "空白", (1, 3): "重甲兵"}

FONT_PATH = "C:/Windows/Fonts/msyh.ttc"


def font(size):
    return ImageFont.truetype(FONT_PATH, size)


def spans_between_lines(profile, thr=LINE_THR, max_line=LINE_MAX_W, min_len=MIN_CELL):
    """把一条轴上的深色占比曲线切成「内容区间」。

    只有窄条才算线（段宽 <= max_line）；宽条即便占比高也只是角色，不参与切分。
    """
    n = len(profile)
    isline = np.zeros(n, bool)
    i = 0
    while i < n:
        if profile[i] > thr:
            j = i
            while j < n and profile[j] > thr:
                j += 1
            if j - i <= max_line:
                isline[i:j] = True
            i = j
        else:
            i += 1
    out, i = [], 0
    while i < n:
        if not isline[i]:
            j = i
            while j < n and not isline[j]:
                j += 1
            if j - i >= min_len:
                out.append((i, j - 1))
            i = j
        else:
            i += 1
    return out


def bg_seed(cell, x, y, dx, dy, limit=18):
    """沿对角线往里找第一个「确定是背景」的像素，拿它当 floodfill 种子。

    不能直接用内容区的四角：网格黑线经 JPEG 压缩会向外渗 2~3px，四角常常是
    (115,115,115) 这种过渡灰 —— 从灰种子出发，thresh 一比较就到不了白底，
    一格也啃不动。这是第一版踩的坑（背景占比 0%）。
    """
    for k in range(limit):
        px = cell.getpixel((x + dx * k, y + dy * k))
        if min(px) >= 232 and max(px) - min(px) <= 20:
            return (x + dx * k, y + dy * k)
    return None


def cut_cell(im, xs, ys):
    """裁一格 + 去背 + 裁紧包围盒，返回 RGBA（尚未构图）。

    切的时候往里让 EDGE_PAD 像素：网格黑线经 JPEG 压缩会向外渗一圈过渡灰
    （(115,115,115) 这种），留着它会把前景包围盒撑成整个格子，还留下一圈灰边。
    """
    cell = im.crop((xs[0] + EDGE_PAD, ys[0] + EDGE_PAD,
                    xs[1] + 1 - EDGE_PAD, ys[1] + 1 - EDGE_PAD)).convert("RGB")
    w, h = cell.size
    for sd in (bg_seed(cell, 0, 0, 1, 1), bg_seed(cell, w - 1, 0, -1, 1),
               bg_seed(cell, 0, h - 1, 1, -1), bg_seed(cell, w - 1, h - 1, -1, -1)):
        if sd:
            ImageDraw.floodfill(cell, sd, MAGIC, thresh=FLOOD_THRESH)

    a = np.asarray(cell).astype(int)
    is_magic = (a[:, :, 0] == MAGIC[0]) & (a[:, :, 1] == MAGIC[1]) & (a[:, :, 2] == MAGIC[2])
    # 补一刀：棋盘格若被角色隔成孤岛，floodfill 从边上啃不到，得按颜色一并清掉。
    # 棋盘两档实测是 (254,255,254) 与 (237,238,238)，JPEG 把格子边界糊成 224~255 的
    # 连续带 —— 所以阈值必须够到 224。这里踩过一次坑：原来写 `min >= 240`，
    # 正好差 1 漏掉暗档 237，守卫和村中少年两格因此留了一地白色噪点（其余三格看着正常，
    # 更难发现）。五格实测 224 以下没有成片前景像素；角色身上的浅色衣物都带黄调
    # （村中少年的米色袍通道差 > 20），会被「中性」这条挡住，不会切出洞。
    spare_bg = (a.max(2) - a.min(2) <= 20) & (a.mean(2) >= 224)
    mask = is_magic | spare_bg
    rgba = np.dstack([np.where(mask[:, :, None], 255, a).astype(np.uint8),
                      np.where(mask, 0, 255).astype(np.uint8)])
    out = Image.fromarray(rgba.astype(np.uint8), "RGBA")

    bbox = out.getchannel("A").getbbox()
    if bbox is None:
        raise SystemExit("这一格整块被判成背景了，阈值有问题")
    if mask.mean() < 0.15:
        raise SystemExit("只啃掉 %.1f%% 背景，多半是种子点找错了" % (mask.mean() * 100))
    return out.crop(bbox), mask


def compose(fig):
    """按高度缩到 138px、顶部留 6px、水平居中 —— 底部由画布切掉，即「肩部出画」。"""
    w, h = fig.size
    s = (FACE_PX - TOP_PAD) / h
    nw, nh = max(1, round(w * s)), FACE_PX - TOP_PAD
    fig = fig.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", (FACE_PX, FACE_PX), (0, 0, 0, 0))
    canvas.alpha_composite(fig, ((FACE_PX - nw) // 2, TOP_PAD))
    return canvas


def face_axis(rgba, frac=(0.0, 0.55)):
    """肤色列剖面 -> 脸的横向中轴（像素 x）。

    只在上部 frac 区间找：下半是朱红袍，红的程度什么样都可能，混进来就把轴拉偏。

    **肤色判据必须带 `G - B > 15`**。宰穿朱红圆领袍，红色是「R 明显大于 B」，
    但 R 也明显大于 G —— 只按 R-B / R-G 判，整件袍子都算脸（第一版就这么错的，
    量出来的"脸"一路顶到画布底边）。肤色是黄调，G 比 B 高一截
    （实测 (230,180,145)：G-B=35）；朱红袍 G≈B，这一条一刀就分开了。
    """
    a = np.asarray(rgba.convert("RGBA")).astype(int)
    y0, y1 = int(a.shape[0] * frac[0]), int(a.shape[0] * frac[1])
    sub = a[y0:y1]
    rgb, al = sub[:, :, :3], sub[:, :, 3]
    m = (al > 200) & (rgb[:, :, 0] > 130) \
        & (rgb[:, :, 0] - rgb[:, :, 2] > 38) \
        & (rgb[:, :, 0] - rgb[:, :, 1] > 18) \
        & (rgb[:, :, 1] - rgb[:, :, 2] > 15)
    col = m.sum(0)
    if col.max() < 8:
        raise SystemExit("这一块里找不到肤色列，判据要改")
    xs = np.where(col > col.max() * 0.25)[0]
    return (int(xs[0]) + int(xs[-1])) // 2, int(xs[0]), int(xs[-1])


def compose_face_centered(top):
    """全身立绘取来的头肩用这个 —— 与 compose() 只差**居中基准**。

    compose() 按裁剪框居中，对合成表那批成立：一格一个胸像，包围盒≈头肩，
    居中≈脸居中。但全身行姿不行 —— 手臂摆动、身体前倾会把包围盒中心拉偏，
    照它居中会让乌纱帽的展脚一侧顶出画（实测 654 偏 12 像素，一侧展脚被切）。
    所以这里按**脸的中轴**对齐到画布中线。缩放口径仍与 compose() 完全一致
    （按高度缩到 138、顶部留 6）—— 那一套才是跟其余脸图对齐的关键。
    """
    cx = face_axis(top)[0]
    w, h = top.size
    s = (FACE_PX - TOP_PAD) / h
    nw = max(1, round(w * s))
    fig = top.resize((nw, FACE_PX - TOP_PAD), Image.LANCZOS)
    canvas = Image.new("RGBA", (FACE_PX, FACE_PX), (0, 0, 0, 0))
    canvas.alpha_composite(fig, ((FACE_PX // 2) - round(cx * s), TOP_PAD))
    return canvas


def checker(size, box=8):
    """棋盘底 —— 透明素材必须衬着它看，否则看不出哪里是空。"""
    im = Image.new("RGB", (size, size), (255, 255, 255))
    d = ImageDraw.Draw(im)
    for y in range(0, size, box):
        for x in range(0, size, box):
            if (x // box + y // box) % 2:
                d.rectangle([x, y, x + box - 1, y + box - 1], fill=(226, 226, 230))
    return im


def main():
    if not os.path.exists(SRC):
        raise SystemExit("找不到 %s" % SRC)
    im = Image.open(SRC).convert("RGB")
    a = np.asarray(im).astype(int)
    assert not ((a[:, :, 0] == 255) & (a[:, :, 1] == 0) & (a[:, :, 2] == 255)).any(), \
        "原图里就有品红像素，floodfill 的哨兵色得换"

    lum = a.mean(2)
    cols = spans_between_lines((lum < 110).sum(0) / lum.shape[0])
    rows = spans_between_lines((lum < 110).sum(1) / lum.shape[1])
    print("量到 %d 列 × %d 行" % (len(cols), len(rows)))
    assert (len(cols), len(rows)) == (4, 2), "网格没量对，先别往下走"

    # ---- 切图 ----
    cells = {}
    for (r, c), name, fname in SLOTS:
        fig, mask = cut_cell(im, cols[c], rows[r])
        final = compose(fig)
        final.save(os.path.join(OUT_FACES, fname + ".png"))
        cells[(r, c)] = (fig, mask)
        print("  %-5s 格(%d,%d) 前景 %2dx%2d -> %-10s 背景啃掉 %.0f%%"
              % (name, r, c, fig.size[0], fig.size[1], fname + ".png", mask.mean() * 100))

    # ---- 切分对照图：8 格全画，没用的标出来 ----
    S, PAD, CAP = 200, 12, 30
    W, H = PAD + 4 * (S + PAD), PAD + 2 * (S + CAP + PAD) + 44
    board = Image.new("RGB", (W, H), (247, 247, 250))
    d = ImageDraw.Draw(board)
    d.text((PAD, 12), "配角脸图表切分 —— 前 5 格已入库，其余留着备用", font=font(26), fill=(30, 30, 38))
    for r in range(2):
        for c in range(4):
            x = PAD + c * (S + PAD)
            y = 44 + PAD + r * (S + CAP + PAD)
            slot = {k: (n, f) for k, n, f in SLOTS}.get((r, c))
            if slot:
                name, fname = slot
                thumb = checker(S).copy()
                f = cells[(r, c)][0].copy()
                f.thumbnail((S, S), Image.LANCZOS)
                thumb.paste(f, ((S - f.size[0]) // 2, (S - f.size[1]) // 2), f)
                board.paste(thumb, (x, y))
                d.text((x, y + S + 5), "%s → %s.png" % (name, fname), font=font(18),
                       fill=(32, 122, 82))
            else:
                cell = im.crop((cols[c][0], rows[r][0], cols[c][1] + 1, rows[r][1] + 1))
                cell.thumbnail((S, S), Image.LANCZOS)
                board.paste(cell, (x + (S - cell.size[0]) // 2, y + (S - cell.size[1]) // 2))
                d.text((x, y + S + 5), "未用 " + UNUSED[(r, c)], font=font(18),
                       fill=(150, 150, 160))
    d.text((PAD, H - 26), "第 6 格（乱发少年）、第 8 格（重甲兵）留着备用，M2 村中可能用得上。",
           font=font(18), fill=(120, 126, 140))
    board.save(os.path.join(OUT_DOCS, "配角脸图_切分对照.png"))

    # 曾经这里还画一张「老素材 vs 新素材」的风格对比条 —— 已删：`face_brief.py` 的
    # 脸图实尺对照.png 把 8 张一并列出并给出占格比例，是同一件事且更权威（直接从
    # CAST + 磁盘推），两张长得像的图并排放在验收目录里只会让人不知道该看哪张。

    print("写好了 assets/img/faces/ 下 5 张；对照图在 docs/accept/portraits/")


if __name__ == "__main__":
    main()
