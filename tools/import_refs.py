# -*- coding: utf-8 -*-
"""把用户发来的一批参照图入库。

来源是剪贴板目录里同一批次的 11 张（文件名带同一个时间戳）。分两类去处：

  assets/portraits/    给美术看的参照图 —— 不参与打包，只为出需求单
  assets/img/titles1/  标题背景 —— 这个要真的进游戏（经 build_project 注入）

归属不猜：下面 FLOW 是**逐张看图核对过**的结论。改它之前先看图。

踩过的坑：用户聊天里的 @image 序号和实际贴图的顺序能差一位 —— 上一轮就是照
序号认领，差点把成子的立绘记成宰的。所以这里一律按**内容**判，序号只当线索。

用法：
    python tools/import_refs.py
产出：
    assets/portraits/宰_立绘参照.png        6 个姿态拼成一张（取共同点用）
    assets/portraits/宰_头部参照.png        同上，只剪到肩线，画脸时看这个
    assets/portraits/成名_立绘参照.png
    assets/portraits/标题背景_月夜_原图.png
    assets/img/titles1/Cuzhi.png            816x624，去水印

成子的立绘不在这里出 —— 见 import_portrait_face.py。
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from face_brief import font                      # noqa: E402  复用中文字体

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = os.path.join(ROOT, "assets", "portraits")
TITLES1 = os.path.join(ROOT, "assets", "img", "titles1")

CLIP = os.path.join(os.path.expanduser("~"), ".workbuddy", "clipboard-images")
STAMP = "clipboard-2026-09-23T13-20-49-"

# 剪贴板文件名里的毫秒序号 -> 内容。用户发的是 #1..#11。
#   651 = 成子行走图 4 帧（已入库为 成子_形象参照.png，这里只核对）
#   654..665 = 同一名官员的 6 个姿态 —— 用户标注「县太爷官员」，即宰
#   667 = 「脸图重画需求」文档的截图，用户误发，不是素材
#   670 = 暗红交领少年半身像 —— 与成子行走图同族（单发髻/暗红交领/斜挎带/腮红）
#   671 = 青灰衣男女双人半身 —— 左为成名（网巾+青灰直裰），右为成妻
#   674 = 月夜荒草坡 —— 标题背景
FLOW = {
    "651": ("skip", "成子行走图 4 帧，与 assets/portraits/成子_形象参照.png 同一张"),
    "654": ("zai", None), "656": ("zai", None), "659": ("zai", None),
    "663": ("zai", None), "664": ("zai", None), "665": ("zai", None),
    "667": ("skip", "「脸图重画需求」文档截图，用户误发"),
    "670": ("skip", "成子立绘（较早的一版裁切），已被更清楚的那张取代，见 import_portrait_face.py"),
    "671": ("chengming", None),
    "674": ("title", None),
}
ORDER = ["651", "654", "656", "659", "663", "664", "665", "667", "670", "671", "674"]

TITLE_W, TITLE_H = 816, 624
OUT_TITLE = "Cuzhi"          # -> assets/img/titles1/Cuzhi.png


def batch():
    """取这一批的 11 张。按毫秒序号排 —— 目录里还堆着别的批次的图。"""
    fs = [f for f in os.listdir(CLIP) if f.startswith(STAMP)]
    got = {}
    for f in fs:
        ms = f[len(STAMP):].split("Z")[0]
        if ms in FLOW:
            got[ms] = os.path.join(CLIP, f)
    missing = [k for k in ORDER if k not in got]
    assert not missing, "这一批里缺 %s（剪贴板目录被清过？）" % missing
    return [got[k] for k in ORDER]


def tight(im, pad=28, thr=244):
    """裁掉白底留白。1536 方的立绘里人只占中间一块，不裁的话缩进参照卡上就看不清脸。"""
    a = np.asarray(im.convert("RGB")).astype(int)
    m = a.min(2) < thr                      # 非白即内容（这几张都是纯白底）
    ys, xs = np.where(m)
    assert len(ys), "整张都是白的：认不出内容"
    x0, x1 = max(0, xs.min() - pad), min(im.width, xs.max() + 1 + pad)
    y0, y1 = max(0, ys.min() - pad), min(im.height, ys.max() + 1 + pad)
    return im.crop((x0, y0, x1, y1))


def dewatermark(im, box):
    """把「豆包AI生成」压回背景亮度，返回新图。

    水印是灰字（亮度 ~160）压在近黑的枯枝上（~20），它多出来的就是「比周围亮」。
    所以框内逐像素算一个不超过背景水平的系数乘回去：色相和纹理都保留，
    暗处的枝桠一根不少，只是不再有字。背景水平取框内亮度的 30 分位。

    **注意 build_title 只在裁不掉水印时才走这一支** —— 裁得掉就直接裁，不造假像素。
    """
    x0, y0, x1, y1 = box
    a = np.asarray(im.convert("RGB")).astype(float)
    sub = a[y0:y1, x0:x1]
    lum = sub.mean(2)
    cap = np.percentile(lum, 30)
    scale = np.minimum(1.0, cap / np.maximum(lum, 1.0))
    a[y0:y1, x0:x1] = sub * scale[:, :, None]
    return Image.fromarray(a.astype(np.uint8))


# 「豆包AI生成」在这批图上的相对位置，量过一遍就够 —— 一次性的活，不值得写检测器。
# 实测：674 框内亮度 p90=162，正上方同宽条带 p50=19，信号干净到不需要怀疑。
WM_FRAC = (0.865, 0.944, 0.990, 0.983)


def find_watermark(im):
    """按固定比例框出水印，顺手验一下框里确实有东西 —— 换了图要立刻知道。"""
    x0, y0, x1, y1 = WM_FRAC
    box = (round(x0 * im.width), round(y0 * im.height),
           round(x1 * im.width), round(y1 * im.height))
    a = np.asarray(im.convert("RGB")).astype(float)
    lum = a[box[1]:box[3], box[0]:box[2]].mean(2)
    base = np.percentile(lum, 30)
    assert np.percentile(lum, 90) > base * 3 + 40, \
        "右下角框里没有水印（p30=%.0f p90=%.0f），图换了？" % (base, np.percentile(lum, 90))
    return box


def montage(paths, cols, out, label_fmt="第 %d 张", cell=520, gap=18, head=96):
    """若干张白底立绘拼一张对照图，每格裁紧再统一高度 —— 不裁的话格子大小骗人。"""
    f_h, f_t = font(40), font(20)
    ims = [tight(Image.open(p).convert("RGB")) for p in paths]
    scale = [cell / max(i.width, i.height) for i in ims]
    cells = [i.resize((round(i.width * s), round(i.height * s)), Image.LANCZOS)
             for i, s in zip(ims, scale)]
    cw = max(c.width for c in cells)
    ch = max(c.height for c in cells)
    rows = (len(cells) + cols - 1) // cols
    H = head + rows * (ch + 34 + gap) + gap
    W = cols * (cw + gap) + gap
    img = Image.new("RGB", (W, H), (247, 247, 250))
    d = ImageDraw.Draw(img)
    d.text((gap, 22), "同一角色的 %d 个生成结果 —— 取共同点，别照抄单张" % len(cells),
           font=f_h, fill=(28, 30, 38))
    d.text((gap, 66), "各格已裁去白边并按高度对齐；有出入时以行走图和文字规格为准",
           font=f_t, fill=(120, 126, 140))
    for i, c in enumerate(cells):
        x = gap + (i % cols) * (cw + gap) + (cw - c.width) // 2
        y = head + (i // cols) * (ch + 34 + gap)
        img.paste(c, (x, y))
        d.rectangle([gap + (i % cols) * (cw + gap), y - 2,
                     gap + (i % cols) * (cw + gap) + cw, y + ch + 2],
                    outline=(214, 218, 226), width=2)
        d.text((gap + (i % cols) * (cw + gap), y + ch + 6),
               label_fmt % (i + 1), font=f_t, fill=(120, 126, 140))
    img.save(out)
    print("写好了", os.path.relpath(out, ROOT), img.size)


def build_title(src):
    """月夜图 -> 引擎要的 816x624。

    水印在**最底边**（原图 y 1384 往下），而引擎只要求比例对得上、尺寸正好 816x624。
    于是最干净的做法不是抹掉水印，而是取一个**下沿落在水印之上**的同比例窗口 ——
    一个假像素都不用造。代价是丢底部约 6%，画面上就是前景的草少一截，看不出来。

    这条路走不通时才退回去压顶（dewatermark）：窗口会被压到八折以下，构图就不对了。
    """
    im = Image.open(src).convert("RGB")
    tar = TITLE_W / TITLE_H
    box = find_watermark(im)
    # 下沿落在水印之上，水印就整个出画 —— 跟它横向占了多宽无关
    if box[1] >= im.height * 0.8:
        y1 = box[1]
    else:                                     # 水印太靠上，裁到那儿构图就塌了
        im = dewatermark(im, box)
        y1 = im.height
    w = min(im.width, round(y1 * tar))
    x0 = (im.width - w) // 2
    im = im.crop((x0, 0, x0 + w, y1))
    os.makedirs(TITLES1, exist_ok=True)
    out = os.path.join(TITLES1, OUT_TITLE + ".png")
    im.resize((TITLE_W, TITLE_H), Image.LANCZOS).save(out)
    print("写好了", os.path.relpath(out, ROOT), (TITLE_W, TITLE_H),
          "裁自", im.size, "水印框 %s" % (box,))
    return out


if __name__ == "__main__":
    paths = batch()
    by = dict(zip(ORDER, paths))

    # 651 是我们已经有的那张（已入库为 成子_形象参照.png，1313x469 对 1312x469）。
    # 只比宽高比 —— 差一个像素是上一轮从聊天里截出来的边，不是换了图。
    old = Image.open(os.path.join(PORT, "成子_形象参照.png"))
    now = Image.open(by["651"])
    assert abs(old.width / old.height - now.width / now.height) < 0.01, \
        "651 与已入库的成子行走参照不像同一张：%s vs %s" % (old.size, now.size)

    zai = [by[k] for k in ("654", "656", "659", "663", "664", "665")]
    montage(zai, 3, os.path.join(PORT, "宰_立绘参照.png"))

    # 另裁一张头部：脸图底边切在肩膀，只看得到帽子和领口，
    # 而 6 张全身像缩到 144px 就连五官都糊了 —— 画脸的人需要这张。
    full = tight(Image.open(by["663"]).convert("RGB"))
    head = tight(full.crop((0, 0, full.width, round(full.height * 0.34))), pad=14)
    head.save(os.path.join(PORT, "宰_头部参照.png"))
    print("写好了 assets/portraits/宰_头部参照.png", head.size)

    # 成子的立绘**不从这里出** —— 用户后来又发了一张同源但取景更紧、头更大的，
    # 那份归 import_portrait_face.py（它顺带把水印和脸图一起做完）。
    # 这里要是再写一遍，就会把人家修好的图盖回旧的。
    # 671 是双人图，左为成名。裁到 66% 宽再裁紧 —— 成妻的高髻在 66% 之后
    duo = Image.open(by["671"]).convert("RGB")
    left = duo.crop((0, 0, round(duo.width * 0.66), duo.height))
    tight(left).save(os.path.join(PORT, "成名_立绘参照.png"))
    print("写好了 assets/portraits/成名_立绘参照.png")

    tw = tight(Image.open(by["674"]).convert("RGB"), pad=0)
    tw.save(os.path.join(PORT, "标题背景_月夜_原图.png"))
    print("写好了 assets/portraits/标题背景_月夜_原图.png", tw.size)
    build_title(by["674"])

    for k in ORDER:
        what, why = FLOW[k]
        if what == "skip":
            print("  跳过 %s —— %s" % (k, why))
