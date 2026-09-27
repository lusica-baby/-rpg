"""本地试玩 —— 把 CuzhiDemo/ 挂到 http://127.0.0.1:8321/ 用浏览器打开。

**为什么不能直接双击 index.html**：MZ 用 XHR 取 data/*.json 和 img/ 下的位图，
`file://` 下一律被 CORS 拦掉，游戏卡在加载页。必须走 HTTP。

    python tools/serve_game.py      起服务，Ctrl+C 停
    python tools/serve_game.py 9000 换端口起（默认 8321，被占就往后找）

起完会自检几个关键资源（状态码 + Content-Type + 字节数）——
"服务器起来了"和"游戏能跑"是两回事，资源取不到时浏览器只会白屏。
"""

import functools
import http.server
import json
import os
import socket
import sys
import threading
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TARGET = os.path.join(ROOT, "CuzhiDemo")
HOST = "127.0.0.1"

# 不信注册表：Windows 上 .woff/.ttf 没有映射（mimetypes 返回 None），
# .js 在某些机器上被登记成 text/plain —— 那会让 <script> 直接被浏览器拒载。
# 这几个写死。
MIME = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".wasm": "application/wasm",
}
http.server.SimpleHTTPRequestHandler.extensions_map.update(MIME)


class Handler(http.server.SimpleHTTPRequestHandler):
    """只报错，不刷屏 —— 一个 MZ 工程开局要拉几十个资源。"""

    def end_headers(self):
        # 构建器整棵覆盖 CuzhiDemo/：不缓存，改完刷新就是新的，
        # 免得看的是上一版还以为改动没生效。
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_request(self, code="-", size="-"):
        try:
            if int(code) >= 400:
                sys.stdout.write("  %s %s -> %s\n" % (self.command, self.path, code))
                sys.stdout.flush()
        except (TypeError, ValueError):
            pass


def pick_port(start):
    for p in range(start, start + 10):
        with socket.socket() as s:
            try:
                s.bind((HOST, p))
                return p
            except OSError:
                continue
    raise SystemExit("%d~%d 都被占用了，换一个起始端口。" % (start, start + 9))


def first(rel_dir, ext):
    d = os.path.join(TARGET, rel_dir)
    for f in sorted(os.listdir(d)):
        if f.lower().endswith(ext):
            return "%s/%s" % (rel_dir, f)
    return None


def probe(port):
    """拉几个关键资源 —— 这一类失败浏览器只会白屏，不解释。

    两个坑都踩过，各修一处：

    ① **必须绕开系统代理**。本机 IE/系统设置里配了 HTTP 代理，而 `urlopen` 默认
       走 `getproxies()`；对 127.0.0.1 的请求被丢给代理，表现是**干脆超时**
       （不是 connection refused），会让人误判成"服务器没起来"。而浏览器对
       localhost 自带 bypass，所以"我能跑"和"探针能连"是两回事。
    ② **自检失败不许把服务带走**。原来 probe 抛异常直接冒到 main，banner 打完
       就退出 —— 探针挂了、游戏其实好好的。
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    base = "http://%s:%d/" % (HOST, port)
    checks = ["index.html", "data/System.json", "data/Map001.json",
              "js/rmmz_core.js", "js/plugins.js",
              "fonts/mplus-1m-regular.woff", first("audio/bgm", ".ogg"),
              first("img/faces", ".png")]
    bad = 0
    for rel in checks:
        if rel is None:
            continue
        try:
            with opener.open(base + rel, timeout=5) as r:
                body = r.read()
                ctype = (r.headers.get("Content-Type") or "").split(";")[0]
                flag = "" if r.status == 200 and body else "   <== 空/异常"
                if flag:
                    bad += 1
                print("  %-34s %s  %-26s %8d B%s"
                      % (rel, r.status, ctype, len(body), flag))
        except Exception as e:
            bad += 1
            print("  %-34s 取不到：%s" % (rel, e))
    try:
        with opener.open(base + "data/System.json", timeout=5) as r:
            print("\n  标题 = %r" % json.load(r)["gameTitle"])
    except Exception as e:
        bad += 1
        print("\n  标题读不到：%s" % e)
    return bad


def main():
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 8321
    if not os.path.isdir(TARGET):
        raise SystemExit("找不到 %s —— 先跑 tools/build_project.py。" % TARGET)
    port = pick_port(start)
    handler = functools.partial(Handler, directory=TARGET)
    srv = http.server.ThreadingHTTPServer((HOST, port), handler)

    # **先真的开始 accept，再去自检。** 构造函数只做到 bind+listen：
    # 没有 accept 循环时，三次握手由内核 backlog 收下，HTTP 请求却没人应答
    # —— 探针表现是「干脆超时」，backlog 满了才变成 connection refused。
    # 我第一版就是把 probe 写在 serve_forever() 前面，于是自检全红、服务其实好好的。
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    print("=" * 62)
    print("  促织 · 本地试玩")
    print("=" * 62)
    print("  地址    http://%s:%d/" % (HOST, port))
    print("  目录    %s" % os.path.relpath(TARGET, ROOT))
    print("\n自检：")
    bad = probe(port)
    print("\n  自检%s（%d 个资源取不到）"
          % ("通过" if bad == 0 else "**失败**", bad))
    print("  操作    方向键 / WASD 移动   Enter / Z 确定   Esc / X 菜单")
    print("\n  Ctrl+C 停止。窗口关掉服务就没了。\n")
    sys.stdout.flush()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("  已停止。")


if __name__ == "__main__":
    main()
