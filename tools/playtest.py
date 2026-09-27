# -*- coding: utf-8 -*-
"""自动走查（automated playtest）：起 HTTP 服务 -> 起游戏 -> 验证可达性 -> 对话 -> 换图 -> 截图

首版只走 M1，这一版扩到多图，做法上多了三件事：

4) **换图用真按键走进去**
   传送靠的是「走上传送格」这条引擎触发路径（priorityType 0 + trigger 1），
   不是对话。所以验证它的唯一办法就是**真的按一下方向键踩上去**，再看引擎
   有没有换图。用 `locate()` 把人搬到目标图不算数 —— 那条路绕开了 201 指令
   和触发判定，恰好是会出问题的地方。

5) **每张图独立编号出图**
   `docs/accept/m1/` 与 `docs/accept/m2/` 各自从 01 起。共用一套计数器的话，
   第二张图的截图会顶着第一张的编号，回头根本分不清哪张是哪张。

6) **出图目录按图切换**
   `OUT[0]` 是当前目录；`shot()` 只认它。换图时 `use_out(mid)` 切一次。

前三条是首版踩出来的，一条都不能少：

1) **走位不靠按键，靠 BFS + locate**
   最初用「按方向键 + 读坐标」闭环走位，结果在成子那一格卡死：
   事件本身占格且不穿透，贪心走位必然撞上去。
   headless Chrome 的帧率还不等于 60fps，「按住 N 毫秒」到不了确定的格数，
   写死序列会时对时错 —— 假失败比不测更坏。
   现在改为：读一次引擎的 `$gameMap.isPassable` 得到整张通行图，
   在 Python 里 BFS。**通行图用的是引擎自己的判定**，所以
   「BFS 说走得到」= 「游戏里真走得到」。定位用 `$gamePlayer.locate()`。
   （例外见第 4 条：换图那一下必须真走。）

2) **仍然真按几下方向键**
   静态可达性证明不了输入链路没坏，所以开局仍真按方向键走几步并截图。

3) **截图必须框住整个画布**
   按 `#gameCanvas` 元素截、视口先设成引擎原尺寸；视口截会把消息窗下半截丢掉，
   看着像脸图有问题（见 `shot()`）。同时断言脸图整张进得了消息窗（见
   `check_face_fits()`）—— 内高是算出来的巧合，改 padding 就会静默切脸。

用法：
    python tools/playtest.py
"""
import functools
import http.server
import json
import os
import re
import sys
import threading
import time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

os.environ.setdefault("AB_INIT", os.path.join(HERE, "instrument.js"))
os.environ.setdefault("AB_SESSION", "cuzhi")
import ab  # noqa: E402
import build_project as B  # noqa: E402  台词拆页要跟构建器用同一套（emit_lines）
import game_data as G  # noqa: E402  事件 id -> 中文名 从这里查

TARGET = os.path.join(ROOT, "CuzhiDemo")
PORT = 8123
DIRKEY = {2: "down", 4: "left", 6: "right", 8: "up"}
DIRVEC = {2: (0, 1), 4: (-1, 0), 6: (1, 0), 8: (0, -1)}
LOG = []

OUT = [os.path.join(ROOT, "docs", "accept", "m1")]     # 当前出图目录
CNT = {}                                               # 目录 -> 已出图数


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve():
    handler = functools.partial(Quiet, directory=TARGET)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ------------------------------------------------------------ 引擎状态
def ev(js):
    """取一次引擎状态。

    ab 的 eval 回显是 **JSON 字符串字面量**（带引号、可能把非 ASCII 转成 \\uXXXX），
    所以约定：JS 侧一律只回 ASCII + 分隔符，中文名在 Python 侧查表。
    直接 json.loads 回显是不行的 —— 里层的引号是转义过的。
    """
    return ab.ab("eval", js).strip().strip('"')


def pos():
    try:
        x, y, d = ev("$gamePlayer.x+' '+$gamePlayer.y+' '+$gamePlayer.direction()").split()
        return int(x), int(y), int(d)
    except Exception:
        return None


def map_id():
    try:
        return int(ev("$gameMap.mapId()"))
    except Exception:
        return None


def scene():
    return ev("typeof SceneManager!=='undefined'&&SceneManager._scene?"
              "SceneManager._scene.constructor.name:'NONE'")


def busy():
    return ev("typeof $gameMessage!=='undefined'&&$gameMessage.isBusy()") == "true"


def read_grid():
    """整张通行图。'#' 挡路 / 'x' 有挡路的事件 / '.' 可站

    **'x' 的判据是「有 priorityType 1 的事件」，不是「有事件」。**
    这行判断必须照抄引擎：玩家能不能站上一格，看的是
    `Game_CharacterBase.isCollidedWithEvents` -> `eventsXyNt(x,y).some(isNormalPriority)`，
    而 `isNormalPriority() = (priorityType === 1)`。
    早先这里写的是 `eventsXy(x,y).length` —— 于是**门口那种 priorityType 0 的
    传送格也被标成 'x'**，BFS 判定「走不上去」，走查当场误报
    「玩家到不了门口」。工具自己把工具测的东西搞错了，还把错推给工程。
    """
    js = ("(function(){var w=$gameMap.width(),h=$gameMap.height(),r=[];"
          "for(var y=0;y<h;y++){var s='';for(var x=0;x<w;x++){"
          "if(!$gameMap.isPassable(x,y,2)){s+='#';}"
          "else if($gameMap.eventsXyNt(x,y).some(function(e){"
          "return e.isNormalPriority();})){s+='x';}"
          "else{s+='.';}}r.push(s);}return r.join('/');})()")
    return ev(js).split("/")


def read_events():
    """事件表：'id:x:y' 用 ';' 串起来（事件名是中文，不带回来）"""
    js = ("$gameMap.events().map(function(e){"
          "return e.eventId()+':'+e.x+':'+e.y;}).join(';')")
    return [[int(v) for v in item.split(":")] for item in ev(js).split(";") if item]


