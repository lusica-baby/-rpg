# -*- coding: utf-8 -*-
"""把 AI 生成的「一排一朝向」人物大图，转成 RPG Maker MZ 的四向行走图 / 脸图。

与 tools/make_mz_assets.py 的区别（那个用于规整网格的旧批次，仍然有效）：

1. **逐排自适应**。AI 每排的图形数量不定（3 个或 5 个），列位置逐排浮动，
   套统一网格会切歪。这里按排做列方向连通域分析，逐排各自取图。
2. **镜像补朝向**。素材常缺「朝右」。像素风水平镜像无损，比拿正面顶替贴近真实。
3. **白底转 alpha 用边缘洪泛**。不能用「亮度阈值」——角色白袖口、白鞋会被一起抠掉。
   从四角洪泛，只有与画面边缘连通的近白像素才算背景。
4. **全角色统一缩放**。若逐帧各自缩到 48×48，转身时人物会忽大忽小。

用法：
  python tools/build_char_sheet.py chars 源图 输出.png --plan 'JSON'
  python tools/build_char_sheet.py face  源图 输出.png --cols 8 --rows 1 --head

plan 的 JSON 形如：
  {"DOWN": {"row": 0}, "LEFT": {"row": 1}, "RIGHT": {"mirror": "LEFT"}, "UP": {"row": 3}}
可选的 "picks": [0,2,4] 手动指定取该排的第几个图形当三帧。
"""
import argparse
import json
import os
import sys
from collections import deque
from PIL import Image, ImageChops, ImageDraw

MZ_ROWS = ["DOWN", "LEFT", "RIGHT", "UP"]
WHITE = 255
ALPHA_TOL = 18            # 洪泛容差（作用在逐通道最小值上）：背景 255 可过，皮肤 212 不可过
CLUSTER_GAP = 14          # 列方向两个连通域间隔小于此值视为同一个图形
CLUSTER_MIN_W = 24        # 小于此宽度的连通域当噪点丢掉
ROW_CONTENT_MIN = 3       # 该列至少这么多前景像素才算「有内容」，滤掉 JPEG 噪点


# ---------------------------------------------------------------- 基础工具

def fg_mask_flags(im, bg=WHITE, th=40):
    """返回逐像素布尔前景列表（按行），用于分簇。不做 alpha，只做几何判定。"""
    px = im.convert("RGB").load()
    W, H = im.size
    rows = []
    for y in range(H):
        row = bytearray(W)
        for x in range(W):
            c = px[x, y]
            if abs(c[0] - bg) > th or abs(c[1] - bg) > th or abs(c[2] - bg) > th:
                row[x] = 1
        rows.append(row)
    return rows


def clusters(rows, x0, x1, min_w=CLUSTER_MIN_W, gap=CLUSTER_GAP, min_px=ROW_CONTENT_MIN):
    """在 [x0,x1) 列范围内找列方向连通域。"""
    H = len(rows)
    colsum = [sum(r[x] for r in rows) for x in range(x0, x1)]
    xs = [i for i, v in enumerate(colsum) if v >= min_px]
    if not xs:
        return []
    out, s, p = [], xs[0], xs[0]
    for v in xs[1:]:
        if v - p <= gap:
            p = v
        else:
            if p - s + 1 >= min_w:
                out.append((x0 + s, x0 + p))
            s = p = v
    if p - s + 1 >= min_w:
        out.append((x0 + s, x0 + p))
    return out


def tight_rows(rows, x0, x1):
    """给定列范围，返回内容的 y 范围。"""
    ys = [y for y, r in enumerate(rows) if any(r[x] for x in range(x0, x1))]
    return (min(ys), max(ys)) if ys else None


def pick3(n):
    """从 n 个图形里挑 3 帧（MZ 的三帧循环）。"""
    if n >= 3:
        return [round(i * (n - 1) / 2) for i in range(3)]
    if n == 2:
        return [0, 1, 0]
    return [0, 0, 0]


# ---------------------------------------------------------------- alpha

