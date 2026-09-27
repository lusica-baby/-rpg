# -*- coding: utf-8 -*-
"""单张立绘 -> MZ 脸图

和 `import_faces.py` 的分工：那个吃 4×2 合成表（得先量网格再逐格切），
这个吃**整幅就是一个人**的单张立绘。构图规格两者共用 `compose()`。

这张（成子）有三个特点，决定了这里怎么写：

1. **白底 JPG，不是透明 PNG**。白底是纯 (255,255,255)，从四角 floodfill 能整片啃掉。
   没有沿用合成表那套「中性浅色补刀」—— 角色的交领内衬是米白 (232,228,221)，通道差 11，
   一刀切会把内衬切出洞。改成把 floodfill 的 thresh 放到 100：只吃「从图边走得通」的
   连通区，被衣服包住的内衬天然进不来。

2. **水印横跨衣服和白底**。右下角「豆包AI生成」两半的材质完全不同，得分开处理：
   - 压在暗红短衣上的是**不透明白字**（中心实测纯白），跟衣服连通、floodfill 啃不掉，
     只能按几何位置竖着插值补回来 —— 详见 `strip_watermark` 的注释；
   - 白底上的是灰字，抹成纯白即可。
   顺带记下两个不管用的做法：整块填白会啃掉一块衣服；照 `import_refs.dewatermark`
   那样「按框内 30 分位压顶」—— 这个框里 30 分位落在衣服上（~70），一压把白底也压成灰。

3. **构图直接交给 `compose()`，不要先裁到肩**。入口比合成表的格子宽
   （头 + 肩 + 胸 + 肘），compose 按**高度**缩到 138，多出来的胸口正好落到画布之外。
   实测头高（发顶→下巴）落在 90px，和配角那 5 张的 86px 基本齐平；
   若先裁到肩线再缩，头会胀到 116px —— 同框一比就露馅。

用法：python tools/import_portrait_face.py
产出：assets/img/faces/ChengZi.png          （144×144，进游戏）
      assets/portraits/成子_立绘参照.png      （修过水印的原图，给美术看形象）
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game_data as G                                     # noqa: E402
from import_faces import compose                          # noqa: E402
from import_refs import tight                             # noqa: E402  参照图统一裁白边

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIP = os.path.expanduser("~/.workbuddy/clipboard-images")
OUT_FACES = os.path.join(ROOT, "assets", "img", "faces")
OUT_PORT = os.path.join(ROOT, "assets", "portraits")

MAGIC = (255, 0, 255)
FLOOD_THRESH = 100
# 豆包水印占图幅的比例（量出来的 x1266..1511, y1440..1512，含衣服上那半和
# 白底上那半；四周略外扩，宁可多补几列，别漏一条字的边）。
WM_FRAC = (0.8242, 0.9375, 0.9950, 0.9844)

# 角色名 -> (脸图文件名, 剪贴板文件名)。以后宰、成名到手，往这里加一行即可。
JOBS = [("成子", "ChengZi", "clipboard-2026-09-23T14-01-32-811Z-f5523c01.jpg")]


def strip_watermark(im, box):
    """把水印从衣服上换回衣服色，返回被改写的像素占比。

    水印是**不透明白字**（笔画中心实测纯白 255），压在暗红短衣（RGB 139,48,55）上。
    所以两种直觉做法都不成立：
      - 「比正上方亮就压暗」：纯白按比例缩成 (76,76,76) —— 亮度对了，**色相全丢**，
        得到一块无彩色的灰，比周围的暗红还扎眼。实测就栽在这。
      - 「用正上方十几行前的像素盖下来」：这几十行里肩线轮廓向右斜移了 37px，
        盖下来等于在衣服上糊一条白边，比原水印还显眼。
    正解是**竖着插值**：框的上下各取一条干净行，按行号线性补回来。
    衣服在竖直方向是连续的（色相不变、随受光缓慢渐变），突变都在水平方向
    （褶皱、斜挎带、轮廓），所以竖着插出来的正好是红衣服，且接缝严丝合缝。

    框比字本身外扩几像素：多补的地方在端点行上本来就等于原值，补了看不出；
    而漏补一条字的边就会留下痕迹。
    """
    x0, y0, x1, y1 = box
    assert y0 >= 3 and y1 + 3 <= im.height, "水印太靠边，取不到上下干净行"
    a = np.asarray(im).astype(float)
    # 端点行各取 3 行中位数：单行可能正好压在褶皱的高光或暗线上
    up = np.median(a[y0 - 3:y0, x0:x1], axis=0)
    dn = np.median(a[y1 + 1:y1 + 4, x0:x1], axis=0)
    t = np.linspace(0.0, 1.0, (y1 - y0) + 2)[1:-1, None, None]
    a[y0:y1, x0:x1] = up * (1 - t) + dn * t
    # 白底上那半（「AI生成」）是灰字，直接抹成纯白。框里亮度 > 150 的无彩色像素
    # 就剩它 —— 衣服最亮才 140，纯白底 255 抹成 255 等于没动。
    # 代价是衣服右缘的抗锯齿被削掉一两个像素，在 1536 的图上引不起注意。
    reg = a[y0:y1, x0:x1]
    grey = ((reg.max(2) - reg.min(2)) < 44) & (reg.mean(2) > 150)
    a[y0:y1, x0:x1] = np.where(grey[:, :, None], 255.0, reg)

    out = Image.fromarray(a.astype(np.uint8))
    # 回读像素验一遍：只看框左侧 90 列（衣服所在），拿**正上方同宽区域**当基准比通道差。
    # 暗红衣服通道差 ~90、被白字盖住会掉到 40 上下；而绝对阈值没法写死 ——
    # 衣服右缘那几列本来就偏灰，占的比例随图变。用 up 当基准就自动跟住了。
    chk = np.asarray(out).astype(int)[y0:y1, x0:x0 + 90]
    cur_sp = (chk.max(2) - chk.min(2)).mean()
    ref_sp = (up[:90].max(1) - up[:90].min(1)).mean()
    assert cur_sp > ref_sp * 0.8, \
        "框内左侧的通道差 %.0f，只有正上方同位（%.0f）的 %.0f%% —— 水印没补干净" \
        % (cur_sp, ref_sp, cur_sp / ref_sp * 100)
    return out, (y1 - y0) * (x1 - x0) / (im.width * im.height)


def cutout(im):
    """白底 -> 透明，裁紧前景包围盒。"""
    work = im.convert("RGB").copy()
    w, h = work.size
    probe = np.asarray(work).astype(int)
    assert not ((probe[:, :, 0] == MAGIC[0]) & (probe[:, :, 1] == MAGIC[1]) &
                (probe[:, :, 2] == MAGIC[2])).any(), "原图里就有品红，哨兵色得换"
    # 四角先一起验完再动手 —— 放进循环里的话，第一个角填成哨兵色之后，
    # 后面三个角读到的就是 (255,0,255)，断言自己把自己绊倒
    corners = ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))
    for sd in corners:
        assert min(work.getpixel(sd)) >= 240, \
            "四角不是白底（%s=%s），先看图" % (sd, work.getpixel(sd))
    for sd in corners:
        ImageDraw.floodfill(work, sd, MAGIC, thresh=FLOOD_THRESH)

    a = np.asarray(work).astype(int)
    mask = ((a[:, :, 0] == MAGIC[0]) & (a[:, :, 1] == MAGIC[1]) & (a[:, :, 2] == MAGIC[2]))
    assert 0.20 < mask.mean() < 0.80, "背景只啃掉 %.1f%%，阈值不对" % (mask.mean() * 100)

    # 记得把哨兵色写回白 —— 否则 MAGIC 会以 RGB(255,0,255) 留在半透明边缘上
    rgba = np.dstack([np.where(mask[:, :, None], 255, a).astype(np.uint8),
                      np.where(mask, 0, 255).astype(np.uint8)])
    out = Image.fromarray(rgba.astype(np.uint8), "RGBA")
    bbox = out.getchannel("A").getbbox()
    assert bbox is not None, "整幅被判成背景了"
    return out.crop(bbox)


def build(src, name, fname):
    im = Image.open(src).convert("RGB")
    w, h = im.size
    box = tuple(int(round(v * (w if i % 2 == 0 else h))) for i, v in enumerate(WM_FRAC))
    im, wm = strip_watermark(im, box)

    # 参照图先落盘：它是修过水印的干净原图，重跑一次就是同一张，不怕覆盖。
    # 白底要裁掉 —— 1536 方的图里人只占中间一块，不裁的话参照卡上脸小得看不清。
    ref = os.path.join(OUT_PORT, "%s_立绘参照.png" % name)
    tight(im).save(ref)

    fig = cutout(im)
    face = compose(fig)
    out = os.path.join(OUT_FACES, fname + ".png")
    face.save(out)
    print("  %-4s 修水印 %.1f%%  前景 %dx%d(原图 %d) -> %-14s %s"
          % (name, wm * 100, fig.size[0], fig.size[1], h, fname + ".png", face.size))
    print("       参照 %s" % os.path.relpath(ref, ROOT))
    return fig, face


def main():
    for name, fname, f in JOBS:
        assert name in G.CAST, "%s 不在 CAST 名册里" % name
        assert G.CAST[name][1] == fname, \
            "CAST 里 %s 的脸图名是 %s，与这里的 %s 不一致" % (name, G.CAST[name][1], fname)
        src = os.path.join(CLIP, f)
        assert os.path.exists(src), "原图不在：%s" % src
        build(src, name, fname)
    print("写好了 assets/img/faces/")


if __name__ == "__main__":
    main()
