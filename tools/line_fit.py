# -*- coding: utf-8 -*-
"""用**引擎的真宽度**复量构建器折出来的每一行 —— 核对折行模型有没有漂移。

**为什么需要它**：这台引擎不折行（`flushTextState` 拿 `textWidth(text)` 当宽度
`drawText` 一次画完，`rmmz_windows.js:266`；唯一的换行来源是控制字符 `\\n`），
超出消息窗右缘的部分被位图边界**静默裁掉** —— 不报错、不崩、日志空白，
只是那几个字从来没出现在屏幕上。

折行本身现在由构建器做（`build_project.wrap_line`，见那里的注释），
所以本工具不再是「手工拆行的辅助」，而是**独立核对者**：构建器用一套宽度模型
折行，这里请引擎自己量一遍折出来的结果。两者不一致 = 模型漂移（换字体、改
fontSize 后最可能发生），超宽的行会打出来并退出码 1。

**为什么不在这里再算一遍切点**：构建器的规则（两行取长边最短）与引擎的贪心
逐行填充并不是同一套，在这里另写一份「建议切法」只会给出与构建器不同的答案，
真出问题时反而误导。核对就是核对，只报「哪一行多宽、超了多少」。

分工：
    构建器 `build_project.wrap_line()` —— 构建期折行，保证绝不产出超宽行；
    `playtest.check_line_fit()` —— **验收**（超宽即退出码非零，挂在主流程里）；
    本工具 —— **快筛**（58 秒 vs 六分钟），把超宽行和超出量一次列清。

    python tools/line_fit.py            量一遍，超宽则退出码 1
    python tools/line_fit.py --quiet    只打结论
"""
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_project as B  # noqa: E402
import game_data as G  # noqa: E402
import playtest as P  # noqa: E402


def collect():
    """走构建器同一条路收集 401 行：一页 = 一个 101 + 紧跟的 401s。

    别自己另写一份拆页逻辑 —— 构建器怎么拆，这里就得怎么量。
    """
    rows = []
    for mid in sorted(G.MAPS):
        for kind, t in G.events_of(mid):
            if kind != "npc":
                continue
            face = False
            for c in B.emit_lines(t[6], t[5], t[0], 0):
                if c["code"] == 101:
                    face = bool(c["parameters"][0])
                elif c["code"] == 401:
                    txt = c["parameters"][0]
                    rows.append((mid, t[0], face, txt, txt.count("\\I[")))
    return rows


def main():
    quiet = "--quiet" in sys.argv

    srv = P.serve()
    try:
        P.ab.ab("close", "--all")
        time.sleep(1)
        P.ab.ab("set", "viewport", "816", "624")
        P.ab.ab("open", "http://127.0.0.1:%d/index.html" % P.PORT)
        assert P.ab.wait_ready(40), "没能进入游戏"
        P.ab.key("ok", 60)
        for _ in range(40):
            if P.scene() == "Scene_Map":
                break
            time.sleep(0.5)
        time.sleep(1.2)

        m = "SceneManager._scene._messageWindow"
        inner = int(float(P.ev("Math.round(%s.innerWidth)" % m)))
        face_w = int(float(P.ev("ImageManager.standardFaceWidth")))
        icon_w = int(float(P.ev("ImageManager.standardIconWidth"))) + 4

        rows = collect()
        # 图标要先抠掉再量：`textWidth('\\I[2]')` 会把反斜杠和方括号当正文算，
        # 而它实际画成一个图标，步进 standardIconWidth + 4（见 processDrawIcon）。
        stripped = [re.sub(r"\\I\[\d+\]", "", r[3]) for r in rows]
        limits = [(inner - (face_w + 20) if r[2] else inner - 4) + icon_w * r[4]
                  for r in rows]

        if not quiet:
            print("内宽 %d  可用宽：有脸 %d / 无脸 %d  图标步进 %d"
                  % (inner, inner - (face_w + 20), inner - 4, icon_w))

        # 一次 eval 量完：一行一个往返的话，两百多次 CDP 往返要十几秒。
        batch = json.dumps([s for s in stripped], ensure_ascii=False)
        got = P.ev("(function(){var m=%s;var a=%s;return a.map(function(t){"
                   "return Math.round(m.textWidth(t));}).join(',');})()" % (m, batch))
        widths = [int(v) for v in got.split(",") if v != ""]
        err = [l for l in P.ev("(window.__err||[]).join('|')").split("|") if l]
    finally:
        P.ab.ab("close", "--all")
        srv.shutdown()

    bad = 0
    for r, w, lim in zip(rows, widths, limits):
        if w <= lim:
            continue
        bad += 1
        print("  ** 超宽 %3dpx  M%d %-6s %s  %d > %d  %s"
              % (w - lim, r[0], r[1], "有脸" if r[2] else "无脸", w, lim, r[3]))

    print("超宽 %d 行 / 共 %d 行（构建器折行后，引擎复量）" % (bad, len(rows)))
    if bad:
        print("  ↑ 折行模型与引擎不符：换过字体/fontSize？"
              "重跑 .scratch/probe_charwidth.py 重测字宽，再改 build_project.W_HALF/W_FULL")
    if err:
        print("运行时错误：%s" % "|".join(err))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
