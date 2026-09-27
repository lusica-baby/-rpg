# -*- coding: utf-8 -*-
"""宰 的脸图 —— 从用户给的 6 张全身像里取一张，裁出头肩

为什么要单独一个脚本：`import_faces.py` 吃的是 4×2 合成表（一格一个胸像），
`import_portrait_face.py` 吃的是「整幅就是一个人」的单张立绘、且要处理横跨衣服的
水印。宰的源料是**第三种**：用户贴的一批全身行姿像，一张里人只占中间一块，
而且必须自己划「从哪切到哪」才算得出胸像构图。三者的共同点只有构图规格，
那部分共用 `import_faces.compose*()`。

## 为什么是 654 这一张

同一角色的 6 个姿态（654/656/659/663/664/665）逐张看过：

| 键 | 姿态 | 判 |
|---|---|---|
| 654 | 正面偏侧，双展脚齐全 | **选它** |
| 656 | 侧身，只见半边脸 | 太偏 |
| 659 | 朝观者右侧 | 与全套脸图（一律偏左）不一致 |
| 663 | 正面，但**举着一只手**入画 | 手切在框里很脏 |
| 664 | 手指抵着下巴 | 抠不掉，且表情成"沉吟"不合堂上那场 |
| 665 | 侧身偏转 | 同 656 |

654 的表情也对得上：浓眉、直视、压着的髭须 —— 堂上那句「虫呢。」要的就是这个。

## 两个坑

1. **水印把包围盒撑大了**。6 张原图右下角都有「豆包AI生成」，是灰字（约 200），
   白底 floodfill 啃不掉，于是 `getbbox()` 把前景算成 1121×1455。
   它同时污染**横向**：水印在人物右缘之外，宽度也虚胖。切掉底部 10% 之后是
   803×1331 —— 人物脚底在约 85% 处，切 10% 伤不到。不切的话 HEAD_FRAC
   就变成「占图+水印」的比例，换张水印大的原图同一 FRAC 会取到别的地方。
2. **必须按脸居中，不能按包围盒居中**。行姿的手臂摆动会把包围盒中心拉偏
   （654 偏 12px），照 `compose()` 那样居中的话，一侧展脚会顶出画 ——
   而展脚正是这次重画的全部意义。所以走 `compose_face_centered()`。

用法：python tools/import_zai_face.py
产出：assets/img/faces/Zai.png                  144×144，进游戏
      docs/accept/portraits/宰_脸图对照.png     新旧对比 + 与同族脸图并排
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game_data as G                                          # noqa: E402
from import_faces import (FACE_PX, TOP_PAD, compose_face_centered,  # noqa: E402
                          face_axis, checker)
from face_brief import font                                    # noqa: E402
from import_portrait_face import cutout                        # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIP = os.path.join(os.path.expanduser("~"), ".workbuddy", "clipboard-images")
OUT_FACES = os.path.join(ROOT, "assets", "img", "faces")
OUT_DOCS = os.path.join(ROOT, "docs", "accept", "portraits")

NAME, FNAME = "宰", "Zai"
STAMP = "clipboard-2026-09-23T13-20-49-"    # 用户那一批 11 张的公共时间戳
KEY = "654"

SRC_CUT = 0.90      # 先切掉底部 10%：水印的地盘，留着会把包围盒横向纵向都撑大
HEAD_FRAC = 0.52    # 取紧裁后的顶部多少。**用脸宽标定出来的**：这个值给出脸宽 59，
                    # 与 LiXu 61 / Witch 59 / Zai 58 同量级（其余几张肤色判据会被
                    # 浅色衣服污染，只有这三张深袍的可信）
FACE_W_BAND = (50, 72)
OLD = os.path.join(ROOT, ".scratch", "old", "Zai_before.png")


def src_of(key):
    for f in os.listdir(CLIP):
        if f.startswith(STAMP + key + "Z"):
            return os.path.join(CLIP, f)
    raise SystemExit("原图不在剪贴板目录里：%s%s*" % (STAMP, key))


def wing_span(face):
    """展脚（乌纱帽两侧的翅）的横向跨度 —— 在帽子那一条带里找最宽的一行。

    用来断言展脚完整入画。留这道断言是因为「按包围盒居中」会悄悄把它切掉一侧，
    而切掉展脚之后图看着仍然"正常"，只是这次重画白做了。
    """
    al = np.asarray(face).astype(int)[:, :, 3] > 128
    band = al[:int(FACE_PX * 0.34)]
    best = (0, None)
    for y in range(band.shape[0]):
        xs = np.where(band[y])[0]
        if len(xs) and (xs[-1] - xs[0]) > best[0]:
            best = (int(xs[-1] - xs[0]), (int(xs[0]), int(xs[-1]), y))
    return best[1]


def build():
    src = src_of(KEY)
    raw = Image.open(src)
    cut = raw.crop((0, 0, raw.width, round(raw.height * SRC_CUT)))
    fig = cutout(cut)                       # 白底 -> 透明 + 裁紧包围盒
    top = fig.crop((0, 0, fig.size[0], round(fig.size[1] * HEAD_FRAC)))
    face = compose_face_centered(top)

    cx, fx0, fx1 = face_axis(top)
    print("  源      %s" % os.path.basename(src))
    print("  人物    %dx%d（切掉底部 %.0f%% 之后）" % (fig.size[0], fig.size[1], (1 - SRC_CUT) * 100))
    print("  取顶部  %.0f%% = %dpx" % (HEAD_FRAC * 100, top.size[1]))
    print("  脸中轴  取景内 x=%d/%d（%.0f%%）" % (cx, top.size[0], cx / top.size[0] * 100))

    # ---- 断言：与同族脸图对得上 ----
    a = np.asarray(face.convert("RGBA")).astype(int)
    rgb, al = a[:, :, :3], a[:, :, 3]
    m = (al > 200) & (rgb[:, :, 0] > 130) & (rgb[:, :, 0] - rgb[:, :, 2] > 38) \
        & (rgb[:, :, 0] - rgb[:, :, 1] > 18) & (rgb[:, :, 1] - rgb[:, :, 2] > 15)
    ys, xs = np.where(m)
    fw = int(xs.max()) - int(xs.min()) + 1
    print("  成图    脸宽 %d（同族 58~61）" % fw)
    assert FACE_W_BAND[0] <= fw <= FACE_W_BAND[1], \
        "脸宽 %d 落在 %s 之外 —— HEAD_FRAC 该调了" % (fw, FACE_W_BAND)

    x0, x1, wy = wing_span(face)
    print("  展脚    跨 x %d..%d（画布 0..%d）" % (x0, x1, FACE_PX - 1))
    assert x0 >= 1 and x1 <= FACE_PX - 2, \
        "展脚顶到画布边（%d..%d）—— 说明没按脸居中，或者 HEAD_FRAC 太大" % (x0, x1)

    bbox = face.getchannel("A").getbbox()
    assert bbox[1] == TOP_PAD, "头顶没落在 %d（实际 %d）" % (TOP_PAD, bbox[1])
    assert bbox[3] == FACE_PX, "肩部没出画（前景底边 %d）" % bbox[3]

    out = os.path.join(OUT_FACES, FNAME + ".png")
    face.save(out)
    print("  写好    %s" % os.path.relpath(out, ROOT))
    return face


def compare(new):
    """验收图：新脸 / 旧脸 / 同族三张 / 行走图 —— 一屏看完。"""
    tiles = [("新 %s（654）" % NAME, new), ("旧 Zai（换掉的那张）", None),
             ("LiXu（同族，原来最容易撞脸）", None), ("Youth（同族）", None)]
    imgs = [new, Image.open(OLD).convert("RGBA") if os.path.exists(OLD) else None,
            Image.open(os.path.join(OUT_FACES, "LiXu.png")).convert("RGBA"),
            Image.open(os.path.join(OUT_FACES, "Youth.png")).convert("RGBA")]

    S, PAD, CAP = FACE_PX * 2, 16, 46
    rows = 2
    W = PAD + 2 * (S + PAD)
    H = 62 + rows * (S + CAP + PAD) + 190
    board = Image.new("RGB", (W, H), (247, 247, 250))
    d = ImageDraw.Draw(board)
    d.text((PAD, 14), "宰 脸图 —— 换掉「跟里胥像同一个人」的那张",
           font=font(26), fill=(30, 30, 38))
    for i, (tag, _) in enumerate(tiles):
        im = imgs[i]
        rr, cc = divmod(i, 2)
        x, y = PAD + cc * (S + PAD), 62 + rr * (S + CAP + PAD)
        if im is None:
            d.rectangle([x, y, x + S - 1, y + S - 1], outline=(190, 120, 120))
            d.text((x + 12, y + 12), "旧图已归档到 .scratch/old/", font=font(18), fill=(180, 60, 60))
        else:
            th = checker(S, 12).convert("RGBA")
            th.alpha_composite(im.resize((S, S), Image.NEAREST))
            board.paste(th.convert("RGB"), (x, y))
        d.rectangle([x, y, x + S - 1, y + S - 1], outline=(90, 90, 100))
        d.text((x, y + S + 6), tag, font=font(18), fill=(30, 30, 38))

    # 行走图放最后：脸图与行走图对不上，玩家会看成两个人。
    # 这一栏不是凑数 —— 换掉的那张脸跟 $Zai 就完全对不上
    # （行走图是展脚乌纱帽 + 朱红袍，旧脸是无髯的藏青软脚幞头）。
    walk = Image.open(os.path.join(ROOT, "assets", "img", "characters", "$Zai.png")).convert("RGBA")
    w2 = walk.crop((0, 0, 48, 48)).resize((S // 2, S // 2), Image.NEAREST)
    wy = 62 + rows * (S + CAP + PAD) + 20
    board.paste(checker(S // 2, 8), (PAD, wy), None)
    board.paste(w2, (PAD, wy), w2)
    tx = PAD + S // 2 + 16
    for i, line in enumerate((
            "行走图 $Zai 第 1 帧",
            "脸图与它必须认得出是同一个人。",
            "新脸对得上：展脚 + 朱红圆领 + 髭须。",
            "旧脸（无髯、藏青幞头）连行走图都对不上。",
            "底边切在肩，看不到补子 —— 规格如此。")):
        d.text((tx, wy + 4 + i * 26), line, font=font(17 if i == 0 else 16),
               fill=(30, 30, 38) if i == 0 else (90, 96, 110))
    out = os.path.join(OUT_DOCS, "宰_脸图对照.png")
    board.save(out)
    print("  验收图  %s" % os.path.relpath(out, ROOT))


def main():
    assert NAME in G.CAST, "%s 不在 CAST 名册里" % NAME
    assert G.CAST[NAME][1] == FNAME, \
        "CAST 里 %s 的脸图名是 %r，与这里的 %r 不一致" % (NAME, G.CAST[NAME][1], FNAME)
    print("宰 脸图：从 %s%s* 取 %s" % (STAMP, KEY, KEY))
    face = build()
    compare(face)
    print("写好了 assets/img/faces/%s.png" % FNAME)


if __name__ == "__main__":
    main()