def white_to_alpha(frame, tol=ALPHA_TOL):
    """从四角和四边洪泛，把与边缘连通的**纯白**像素变透明；其余保持不透明。

    判定用**逐通道最小值**，不用亮度。原因是亮度会把两类东西混为一谈：
    背景是 (255,255,255)，而角色皮肤是 (252,231,212) —— 亮度 236 落在同一个
    「接近白」的区间里。用亮度做阈值，要么漏（白边残留），要么过（把整张脸抠掉）。
    取 min(r,g,b) 后：背景 255，皮肤 212，一刀分清。

    另外必须洪泛而不是全局阈值 —— 角色自身的白袖口、白鞋是封闭区域，
    全局阈值会把它们一起抠掉。
    """
    rgb = frame.convert("RGB")
    W, H = rgb.size
    # 逐通道最小值，作为「有多白」的度量
    r, g, b = rgb.split()
    probe = ImageChops.darker(ImageChops.darker(r, g), b)
    seeds = [(0, 0), (W - 1, 0), (0, H - 1), (W - 1, H - 1)]
    seeds += [(x, 0) for x in range(0, W, max(1, W // 8))]
    seeds += [(x, H - 1) for x in range(0, W, max(1, W // 8))]
    seeds += [(0, y) for y in range(0, H, max(1, H // 8))]
    seeds += [(W - 1, y) for y in range(0, H, max(1, H // 8))]
    for s in seeds:
        v = probe.getpixel(s)
        if v >= 255 - tol:
            ImageDraw.floodfill(probe, s, 7, thresh=tol)
    alpha = Image.new("L", (W, H), 255)
    ap = alpha.load()
    pp = probe.load()
    for y in range(H):
        for x in range(W):
            if pp[x, y] == 7:
                ap[x, y] = 0
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def keep_largest(im):
    """只保留最大的那个连通块，扔掉其余。

    AI 把 8 张脸排在一行时，间距常常不足一个格宽，等分切格会把邻座角色的
    头发丝带进来 —— 表现为帧边缘挂着一小条碎片。这些碎片与主体不连通，
    用连通域一刀切干净。顺带也清掉脚底那层淡淡的投影。
    """
    W, H = im.size
    src = im.getchannel("A").load()
    seen = [bytearray(W) for _ in range(H)]
    best, best_n = None, 0
    for sy in range(H):
        for sx in range(W):
            if src[sx, sy] == 0 or seen[sy][sx]:
                continue
            comp = []
            dq = deque([(sx, sy)])
            seen[sy][sx] = 1
            while dq:
                x, y = dq.popleft()
                comp.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < W and 0 <= ny < H and not seen[ny][nx] and src[nx, ny] > 0:
                        seen[ny][nx] = 1
                        dq.append((nx, ny))
            if len(comp) > best_n:
                best_n, best = len(comp), comp
    if not best:
        return im
    mask = Image.new("L", (W, H), 0)
    mp = mask.load()
    for x, y in best:
        mp[x, y] = src[x, y]
    out = im.copy()
    out.putalpha(mask)
    return out


def bleed_rgb(im, iters=3):
    """把透明像素的 RGB 换成邻近可见像素的颜色。

    缩放时若不做这一步，透明区的白色会渗进边缘，成品沿轮廓出现白边
    （$Frog 那批踩过同样的坑，只是那次渗的是紫色）。
    """
    im = im.copy()
    W, H = im.size
    px = im.load()
    for _ in range(iters):
        todo = []
        for y in range(H):
            for x in range(W):
                if px[x, y][3] > 0:
                    continue
                r = g = b = n = 0
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < W and 0 <= ny < H and px[nx, ny][3] > 0:
                        r += px[nx, ny][0]; g += px[nx, ny][1]; b += px[nx, ny][2]; n += 1
                if n:
                    todo.append((x, y, (r // n, g // n, b // n)))
        if not todo:
            break
        for x, y, c in todo:
            px[x, y] = (c[0], c[1], c[2], 0)
    return im


# ---------------------------------------------------------------- 提取

def extract_frames(src, row_h, layout):
    """layout: {方向名: {"row": i, "picks": [...]}} → {方向: [frame, frame, frame]}"""
    im = Image.open(src).convert("RGB")
    W, H = im.size
    nrows = H // row_h
    out = {}
    meta = {}
    print("源图 %dx%d -> 假定 %d 排，每排高 %d" % (W, H, nrows, row_h))
    for name, spec in layout.items():
        if "row" not in spec:
            continue
        r = spec["row"]
        y0, y1 = r * row_h, min((r + 1) * row_h, H)
        rows = fg_mask_flags(im.crop((0, y0, W, y1)))
        cls = clusters(rows, 0, W)
        print("  %-6s 排%d: %d 个图形 %s" % (name, r, len(cls), [c[0] for c in cls]))
        idxs = spec.get("picks") or pick3(len(cls))
        frames = []
        for c in idxs:
            cx0, cx1 = cls[min(c, len(cls) - 1)]
            ty = tight_rows(rows, cx0, cx1 + 1)
            fy0, fy1 = y0 + ty[0], y0 + ty[1] + 1
            frames.append(im.crop((cx0, fy0, cx1 + 1, fy1)))
        out[name] = frames
        meta[name] = idxs
    # 镜像补朝向
    for name, spec in layout.items():
        if "mirror" in spec:
            base = spec["mirror"]
            out[name] = [f.transpose(Image.FLIP_LEFT_RIGHT) for f in out[base]]
            meta[name] = "mirror(%s)" % base
            print("  %-6s 由 %s 水平镜像生成" % (name, base))
    return out, meta


def build_walk(src, out_path, layout, row_h, cell=48, alpha_tol=ALPHA_TOL):
    frames_by_dir, meta = extract_frames(src, row_h, layout)
    for name in MZ_ROWS:
        if name not in frames_by_dir:
            sys.exit("缺少方向 %s" % name)

    # 全角色统一缩放：用所有帧里的最大尺寸，保证转身时大小不变
    allf = [f for v in frames_by_dir.values() for f in v]
    mw = max(f.width for f in allf)
    mh = max(f.height for f in allf)
    scale = min(cell / mw, cell / mh)
    print("统一缩放：最大帧 %dx%d -> %.4f（帧高约 %d px）" % (mw, mh, scale, round(mh * scale)))

    sheet = Image.new("RGBA", (cell * 3, cell * 4), (0, 0, 0, 0))
    for d, name in enumerate(MZ_ROWS):
        for c, f in enumerate(frames_by_dir[name]):
            cut = keep_largest(white_to_alpha(f, alpha_tol))
            cut = bleed_rgb(cut)
            nw = max(1, int(round(cut.width * scale)))
            nh = max(1, int(round(cut.height * scale)))
            cut = cut.resize((nw, nh), Image.LANCZOS)
            x = (cell - nw) // 2
            y = cell - nh
            sheet.paste(cut, (c * cell + x, d * cell + y), cut)
        print("  行%d %-5s 帧数=%d 来源=%s" % (d, name, len(frames_by_dir[name]), meta.get(name)))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    sheet.save(out_path)
    print("写出 %s  %dx%d" % (out_path, sheet.width, sheet.height))
    return sheet


def build_face(src, out_path, cols, rows, cell=144, head=False, alpha_tol=ALPHA_TOL,
               head_h=None):
    im = Image.open(src).convert("RGB")
    W, H = im.size
    cw, ch = W // cols, H // rows
    print("源图 %dx%d -> %d 列 × %d 排，格 %dx%d" % (W, H, cols, rows, cw, ch))
    flags = fg_mask_flags(im)
    ty = tight_rows(flags, 0, W)
    print("全局内容 y 范围: %s" % (ty,))
    frames = []
    boxes = []
    for r in range(rows):
        for c in range(cols):
            x0, y0 = c * cw, r * ch
            if head:
                # 半身像只取头部：从该格自己的内容顶端往下量 head_h。
                # 高度必须容得下「发顶→下巴」，只取一个格宽会把嘴和下巴切掉。
                ct = tight_rows(flags, x0, x0 + cw)
                top = (y0 + ct[0]) if ct else y0
                hh = head_h or round(cw * 1.2)
                box = (x0, top, x0 + cw, min(top + hh, H))
            else:
                box = (x0, y0, x0 + cw, y0 + ch)
            frames.append(im.crop(box))
            boxes.append(box)
    for i, b in enumerate(frames[:8]):
        print("  格%d 裁 %s  %dx%d" % (i, boxes[i], b.width, b.height))
    sheet = Image.new("RGBA", (cell * 4, cell * 2), (0, 0, 0, 0))
    for i, f in enumerate(frames[:8]):
        cut = keep_largest(white_to_alpha(f, alpha_tol))
        cut = bleed_rgb(cut)
        s = min(cell / cut.width, cell / cut.height)
        cut = cut.resize((max(1, round(cut.width * s)), max(1, round(cut.height * s))), Image.LANCZOS)
        x = (i % 4) * cell + (cell - cut.width) // 2
        y = (i // 4) * cell + cell - cut.height
        sheet.paste(cut, (x, y), cut)
        print("  格%d <- %s" % (i, boxes[i]))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    sheet.save(out_path)
    print("写出 %s  %dx%d" % (out_path, sheet.width, sheet.height))
    return sheet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["chars", "face"])
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--plan", default=None)
    ap.add_argument("--row-h", type=int, default=480)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--rows", type=int, default=2)
    ap.add_argument("--head", action="store_true", help="脸图按头顶裁方形，让头占满对话框")
    ap.add_argument("--head-h", type=int, default=None, help="脸图头部裁切高度（默认 1.2 倍格宽）")
    ap.add_argument("--alpha-tol", type=int, default=ALPHA_TOL)
    a = ap.parse_args()

    if a.mode == "chars":
        if not a.plan:
            sys.exit("chars 模式必须给 --plan")
        build_walk(a.src, a.out, json.loads(a.plan), a.row_h, alpha_tol=a.alpha_tol)
    else:
        build_face(a.src, a.out, a.cols, a.rows, head=a.head, alpha_tol=a.alpha_tol,
                   head_h=a.head_h)


if __name__ == "__main__":
    main()
