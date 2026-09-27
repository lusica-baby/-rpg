# -*- coding: utf-8 -*-
"""成名 的脸图 —— 从 671 那张**双人半身像**的左半取

源料是第四种形态（前三种见 `import_faces` / `import_portrait_face` /
`import_zai_face` 的模块注释）：一张 1536×1536 里**并排两个人**，左边成名、
右边成妻。于是比宰那一步多两件事：

1. **要自己划左右**。宰是「一整幅一个人」，紧包围盒就是那个人；这里紧包围盒
   是「两个人 + 中间一条缝」。量出来的缝在 x=909..948（y=1072 那行最窄），
   成名自己的右肩伸到 x≈908 —— 所以裁窗右界取 900，既留全他的肩、又不碰成妻。
   左界取 0：他的直裰在原图里就被画到画外了（y≥1300 时贴到 x=0），这一侧本来
   就是「出画」，不是被我裁掉的。

2. **水印不用管**。「豆包AI生成」整块在右半（压在成妻衣袍上，x 1266..1528），
   裁窗右界 900 离它还有 366px —— 不像成子那张要竖着插值补回来。

## 构图：为什么不能直接吃紧包围盒

成子那张「整幅就是一个人」，`cutout()` 的紧包围盒直接丢给 `compose()` 就对。
这张不行：紧包围盒一直含到底部 1535 行（两人的衣裳在下方相接），高度是「半身
+ 一大截袍子」，照它缩到 138 的话头会小一半。

所以按**头高**倒推裁窗高度 —— 这是与其余七张对齐的唯一口径：

    头高(发顶→下巴) 缩到 138 后要落在 90px（成子那张实测值，配角 5 张是 86）

    发顶 y=139（逐列首个非白行的最小值，就是发髻尖）
    下巴 y=748（肤色逐行宽度 347→147→88 的骤降处：脸到此为止，下面是脖子）
    H = 609  →  裁窗高 = 138*609/90 = 934

两条独立佐证（都是量出来的，不是估的）：
  - 脸宽：源图肤色列簇 275..683 = 409px，乘 0.1478 得 **60px**，
    与同族的 LiXu 61 / Witch 59 / Zai 59 同量级；
  - 肩宽：裁窗底行的直裰跨 x 63..908，缩后落在画布 10..135 = **126px 宽**，
    与同族的 Guard 135 / Mother 136 / ChengZi 106 同量级（规格是「底边把肩切掉」）。

用法：python tools/import_chengming_face.py
产出：assets/img/faces/ChengMing.png              144×144，进游戏
      docs/accept/portraits/成名_脸图对照.png     新旧对比 + 同族并排 + 行走图
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import game_data as G                                          # noqa: E402
from import_faces import (FACE_PX, TOP_PAD, compose_face_centered,  # noqa: E402
                          face_axis, checker)
from face_brief import font, wrap                            # noqa: E402
from import_portrait_face import cutout                        # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIP = os.path.join(os.path.expanduser("~"), ".workbuddy", "clipboard-images")
OUT_FACES = os.path.join(ROOT, "assets", "img", "faces")
OUT_DOCS = os.path.join(ROOT, "docs", "accept", "portraits")
OLD_DIR = os.path.join(ROOT, ".scratch", "old")

NAME, FNAME = "成名", "ChengMing"
SRC = os.path.join(CLIP, "clipboard-2026-09-23T13-20-49-671Z-fe2bb891.jpg")

# 量出来的源图几何（.scratch/probe_cm_geom.py / probe_cm_prof.py）：
TOP_Y = 139          # 发顶：逐列首个非白行的最小值
CHIN_Y = 748         # 下巴：肤色逐行宽度 147 -> 88 的骤降
X0, X1 = 0, 900      # 左界=直裰原图出画处；右界=两人最窄缝(909)之左
WM_X0 = 1266         # 「豆包AI生成」左缘（按图幅 0.8242）—— 裁窗必须离它足够远
HEAD_PX = 90         # 缩到 138 后头高要落的像素数（同族口径）
FACE_W_BAND = (50, 72)          # 与 LiXu 61 / Witch 59 / Zai 59 同量级
SHOULDER_BAND = (100, 143)      # 底行肩宽：ChengZi 106 … Zai 141
PAD = 24             # 给 cutout 的白边（它断言四角是白的，见下）
OLD = os.path.join(OLD_DIR, "ChengMing_before.png")


def build():
    im = Image.open(SRC).convert("RGB")
    head = CHIN_Y - TOP_Y
    crop_h = round((FACE_PX - TOP_PAD) * head / HEAD_PX)     # 138*H/90
    win = (X0, TOP_Y, X1, TOP_Y + crop_h)
    assert win[2] < WM_X0, "裁窗右界 %d 撞上水印左缘 %d 了" % (win[2], WM_X0)

    # 去背。**不能直接把裁窗丢给 cutout**：它断言四角是白的，而这个窗口的下沿
    # 正好落在直裰上（两个下角都是衣服）。贴到白底画布上再走同一条 floodfill ——
    # 四角有白边，断言成立；回裁后紧包围盒本来就等于「内容自己的外接框」，
    # 上沿仍是发顶、下沿仍是衣服，规格不变。
    winim = im.crop(win)
    can = Image.new("RGB", (winim.width + 2 * PAD, winim.height + 2 * PAD), (255, 255, 255))
    can.paste(winim, (PAD, PAD))
    fig = cutout(can)

    print("  源      %s" % os.path.basename(SRC))
    print("  头高    发顶 y=%d -> 下巴 y=%d = %dpx；缩到 138 后应落 %dpx"
          % (TOP_Y, CHIN_Y, head, HEAD_PX))
    print("  裁窗    x %d..%d, y %d..%d（%dx%d）"
          % (win[0], win[2], win[1], win[3], win[2] - win[0], crop_h))
    # 上/下沿必须各有内容：否则发顶没落在 TOP_PAD、或下沿不是衣服
    assert fig.size[1] == crop_h, \
        "裁窗上下沿没被内容顶满（%d != %d）—— 发顶不在 y=%d，或下巴量错了" \
        % (fig.size[1], crop_h, TOP_Y)
    assert fig.size[0] > (X1 - X0) * 0.8, \
        "内容只占裁窗宽度的 %.0f%% —— 右界划进成妻那边了？" % (fig.size[0] / (X1 - X0) * 100)
    print("  前景    %dx%d" % fig.size)

    face = compose_face_centered(fig)

    # ---- 断言：与同族脸图同一把尺子 ----
    a = np.asarray(face.convert("RGBA")).astype(int)
    rgb, al = a[:, :, :3], a[:, :, 3]
    m = (al > 200) & (rgb[:, :, 0] > 130) & (rgb[:, :, 0] - rgb[:, :, 2] > 38) \
        & (rgb[:, :, 0] - rgb[:, :, 1] > 18) & (rgb[:, :, 1] - rgb[:, :, 2] > 15)
    ys, xs = np.where(m)
    fw, fcx = int(xs.max()) - int(xs.min()) + 1, (int(xs.min()) + int(xs.max())) // 2
    print("  成图    脸宽 %d（同族 59~61）  脸中轴 x=%d（画布中线 72）" % (fw, fcx))
    assert FACE_W_BAND[0] <= fw <= FACE_W_BAND[1], \
        "脸宽 %d 落在 %s 之外 —— 头高口径要重标" % (fw, FACE_W_BAND)
    assert abs(fcx - FACE_PX // 2) <= 4, \
        "脸中轴偏了 %d px —— compose_face_centered 的肤色判据在这张上失准？" % (fcx - FACE_PX // 2)

    solid = al > 128
    bot = int(solid[FACE_PX - 1].sum())
    print("  肩宽    底行 %d（同族 ChengZi 106 ~ Zai 141）" % bot)
    assert SHOULDER_BAND[0] <= bot <= SHOULDER_BAND[1], \
        "底行肩宽 %d 落在 %s 之外 —— 裁窗太高/太低了" % (bot, SHOULDER_BAND)

    bbox = face.getchannel("A").getbbox()
    assert bbox[1] == TOP_PAD, "发顶没落在 y=%d（实际 %d）" % (TOP_PAD, bbox[1])
    assert bbox[3] == FACE_PX, "肩部没出画（前景底边 %d）" % bbox[3]

    out = os.path.join(OUT_FACES, FNAME + ".png")
    face.save(out)
    print("  写好    %s" % os.path.relpath(out, ROOT))
    return face


def archive_old():
    """旧脸挪进 .scratch/old/ —— 用 os.replace 而不是 os.remove。

    本机有安全删除层，`os.remove` 会被挡下（连报错都不一定看得见）；
    `os.replace` 是「搬走」，一路畅通。也别用 shutil.move：目标已存在时它会
    退化成 copy+unlink，照样撞上那道墙。

    **归档只做一次**（档案已存在就直接返回）。第一版没这道闸，重跑一次就把
    上一次生成的**新脸**当成"旧脸"搬进去盖掉了档案 —— 素材重跑是家常便饭，
    这种工具必须幂等。
    """
    src = os.path.join(OUT_FACES, FNAME + ".png")
    if not os.path.exists(src) or os.path.exists(OLD):
        return
    os.makedirs(OLD_DIR, exist_ok=True)
    os.replace(src, OLD)
    print("  旧脸    -> %s" % os.path.relpath(OLD, ROOT))


def compare(new):
    """验收图：新脸 / 旧脸 / M1 同场戏的另两张 —— 一屏看完口径与风格。

    文字一律走 `wrap`：第一版按字数硬拍一行，右侧被画布裁掉半句
    （"脸宽 59~"、"风格与..."），看图的人只会以为我漏写了。
    """
    def cell0(path):
        """库存表情表是 576x288 的 8 格表，取第 0 格 —— 那才是引擎真正画出来的。"""
        im = Image.open(path).convert("RGBA")
        return im.crop((0, 0, 144, 144)) if im.size != (144, 144) else im

    def note(d, xy, text, fnt, fill, max_w):
        """折行落字，返回下一行的 y。"""
        y = xy[1]
        for line in wrap(d, text, fnt, max_w):
            d.text((xy[0], y), line, font=fnt, fill=fill)
            y += int(fnt.size * 1.5)
        return y

    tiles = [
        ("新 成名（671 左半，144×144）", new, (30, 118, 76)),
        ("旧 ChengMing（库存 8 格表 第 0 格）", cell0(OLD) if os.path.exists(OLD) else None,
         (176, 42, 42)),
        ("同族口径：ChengZi（M1 同场戏）", cell0(os.path.join(OUT_FACES, "ChengZi.png")),
         (90, 96, 110)),
        ("同族口径：ChengQi 成妻（也是 8 格表）",
         cell0(os.path.join(OUT_FACES, "ChengQi.png")), (176, 120, 42)),
    ]
    S, PADW, CAP, M = FACE_PX * 2, 16, 50, 26
    W = PADW + 2 * (S + PADW)
    H = 150 + 2 * (S + CAP + PADW) + 250
    board = Image.new("RGB", (W, H), (247, 247, 250))
    d = ImageDraw.Draw(board)
    Wf = W - M * 2
    d.text((M, 16), "成名 脸图 —— 主角这张此前是库存粗像素表", font=font(26), fill=(30, 30, 38))
    note(d, (M, 52), "构图口径与现有七张一致：144×144、发顶距顶 6px、底边把肩切掉、"
                     "脸宽落在 59~61（同族 LiXu 61 / Witch 59 / Zai 59）。",
         font(17), (120, 126, 140), Wf)
    top = 118
    for i, (tag, im, col) in enumerate(tiles):
        rr, cc = divmod(i, 2)
        x, y = PADW + cc * (S + PADW), top + rr * (S + CAP + PADW)
        if im is None:
            d.rectangle([x, y, x + S - 1, y + S - 1], outline=(190, 120, 120))
            d.text((x + 12, y + 12), "旧图已归档 .scratch/old/", font=font(18), fill=(180, 60, 60))
        else:
            th = checker(S, 12).convert("RGBA")
            th.alpha_composite(im.resize((S, S), Image.NEAREST))
            board.paste(th.convert("RGB"), (x, y))
        d.rectangle([x, y, x + S - 1, y + S - 1], outline=col, width=3)
        note(d, (x, y + S + 8), tag, font(18), (30, 30, 38), S)

    walk = Image.open(os.path.join(ROOT, "assets", "img", "characters",
                                   "$ChengMing.png")).convert("RGBA")
    w2 = walk.crop((0, 0, 48, 48)).resize((S // 2, S // 2), Image.NEAREST)
    wy = top + 2 * (S + CAP + PADW) + 22
    board.paste(checker(S // 2, 8), (PADW, wy), None)
    board.paste(w2, (PADW, wy), w2)
    tx, tw = PADW + S // 2 + 18, W - (PADW + S // 2 + 18) - M
    y = wy + 2
    for line, c in (("行走图 $ChengMing 第 1 帧", (30, 30, 38)),
                    ("新脸对得上：网巾 + 青灰直裰 + 米白交领，清瘦、眉间带愁。", (90, 96, 110)),
                    ("旧脸是同一个包里的粗像素表（576×288，8 种表情），"
                     "与其余七张不成一族。", (90, 96, 110)),
                    ("注：ChengQi（成妻）也是这个包的 8 格表，M1 有三处对话在用，"
                     "同样是另一族笔法。", (176, 120, 42))):
        y = note(d, (tx, y), line, font(16), c, tw) + 8
    out = os.path.join(OUT_DOCS, "成名_脸图对照.png")
    board.save(out)
    print("  验收图  %s" % os.path.relpath(out, ROOT))


def main():
    assert NAME in G.CAST, "%s 不在 CAST 名册里" % NAME
    assert G.CAST[NAME][1] == FNAME, \
        "CAST 里 %s 的脸图名是 %r，与这里的 %r 不一致" % (NAME, G.CAST[NAME][1], FNAME)
    assert os.path.exists(SRC), "原图不在：%s" % SRC
    print("成名 脸图：%s" % os.path.basename(SRC))
    archive_old()
    face = build()
    compare(face)
    print("写好了 assets/img/faces/%s.png" % FNAME)


if __name__ == "__main__":
    main()