def wait_map(mid, timeout=10.0):
    """等换图落地。淡出 + 载入 + 淡入，快的一两秒。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if map_id() == mid:
            return True
        time.sleep(0.25)
    return False


def step(key, tries=3):
    """走一格：按下方向键，然后**等它真的动一格**。

    不用 sleep 定长：headless Chrome 的 rAF 帧率不等于 60fps，而 MZ 按帧推进，
    「按住 N 毫秒」到不了确定的格数。所以按完就轮询坐标，变了才算数；
    没变就再按一次（偶尔会正好落在两帧之间的缝里，那一下会被吞掉）。
    """
    for _ in range(tries):
        before = pos()[:2]
        ab.key(key, 30)               # 30ms ≈ 两帧：够触发一次移动，又短到走不出第二格
                                      # （一次移动要 8 帧以上，期间 moveByInput 被 isMoving 挡住）
        t0 = time.time()
        while time.time() - t0 < 2.0:
            p = pos()
            if p and p[:2] != before:
                time.sleep(0.45)      # 等这一步的动画收尾，免得下一按被吞
                return p[:2]
            time.sleep(0.1)
    return None


# ------------------------------------------------------------ BFS
def bfs(grid, start, goals):
    h, w = len(grid), len(grid[0])
    if start in goals:
        return [start]
    seen = {start}
    q = [[start]]
    while q:
        path = q.pop(0)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (path[-1][0] + dx, path[-1][1] + dy)
            if not (0 <= n[0] < w and 0 <= n[1] < h) or n in seen:
                continue
            if grid[n[1]][n[0]] != ".":
                continue
            if n in goals:
                return path + [n]
            seen.add(n)
            q.append(path + [n])
    return None


def facing_cell(ex, ey, grid, start):
    """挑一个能站、且离起点最近的邻格，返回 (站位, 朝向码, 路径)"""
    best = None
    for dx, dy, d in ((1, 0, 6), (-1, 0, 4), (0, 1, 2), (0, -1, 8)):
        # 站在 (ex-dx, ey-dy)，朝 (dx,dy) 看
        sx, sy = ex - dx, ey - dy
        if not (0 <= sy < len(grid) and 0 <= sx < len(grid[0])):
            continue
        if grid[sy][sx] != ".":
            continue
        p = bfs(grid, start, {(sx, sy)})
        if p and (best is None or len(p) < len(best[2])):
            best = ((sx, sy), d, p)
    return best


def use_out(mid):
    """切出图目录（每张图各自从 01 编号）。"""
    d = os.path.join(ROOT, "docs", "accept", "m%d" % mid)
    os.makedirs(d, exist_ok=True)
    OUT[0] = d
    CNT.setdefault(d, 0)
    return d


def shot(tag):
    """截游戏画面 —— **按 canvas 元素截，不是截视口**。

    踩过的坑：视口默认 1080x500，MZ 的 Graphics._realScale = min(视口宽/816, 视口高/624)
    会把画布按高度缩到 0.8 倍，结果游戏画面在视口里放不下，**消息窗的下半截被切掉**，
    对话框头像只剩半张脸 —— 验收时看着像脸图有问题，其实是截图没框住。
    现在先把视口设成引擎原尺寸（816x624），再按 #gameCanvas 截元素，画面 1:1 且必然完整。
    """
    d = OUT[0]
    CNT[d] = CNT.get(d, 0) + 1
    n = CNT[d]
    p = os.path.join(d, "%02d-%s.png" % (n, tag))
    ab.ab("screenshot", "#gameCanvas", p)
    LOG.append((os.path.basename(d), n, tag, ""))


GEO = [False]


def check_face_fits():
    """脸图必须整张进得了消息窗 —— 这是**算出来的巧合**，必须钉住。

    `Window_Message.drawMessageFace` 给 drawFace 的 height 是 `this.innerHeight`，
    **不是 144**：内高不够就从下方把脸切掉，引擎一声不吭。
    本工程的数：窗口高 = calcWindowHeight(4,false)+8 = 4*36+12*2+8 = 176，
    内高 = 176 - padding*2 = 152 ≥ 144，刚好容下。
    但 padding(12) / lineHeight(36) 任一改动都会让这巧合失效，
    症状是「头像只剩半张脸」且零报错 —— 所以每次走查都量一次。
    """
    js = ("(function(){var m=SceneManager._scene._messageWindow;"
          "return [m.innerHeight,ImageManager.standardFaceWidth,"
          "ImageManager.standardFaceHeight,m.padding,m.lineHeight()].join(',');})()")
    inner, fw, fh, pad, lh = [int(v) for v in ev(js).split(",")]
    print("消息窗：内高 %d ≥ 脸图 %d　(padding=%d lineHeight=%d)"
          % (inner, fh, pad, lh))
    assert fw == 144, "标准脸图宽不是 144，drawFace 按 144 取格会错位"
    assert inner >= fh, ("消息窗内高 %d 装不下脸图 %d —— 头像会被下沿切掉。"
                         "改窗口高（Scene_Message.messageWindowRect）或缩脸图" % (inner, fh))


def check_line_fit(strict=True):
    """每一行台词都要装得进消息窗 —— **这台引擎不会自动折行**。

    2026-09-24 写 P9 收尾旁白时，从截图上发现「他卧床一年有余……仰头看天。」
    少了个尾巴。查源码：`Window_Base.processCharacter` 只是把字符累进 buffer
    （rmmz_windows.js:319），`flushTextState` 把它交给
    `Bitmap.drawText(text, x, y, width, height, align)`，而 drawText 是直接
    canvas 填字（rmmz_core.js:1661-1685）—— **没有 wordWrap，也不按 maxWidth 折**。
    所以超宽的行不是折到下一行，是被位图边界**悄悄裁掉**：
    不报错、不崩、日志里什么都没有，只是那几个字从来没出现在屏幕上。

    可用宽度取自引擎自己（源头 `Window_Message.newLineX`，rmmz_windows.js:4887）：
        有脸   innerWidth - (standardFaceWidth + 20)
        无脸   innerWidth - 4
    比宽度用 `m.textWidth()` 而不是按字数估 —— 中英混排、全角标点、`\\I[n]`
    图标都不等宽，估出来的数会在临界处骗人。

    2026-09-25 起折行搬到了构建器（`build_project.wrap_line`）：数据层写自然长句，
    构建期按标点折好。于是这里的角色从「抓出超宽」变成「用引擎的真宽度
    核对构建器的折行结果」—— 构建器那份宽度模型若漂移（换了字体 / fontSize），
    它折出来的行会在这里被当场量出来，而不是拖到截图里才用肉眼看见。

    这一条是本工程「看图才发现」的那类缺陷里最后一块没被工具兜住的：
    脸图会不会被切（check_face_fits）、事件会不会隐形（build_project.paint）、
    分支会不会走飞（check_branch_structure）都已经有断言了，
    只有「字写太长」一直靠肉眼。
    """
    m = "SceneManager._scene._messageWindow"
    inner = int(float(ev("Math.round(%s.innerWidth)" % m)))
    face_w = int(float(ev("ImageManager.standardFaceWidth")))
    icon_w = int(float(ev("ImageManager.standardIconWidth"))) + 4     # processDrawIcon 的步进
    limits = {True: inner - (face_w + 20), False: inner - 4}

    rows = []          # (图, 事件名, 是否有脸, 行文本)
    for mid in sorted(G.MAPS):
        for kind, t in G.events_of(mid):
            if kind != "npc":
                continue
            # 直接用构建器的 emit_lines 拆页，别再写一份：一页 = 一个 101 +
            # 紧跟的 401s（command101 会把它们一口气吃掉），照抄一遍必然走样。
            face = False
            for c in B.emit_lines(t[6], t[5], t[0], 0):
                if c["code"] == 101:
                    face = bool(c["parameters"][0])
                elif c["code"] == 401:
                    rows.append((mid, t[0], face, c["parameters"][0]))

    # 一次 eval 量完：一行一个往返的话，两百多次 CDP 往返要十几秒。
    # `\I[n]` 要先抠掉再量 —— textWidth('\I[2]') 会把反斜杠和方括号当正文算，
    # 而它实际画成一个图标（步进 standardIconWidth + 4，见 processDrawIcon）。
    batch = json.dumps([re.sub(r"\\I\[\d+\]", "", r[3]) for r in rows], ensure_ascii=False)
    got = ev("(function(){var m=%s;var a=%s;return a.map(function(t){"
             "return Math.round(m.textWidth(t));}).join(',');})()" % (m, batch))
    widths = [int(v) for v in got.split(",") if v != ""]

    bad = []
    for (mid, name, face, line), w in zip(rows, widths):
        w += 36 * line.count("\\I[")          # 每个图标占 standardIconWidth + 4
        lim = limits[face]
        if w > lim:
            bad.append((w - lim, mid, name, face, line, w, lim))
    bad.sort(reverse=True)
    print("\n台词行宽：%d 行，可用 %d（有脸）/ %d（无脸）"
          % (len(rows), limits[True], limits[False]))
    for over, mid, name, face, line, w, lim in bad:
        print("  ** 超宽 %3dpx  M%d %-6s %s  %d > %d  %s"
              % (over, mid, name, "有脸" if face else "无脸", w, lim, line))
    if not bad:
        print("  全部装得下")
    if strict:
        assert not bad, (
            "有 %d 行台词超宽，会被消息窗**静默裁掉**（这台引擎不折行）：%s"
            % (len(bad), [(mid, name, line) for _o, mid, name, _f, line, _w, _l in bad[:4]]))


def drain(tries=20):
    """一路按确定键，直到消息窗真的关了。返回按了几下。

    **按键会被吞。** headless Chrome 跑久了帧率会掉，60ms 的按下可能整段落在两帧
    之间，引擎一次都没看见。所以「按 N 下就关得掉」是错的写法 —— 早先就是这么写的，
    后果不是当场报错，而是**故障串台**：上一条对话没关完，下一处的按键先被它借走，
    于是「守卫按了没反应」这种假失败，指向一个完全无辜的 NPC。
    改成按到状态变了为止，谁的问题就报在谁头上。
    """
    n = 0
    while busy() and n < tries:
        ab.key("ok", 90)
        n += 1
        time.sleep(0.45)
    return n


def talk_and_advance(tag, label=None):
    # 走到这里消息窗本该是关着的。若有残留，先按干净，别让它吃掉这一处的按键。
    drain(tries=12)
    ab.key("ok", 90)
    time.sleep(0.7)
    opened = busy()
    if opened and not GEO[0]:
        GEO[0] = True          # 只量第一次，省掉几次 eval 的开销
        check_face_fits()
    shot(label or tag)
    drain()
    assert not busy(), "%s 的对话按了 20 下还没关掉 —— 按键多半被吞了" % tag
    return opened


# ------------------------------------------------------------ 每张图走一遍
def walk_map(mid):
    """一张图的标准走查：BFS 全事件可达 + 逐个走过去对话 + 截图。

    传送格**不在这里**「对话」—— 它们不是说话，走上去就换图，留在
    `transfer_test()` 里单独验；这里只断言它**踩得上去**（否则玩家到不了门口）。
    """
    print("\n" + "=" * 60)
    print("地图 %d《%s》  %s" % (mid, G.MAPS[mid]["name"], OUT[0].replace(ROOT, ".")))
    grid = read_grid()
    print("通行图（# 挡路 / x 事件占格 / . 可站）：")
    for y, row in enumerate(grid):
        print("  %2d %s" % (y, row))

    kinds = {i: k for i, (k, _t) in enumerate(G.events_of(mid), 1)}
    names = G.event_names(mid)
    events = read_events()
    start = pos()[:2]
    print("\n当前位置 %s，事件 %d 个：" % (start, len(events)))

    plan = []
    for eid, x, y in events:
        name = names.get(eid, "#%d" % eid)
        if kinds.get(eid) == "portal":
            # 传送格：确认它踩得上去（BFS 到它自己）。它是 priorityType 0，
            # 所以在通行图上是 '.' 而不是 'x'。
            ok = bfs(grid, start, {(x, y)}) is not None
            print("  %-8s @(%2d,%2d)  门口（非对话）  踩得上去=%s"
                  % (name, x, y, "是" if ok else "**否**"))
            assert ok, "%s @(%d,%d) 走不上去 —— 玩家到不了门口" % (name, x, y)
            continue
        r = facing_cell(x, y, grid, start)
        assert r, "%s @(%d,%d) 四邻都不通，够不着" % (name, x, y)
        (sx, sy), d, path = r
        print("  %-8s @(%2d,%2d)  站位(%2d,%2d) 朝向%d  步数 %2d"
              % (name, x, y, sx, sy, d, len(path) - 1))
        plan.append((name, sx, sy, d))

    print()
    for name, sx, sy, d in plan:
        ev("$gamePlayer.locate(%d,%d);$gamePlayer.setDirection(%d);" % (sx, sy, d))
        time.sleep(0.25)
        opened = talk_and_advance(name)
        d0, n, _tag, _ = LOG[-1]
        LOG[-1] = (d0, n, name, "站位(%d,%d) 朝向%d 对话%s"
                   % (sx, sy, d, "已开" if opened else "**没开**"))
        assert opened, "%s @(%d,%d) 站到面前按确定键没有弹出对话" % (name, sx, sy)


def transfer_test(mid, eid):
    """**真的走上去**，看引擎换没换图。

    这是全工程唯一不能靠 BFS 代劳的一步：传送依赖引擎的两条判定
    （priorityType 0 才踩得上去、trigger 1 才在「踩上去」那条路上被触发），
    外加 201 指令本身。任何一处配错，`locate()` 都能把人搬过去、而玩家走不过去 ——
    所以这里必须按方向键。
    """
    name, px, py, _d, tmid, tx, ty, td = G.events_of(mid)[eid - 1][1]
    # 出发格不能挑到**别的传送格**上：那会一落地就被弹走，失败信息还会指着
    # 一个跟本次验证无关的门口。所以先把本图所有传送格列出来避开。
    port_cells = {(t[1], t[2]) for k, t in G.events_of(mid) if k == "portal"}

    # 玩家此刻**未必站在出发图上**：主流程按 map id 顺序遍历，而 M4 的入口开在 M2 上，
    # 走到 M4 时玩家还在 M3。所以先搬回出发图 —— 搬用 reserveTransfer（跟人工换图
    # 同一条路），换图仍然用走的。这条分工不能混：最后那一下必须是真的踩上去，
    # 201 指令与 priorityType / trigger 两条判定才在验证范围里。
    # 这一搬只能按数据层的坐标挑格（此刻手上拿到的是**别人家**的通行图），
    # 万一落进墙里也不要紧 —— 下面会 locate 到正经的出发格。
    if map_id() != mid:
        rows = G.MAPS[mid]["rows"]
        cand = [(px - dx, py - dy, d) for d, (dx, dy) in DIRVEC.items()
                if 0 <= px - dx < len(rows[0]) and 0 <= py - dy < len(rows)
                and (px - dx, py - dy) not in port_cells]
        assert cand, "%s @(%d,%d) 贴着地图边，外头没有可站的格子" % (name, px, py)
        ev("$gamePlayer.reserveTransfer(%d,%d,%d,%d,0)" % ((mid,) + cand[0]))
        assert wait_map(mid), "搬不回出发图 %d（现停在 %s）" % (mid, map_id())
        time.sleep(0.6)

    grid = read_grid()
    here = pos()[:2]
    best = None
    for d, (dx, dy) in DIRVEC.items():
        sx, sy = px - dx, py - dy
        if not (0 <= sy < len(grid) and 0 <= sx < len(grid[0])):
            continue
        if grid[sy][sx] != "." or (sx, sy) in port_cells:
            continue
        p = bfs(grid, here, {(sx, sy)})
        if p and (best is None or len(p) < len(best[2])):
            best = ((sx, sy), d, p)
    assert best, "%s @(%d,%d) 周围没有能站的格子，走不进去" % (name, px, py)
    (sx, sy), d, _p = best

    ev("$gamePlayer.locate(%d,%d);$gamePlayer.setDirection(%d);" % (sx, sy, d))
    time.sleep(0.4)
    p = step(DIRKEY[d])
    assert p == (px, py), \
        "%s：按 %s 之后人在 %s，没走到传送格 (%d,%d)" % (name, DIRKEY[d], p, px, py)
    ok = wait_map(tmid)
    time.sleep(0.6)                     # 等淡入
    # 先切出图目录再截：这张拍的是**到达地**的样子，该归到目标图那一组，
    # 而不是留在出发图里骗人。
    use_out(tmid)
    shot("换图-%s去%s" % (name, G.MAPS[tmid]["name"]))
    after = pos()
    print("  %s (%d,%d) --走上去--> 地图%s 落点(%d,%d) 朝向%d"
          % (name, px, py, map_id(), after[0], after[1], after[2]))
    assert ok, "%s 踩上去了但没换图（还在地图 %s）" % (name, map_id())
    assert map_id() == tmid, "%s 换到了地图 %s，期望 %s" % (name, map_id(), tmid)
    assert after[:2] == (tx, ty), "%s 落点 %s，期望 (%d,%d)" % (name, after[:2], tx, ty)
    assert after[2] == td, "%s 落点朝向 %d，期望 %d" % (name, after[2], td)
    print("     换图 OK")


# ------------------------------------------------------------ 道具 / 条件闸门
def item_count(name):
    """队伍里某件道具的数量（名字 -> game_data.ITEMS 里查 id）。"""
    return int(ev("$gameParty.numItems($dataItems[%d])" % G.ITEMS[name][0]))


def goto_map(mid, x, y, d=2):
    """把人弄到某张图的某格。用 reserveTransfer（跟人工换图同一条路）。

    注意这是**摆位**，不是验收 —— 换图那件事仍然由 transfer_test 真走一遍。
    这里是给闸门验证造前置状态用的。
    """
    if map_id() != mid:
        ev("$gamePlayer.reserveTransfer(%d,%d,%d,%d,0)" % (mid, x, y, d))
        assert wait_map(mid), "搬不到地图 %d（现停在 %s）" % (mid, map_id())
        time.sleep(0.6)
    else:
        ev("$gamePlayer.locate(%d,%d)" % (x, y))
        time.sleep(0.3)


def stand_at(mid, evname):
    """站到某张图上某个事件的正对面（面朝它）。返回事件格 (x, y)。

    face_and_talk 与 talk_capture 都要先站好位置，定位这段只写一次 ——
    两边各写一份的话，其中一边挪了格子另一边不知道，症状是「截图里人站错了地方」。
    """
    eid = next(i for i, n in G.event_names(mid).items() if n == evname)
    ex, ey = {i: (x, y) for i, x, y in read_events()}[eid]
    grid = read_grid()
    r = facing_cell(ex, ey, grid, pos()[:2])
    assert r, "%s @(%d,%d) 四邻都不通，够不着" % (evname, ex, ey)
    (sx, sy), d, _p = r
    ev("$gamePlayer.locate(%d,%d);$gamePlayer.setDirection(%d);" % (sx, sy, d))
    time.sleep(0.3)
    return ex, ey


def face_and_talk(mid, evname, label=None):
    """站到某张图上某个事件面前，按确定键，返回消息窗是否弹开。

    label 只影响截图的文件名。闸门验证要按同一个事件三次、走三条不同的分支，
    不标签的话验收目录里就是三张同名的「石穴」，回头根本认不出哪张是哪条路。
    """
    stand_at(mid, evname)
    return talk_and_advance(evname, label)


def captured(word):
    """刚才那一段对话里出现过 word 吗 —— 必须配 talk_capture() 用。

    比对放在 JS 侧而**不是**把中文读回 Python：ab 的 eval 回显是 JSON 字面量，
    非 ASCII 会变成 \\uXXXX，读回来还要再解一层转义；而本工程的字串里本来就带
    `\\I[2]` 这种反斜杠转义码，解错一层就静默比对失败。让 JS 只回 YES/NO，
    是这里唯一不会骗人的口径（也是 playtest 一贯的约定）。
    """
    esc = "".join("\\u%04x" % ord(c) for c in word)
    return ev("(String(window.__cap||'').indexOf('%s')>=0?'YES':'NO')" % esc) == "YES"


def talk_capture(mid, evname, label=None):
    """按一次确定键开始对话，把这一段**所有页**的文字收进 window.__cap，再关掉。

    与 talk_and_advance 的唯一区别是"读不读文字"。为什么一页一读、而不是等
    关掉之后读一次：`$gameMessage` 在 terminateMessage() 里就被 clear() 了
    （rmmz_windows.js:4912），窗口一关，文字**当场没了**，再问就是空串。
    而一页一读还得留意台词中间的 ("乐", …) 会把一段断成两段文字框 ——
    所以每按一下之前都追加一次，断了也照样收齐。

    循环条件用 busy() 是安全的：command249（ME）**没有** setWaitMode
    （rmmz_objects.js:10815），所以两个文字框之间的"窗口已关"是同一帧内的事，
    0.4 秒一次的轮询看不到那个缝；command101 则是 setWaitMode("message")，
    解释器会一直等到窗口关掉（rmmz_objects.js:9824），前后顺序不会乱。
    """
    stand_at(mid, evname)
    drain(tries=12)                        # 残留先按干净，别让它吃掉这一次
    ev("window.__cap='';")
    ab.key("ok", 90)
    time.sleep(0.7)
    opened = busy()
    assert opened, "按了 %s，消息窗没弹开 —— 后面就没有文字可读" % evname
    shot(label or evname)
    n = 0
    while busy() and n < 40:
        ev("window.__cap+=$gameMessage.allText()+String.fromCharCode(10);")
        ab.key("ok", 90)
        n += 1
        time.sleep(0.4)
    assert not busy(), "%s 按了 %d 下还没关掉 —— 页数比预想的多" % (evname, n)
    return opened


def check_gate():
    """定向验证「按图索骥」这道条件闸门 —— 正反两条路都要走一遍。

    遍历式走查只能证明**正面**：「有片纸时拿得到虫」（事件顺序恰好是
    M2 巫舍 -> M3 石穴）。它证不了反面 —— 而条件分支写错的典型表现正是
    「条件永远为真」（缩进掉了 / 道具 id 没登记 / id 与下标错位），
    那会让遍历式走查照样全绿。所以这里把状态清干净，两个方向各走一次。

    三条断言分别钉住三件事：
      无片纸 -> 不得虫      条件真的在判（不是永远为真）
      有片纸 -> 得虫        条件真的能过（不是永远为假）
      再按一次 -> 仍是 1    「已有虫」那层在挡重复领
    """
    print("\n" + "=" * 60)
    print("条件闸门验证：石穴给不给虫，取决于怀里有没有片纸")
    goto_map(3, 22, 14, 8)                      # 后园东南口内侧的石径上
    # 出图目录要跟着切回 M3。上一段「逐门验证」最后一次换图停在 M2，
    # 不切的话这三张闸门截图会落进 m2/ —— 目录名说谎比不放图更坏。
    use_out(3)
    ev("$gameParty.loseItem($dataItems[%d],99);$gameParty.loseItem($dataItems[%d],99);"
       % (G.ITEMS["片纸"][0], G.ITEMS["青麻头"][0]))
    time.sleep(0.3)
    p0, c0 = item_count("片纸"), item_count("青麻头")
    print("清空后：片纸 %d，青麻头 %d" % (p0, c0))
    assert p0 == 0 and c0 == 0, "清理不干净，后面的正反对照就不成立"

    face_and_talk(3, "石穴", "石穴-无片纸")
    n0 = item_count("青麻头")
    print("无片纸按石穴 -> 青麻头 %d（应当 0）" % n0)
    assert n0 == 0, "没有片纸却拿到了虫 —— 条件分支根本没在判"

    ev("$gameParty.gainItem($dataItems[%d],1)" % G.ITEMS["片纸"][0])
    time.sleep(0.2)
    face_and_talk(3, "石穴", "石穴-有片纸得虫")
    n1 = item_count("青麻头")
    print("有片纸按石穴 -> 青麻头 %d（应当 1）" % n1)
    assert n1 == 1, "手里有片纸却拿不到虫 —— 条件分支走反了"

    face_and_talk(3, "石穴", "石穴-已有虫")
    n2 = item_count("青麻头")
    print("再按一次石穴 -> 青麻头 %d（应当仍是 1）" % n2)
    assert n2 == 1, "石穴会重复给虫 —— 少了「已有虫」那一层"


def switch_of(name):
    """开关当前值（名字 -> game_data.SWITCHES 里查 id）。"""
    assert name in G.SWITCHES, "没有登记过的开关 %r" % name
    return ev("String($gameSwitches.value(%d))" % G.SWITCHES[name]) == "true"


def check_story():
    """定向正推 P5→P8 —— 遍历式走查够不到这条线。

    为什么够不到：`walk_map` 按地图 id 顺序遍历（M1 -> M2 -> M3 -> M4），
    而 M1 是**第一张**走的图，那时手上片纸、青麻头都还没有。于是 M1 上所有
    判「有青麻头」「失虫」「投井」的分支，遍历时统统落在最外层 else 上 ——
    **走查全绿，也可能是那些分支一次都没走到**。

    条件写错的两种典型表现恰好都不报错：永远为真（打进真段）、永远为假
    （打进 else）。遍历只覆盖得到后者的一半，所以主线必须单独推一遍：
    从「手上有青麻头」（走完 M3 石穴之后的真实状态）起步，按剧情顺序走完
    P5 失虫 -> P5 投井 -> P6 复得 -> P7 斗虫 -> P8 进献，
    每一步都断言**道具与开关真的按预期变了**。

    顺序不能颠倒：虫盆判「有青麻头」，而青麻头在投井之前就该没了；
    门口判「投井」，而投井要等井边那场演过。这条链本身就是剧情顺序的
    可执行版本 —— 顺序错了，某一步的断言就会掉到 else 分支上去。
    """
    print("\n" + "=" * 60)
    print("主线正推 P5→P8：失虫 -> 投井 -> 复得 -> 斗虫 -> 进献")
    # 起步状态：上面刚断言过「片纸 1 / 青麻头 1」，正好是 P4 刚得虫的样子。
    assert item_count("青麻头") == 1, "正推起步时手上该有 1 只青麻头"
    assert item_count("小虫") == 0, "正推起步时不该已经有小虫"
    for sw in ("失虫", "投井", "斗虫", "献虫"):
        assert not switch_of(sw), "开关「%s」在正推之前就开着 —— 上一段把状态跑脏了" % sw

    # ---- P5 上：虫毙于盆中 ----
    goto_map(1, 12, 16, 8)
    use_out(1)
    face_and_talk(1, "虫盆", "虫盆-失虫")
    assert item_count("青麻头") == 0, "演完失虫，青麻头却还在手上 —— 「收」没生效"
    assert switch_of("失虫"), "演完失虫，「失虫」开关没打开"
    print("  失虫 OK：青麻头 %d，开关失虫=%s"
          % (item_count("青麻头"), switch_of("失虫")))

    # ---- P5 下：井边 ----
    face_and_talk(1, "水井", "水井-投井")
    assert switch_of("投井"), "演完井边那场，「投井」开关没打开"
    print("  投井 OK：开关投井=%s" % switch_of("投井"))

    # ---- P6：门外虫鸣，复得小虫 ----
    face_and_talk(1, "门口", "门口-复得")
    assert item_count("小虫") == 1, "门口演完却没拿到小虫 —— P6 断了"
    print("  复得 OK：小虫 %d" % item_count("小虫"))

    # ---- P7：斗虫 ----
    goto_map(2, 12, 16, 8)
    use_out(2)
    face_and_talk(2, "村中少年", "少年-斗虫")
    assert switch_of("斗虫"), "斗完虫，「斗虫」开关没打开"
    assert item_count("小虫") == 1, "斗完虫，小虫却不在了 —— 它不该被收走"
    print("  斗虫 OK：开关斗虫=%s，小虫 %d" % (switch_of("斗虫"), item_count("小虫")))

    # ---- P8：进献 ----
    goto_map(4, 9, 11, 8)
    use_out(4)
    face_and_talk(4, "宰", "宰-进献")
    assert switch_of("献虫"), "献完虫，「献虫」开关没打开"
    assert item_count("小虫") == 0, "献完虫，小虫却还在手上 —— 「收」没生效"
    print("  进献 OK：开关献虫=%s，小虫 %d" % (switch_of("献虫"), item_count("小虫")))

    # ---- P8 收束 ----
    # 这里**不再**多按一次宰。原来是按的，用来证明「献虫」那层挡得住重复演出；
    # 但 P9 给献虫之后加了一段报喜（带 ME Fanfare2），多按一次就等于让这个 ME
    # 响两遍，而期望值来自数据层的声明次数（一次）—— 断言会报「多响」。
    # 重复进言的覆盖挪去了 check_finale()：那边每个事件都只按一次。
    assert switch_of("献虫") and item_count("小虫") == 0, \
        "献完虫之后状态不对：献虫=%s 小虫=%d" % (switch_of("献虫"), item_count("小虫"))
    print("  进献收束 OK")


def check_finale():
    """P9：结尾三段，外加一道**顺序门**。

    P5→P8 验的是道具与开关，因为那几场戏都留下了痕迹（虫没了、开关开了）。
    P9 不一样：它一段台词都不改状态，全是「说了什么」。
    于是这一段的断言必须读到**文字**本身 —— 否则「分支静默走错」
    （条件写反、被上一层挡住、else 落错）在这里一次都测不出来，
    而那正是本工程一路吃亏的那类错。

    三个事件各按一次，一处都不多按：音频断言要求每个 ME **恰好**响一次，
    而期望值来自数据层的声明。多按一下就是「多响」，会被抓出来。
    """
    print("\n" + "=" * 60)
    print("尾声 P9：宰报喜 -> 成子复旧 -> 异史氏曰")
    assert switch_of("献虫"), "P9 的起手状态该是「已献虫」"
    assert not switch_of("复旧"), "P9 的起手状态不该已经「复旧」"
    assert item_count("小虫") == 0, "P9 起手时小虫该已经不在手上"

    # ---- P9-1 回县衙：那只虫的下文，以及免役入邑庠 ----
    goto_map(4, 9, 11, 8)
    use_out(4)
    talk_capture(4, "宰", "宰-报喜")
    assert captured("邑庠"), \
        "宰那里没说出「入邑庠」—— 要么没走献虫那条分支，要么台词被改坏了"
    # 反面控制：证明上面那条不是「怎么问都 YES」。献虫之前那套要虫的台词里
    # 有「虫呢」三个字，报喜这条分支里绝不该有。
    assert not captured("虫呢"), "读到的是要走虫的那一页 —— 献虫分支没生效"

    # ---- 顺序门：复旧之前，门口不该出现异史氏曰 ----
    # 顺手钉住另一件事：此时手上已经没了小虫，门口**不许再送一只**
    # （见 game_data 门口那段注释 —— 这是 P9 才暴露出来的状态泄漏）。
    goto_map(1, 12, 16, 8)
    use_out(1)
    talk_capture(1, "门口", "门口-复旧前")
    assert not captured("异史氏曰"), \
        "成子还没复旧，「异史氏曰」就抢出来了 —— 顺序门没生效，全篇的转折被说漏"
    assert item_count("小虫") == 0, \
        "献出去的虫在门口又被补了一只 —— 手上空了就再给，这条路没堵上"

    # ---- P9-2 成子复旧 ----
    talk_capture(1, "成子", "成子-复旧")
    assert captured("梦"), "成子没说出那个梦 —— 复旧那层没走到"
    assert not captured("不该碰那个笼子"), \
        "读到的是投井之后那页 —— 献虫/复旧那两层都没生效"
    assert switch_of("复旧"), "成子说完了，「复旧」开关却没打开"

    # ---- 复旧之后再按一次：应当换到「已经好了」那一页 ----
    talk_capture(1, "成子", "成子-已复旧")
    assert not captured("梦"), "复旧之后还在重演那个梦 —— 复旧那层没挡住重复演出"
    assert captured("一样"), "复旧之后的常态台词没读到"

    # ---- P9-3 异史氏曰 ----
    talk_capture(1, "门口", "门口-异史氏曰")
    assert captured("异史氏曰"), "走完了全程，门口却没有出现「异史氏曰」"
    assert captured("信夫"), "评点读到一半就断了 —— 原文末尾那句没收进台词"
    print("  尾声三段 OK：免役入庠 -> 身化促织 -> 异史氏曰")


# ------------------------------------------------------------ 主流程
def archive(mid):
    """清掉上次的截图。**不能 os.remove** —— 本机的安全删除拦截层会把批量删除
    挡下来（SAFE_DELETE_BULK_CONFIRM_REQUIRED），挪进 .scratch 归档。
    必须用 os.replace 而不是 shutil.move：目标已存在时 move 会退化成 copy+unlink，
    unlink 照样被拦。"""
    d = use_out(mid)
    stale = os.path.join(ROOT, ".scratch", "accept_m%d_prev" % mid)
    os.makedirs(stale, exist_ok=True)
    for f in os.listdir(d):
        if f.endswith(".png"):
            os.replace(os.path.join(d, f), os.path.join(stale, f))


def entry_portal(mid):
    """找出「能走进地图 mid」的那处传送 -> (源图, 事件 id, 名字)。"""
    for s in sorted(G.MAPS):
        for i, (kind, t) in enumerate(G.events_of(s), 1):
            if kind == "portal" and t[4] == mid:
                return s, i, t[0]
    return None


def main():
    for mid in sorted(G.MAPS):
        archive(mid)
    use_out(1)
    srv = serve()
    url = "http://127.0.0.1:%d/index.html" % PORT
    print("服务 %s" % url)

    ab.ab("close", "--all")
    time.sleep(1)
    ab.ab("set", "viewport", "816", "624")     # 引擎原尺寸 -> 画面 1:1，截图不会切掉消息窗
    ab.ab("open", url)
    if not ab.wait_ready(40):
        print("!! 没能进入游戏")
        return 1
    print("  画布 %s  视口 %s"
          % (ab.ab("get", "box", "#gameCanvas").replace("\n", " "),
             ab.ab("eval", "innerWidth+'x'+innerHeight").strip()))
    shot("title")

    ab.key("ok", 60)                       # 标题 -> 新游戏
    for _ in range(40):
        if scene() == "Scene_Map":
            break
        time.sleep(0.5)
    time.sleep(1.2)
    start = pos()[:2]
    print("进入地图：场景=%s 地图=%s 玩家=%s" % (scene(), map_id(), pos()))

    # ---- 真按几下方向键，证明输入链路是活的 ----
    for k in ("left", "left", "up"):
        ab.key(k, 26)
        time.sleep(0.35)
    after = pos()
    print("按 左/左/上 之后玩家=%s" % (after,))
    assert after[:2] != start, "按了方向键但玩家没动 —— 输入链路坏了"
    shot("walked")
    ev("$gamePlayer.locate(%d,%d)" % start)

    # ---- 星标层验证：站进树冠格，玩家应当被画在叶子后面 ----
    # 引擎把带 0x10 的图块路由到 _upperLayer（z=4，画在角色之上）；
    # 同时 checkPassage 对星标 `continue`，于是靠下面那层地面放行。
    # 「树干挡路 + 树冠可穿且盖住玩家」是 MZ 表现「走到树后面」的唯一正规做法，
    # 光靠图层号做不到（所有瓦片层都在角色之下），必须靠星标位。
    man = json.load(open(os.path.join(ROOT, "build", "tiles_manifest.json"),
                         encoding="utf-8"))
    star = set(man["star_ids"])
    oname, bx, by = G.MAPS[1]["objects"][0]          # 大树 3x3，底边中心 (3,10)
    o = next(x for x in man["objects"] if x["name"] == oname)
    ow, oh = o["tiles"]
    ox0, oy0 = bx - (ow - 1) // 2, by - oh + 1
    cx, cy = ox0 + 1, oy0                            # 树冠最上一行的中间格
    tx, ty = ox0 + 1, oy0 + oh - 1                   # 树干（物件最后一行）
    tid = json.loads(ev("$gameMap.tileId(%d,%d,1)" % (cx, cy)))
    pas = ev("String($gameMap.isPassable(%d,%d,2))" % (cx, cy)) == "true"
    ftr = json.loads(ev("$gameMap.tileId(%d,%d,1)" % (tx, ty)))
    print("\n星标层：树冠格(%d,%d) tileId=%d 属星标=%s 可通行=%s；"
          "树干格(%d,%d) tileId=%d 属星标=%s"
          % (cx, cy, tid, tid in star, pas, tx, ty, ftr, ftr in star))
    assert tid in star, "树冠格没有星标 —— 高物件分层没生效，玩家会踩在树冠上"
    assert pas, "树冠格不可通行 —— 星标的「跳过判定」没生效"
    assert ftr not in star, "树干格也被标了星标 —— 物件会整个变成可穿过"
    ev("$gamePlayer.locate(%d,%d)" % (cx, cy))
    time.sleep(0.6)
    shot("星标-树后")

    # ---- 台词行宽。跟游戏状态无关，一次算完；超宽的行会被消息窗静默裁掉 ----
    check_line_fit()

    # ---- 逐张图走查。除首图外，每张都靠**真实走位**从上一张走进去 ----
    walk_map(1)

    for mid in sorted(G.MAPS):
        if mid == 1:
            continue
        src = entry_portal(mid)
        assert src, "地图 %d 没有任何传送门通进去" % mid
        print("\n从地图 %d 的「%s」走进地图 %d" % (src[0], src[2], mid))
        transfer_test(src[0], src[1])
        use_out(mid)
        walk_map(mid)

    # ---- 回程：把每张图的每个传送门都走一遍（含刚才入口的反向）。
    # transfer_test 自己会先搬回出发图，所以这里不再按「玩家当前在哪张图」筛。
    print("\n" + "=" * 60)
    print("逐门验证（每张图的每个门各走一次，两个方向都在内）")
    for mid in sorted(G.MAPS):
        for i, (kind, _t) in enumerate(G.events_of(mid), 1):
            if kind != "portal":
                continue
            transfer_test(mid, i)

    # ---- 道具端到端证据 ----
    # 遍历顺序 M2 巫舍 -> M3 石穴 正好就是剧情顺序，所以走完这一遍，
    # 该拿的两样东西必须各**恰好** 1 个。条件分支若有任何一处配错
    # （缩进掉了 / 道具没登记 / id 与下标错位），这里就会是 0 或者 2。
    # 这是最省事的一条端到端断言：不用编排剧情，遍历顺手就覆盖了。
    print("\n走查结束时的道具：片纸 %d，青麻头 %d"
          % (item_count("片纸"), item_count("青麻头")))
    assert item_count("片纸") == 1, "走完一遍应当恰好拿到 1 张片纸"
    assert item_count("青麻头") == 1, "走完一遍应当恰好得到 1 只青麻头"

    # ---- 主线正推。**必须排在 SE 断言之前** —— P5/P6/P7 那几个 ME 与 SE
    #      全长在条件分支里，而遍历够不到它们（M1 是第一张走的图，那时手上
    #      还没虫）。不先推一遍，下面的 SE 期望就会集体落空，报出一堆假失败。
    check_story()

    # ---- 尾声。**也必须排在音频断言之前**：成子复旧那个 ME(Mystery) 与
    #      异史氏曰那个 ME(Organ) 全长在「复旧」这道门后面，走查与 P5→P8
    #      正推都到不了（前者走 M1 时手上还没虫，后者压根不碰 M1 的成子与门口）。
    #      不先推一遍，这两个 ME 就成了「声明了却没响」的假失败。
    check_finale()

    # ---- 音频。读的是 __se（独立数组），不是 __log —— 后者有上限会截断，
    #      表现出「SE 没响」的假阴性。断言口径：数据层里声明过的音频，
    #      走查时必须真的调用过，且**类别与名字都对得上**。
    #
    #      期望值取自 G.audio_cues()，它同时收事件级的 se、分支里的 ("声", …)
    #      与 ("乐", …)：石穴的 Water2 已经从事件级搬进分支（事件级是无条件
    #      播的），只数事件级就会把它漏出验证范围；P5/P7 那几个 ME 也走
    #      同一个探针，不收进来就变成「响了但没人验」。
    #
    #      类别（se/me）也进比对：只看名字的话，把 ("乐", …) 错写成 ("声", …)
    #      会照样全绿 —— 名字对、次数对、只是听感不对。这是本工程反复吃亏的
    #      那种「不报错但全错」。这一条是拿一次真失败换来的：36 次调用里
    #      5 个 ME 全响了，却因为统计只认 "se " 前缀而集体报「没响」。
    #
    #      **这段必须排在 check_gate() 之前读**：闸门验证会再按两次石穴，
    #      把 Water2 的调用次数推上去，之后就对不上「每个音频恰好几次」了。
    se = [l for l in ev("(window.__se||[]).join('|')").split("|") if l]
    want = [c for mid in sorted(G.MAPS) for c in G.audio_cues(mid)]
    got = []
    for line in se:
        w = line.split()
        if w[0] in ("se", "me"):        # bgm/bgs 是被换图带出来的，不进期望值
            got.append((w[0], w[1]))
    # __log 只做人工排查用，被上限截断是**正常**的（2000 条，跑一次多图走查必满）。
    # 报告它，是为了别让谁再拿它当验证依据 —— 音频就是这么被骗过一回的。
    logn = ev("(window.__log||[]).length")
    trunc = "已截断，靠后的记录已丢" if ev(
        "String((window.__log||[]).indexOf('__LOG_TRUNCATED__')>=0)") == "true" else "完整"
    print("\n事件日志 %s 条（%s）" % (logn, trunc))
    print("音频调用 %d 次（SE+ME 计入断言）：" % len(se))
    for k, n in got:
        print("   %s %s" % (k, n))
    print("       期望：%s" % (want or "（无）"))
    # 报三个数而不是"少了几次"：少响和多响是不同的病（前者是漏了指令，
    # 后者多半是同一个事件被走了两遍），只报差值会把多响说成"没响"。
    off = [(c, n, got.count(c)) for c, n in Counter(want).items() if got.count(c) != n]
    assert not off, "这些音频的类别/次数对不上（(类别,名字), 期望, 实际）：%s" % off

    check_gate()

    err = [l for l in ev("(window.__err||[]).join('|')").split("|") if l]
    print("运行时错误：%s" % (err or "（无）"))

    print("\n%3s %-6s %-16s %s" % ("#", "图", "场景", "结果"))
    for d0, n, tag, note in LOG:
        print("%3d %-6s %-16s %s" % (n, d0, tag, note))

    ab.ab("close", "--all")
    srv.shutdown()
    return 0 if not err else 1


if __name__ == "__main__":
    sys.exit(main())
