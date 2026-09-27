# -*- coding: utf-8 -*-
"""agent-browser 薄封装：解决「按键必须被按住至少一帧」的坑。

为什么需要它
------------
MZ 的输入是**轮询式**的：
    Input._onKeyDown -> this._currentState[key] = true
    Input._onKeyUp   -> this._currentState[key] = false
    Input.update()   -> 每帧检查 _currentState，见 true 才算一次触发

`agent-browser press Enter` 会在同一个 tick 内发完 keydown + keyup，
于是 _currentState 被置 true 又立刻置 false，**游戏一帧都没看见**。
症状是「按键没反应、停在标题画面」，极容易被误判成工程有问题。

做法：keydown / 停留 / keyup 三段式。停留期跨过若干帧，游戏就能识别。

用法
----
    python tools/ab.py open <url>
    python tools/ab.py shot <图片路径>
    python tools/ab.py key <键码> [按住毫秒]
    python tools/ab.py wait <毫秒>
    python tools/ab.py eval "<js>"
    python tools/ab.py console
"""
import os
import subprocess
import sys
import tempfile
import time

# 本机 agent-browser 的位置。换机器（或它升级换了目录）用环境变量覆盖，
# 别改这里 —— 这个文件属于工程，不该焊死一台机器的安装路径。
NODE = os.environ.get("AB_NODE",
                      r"C:\Users\lenovo\.workbuddy\binaries\node\versions\22.22.2-3\node.exe")
AB = os.environ.get("AB_CLI",
                    r"C:\Users\lenovo\.workbuddy\binaries\node\workspace\node_modules\agent-browser\bin\agent-browser.js")
# 独立会话名。用 default 会撞上别处残留的守护进程，导致 open 直接挂死。
SESSION = os.environ.get("AB_SESSION", "pt")

# MZ Input.keyMapper 里的几个常用键
KEYS = {"ok": 13, "up": 38, "down": 40, "left": 37, "right": 39,
        "cancel": 27, "menu": 88, "shift": 16, "debug": 120}

_DOWN = ("(function(k,ms){var d=new KeyboardEvent('keydown',{bubbles:true,cancelable:true});"
         "Object.defineProperty(d,'keyCode',{get:function(){return k}});"
         "Object.defineProperty(d,'which',{get:function(){return k}});"
         "document.dispatchEvent(d);"
         "setTimeout(function(){var u=new KeyboardEvent('keyup',{bubbles:true,cancelable:true});"
         "Object.defineProperty(u,'keyCode',{get:function(){return k}});"
         "Object.defineProperty(u,'which',{get:function(){return k}});"
         "document.dispatchEvent(u);},ms);"
         "return 'hold '+k+' '+ms+'ms';})(%d,%d)")


def ab(*args, timeout=90):
    """调一次 agent-browser。

    坑一：它会在首次调用时派一个**常驻守护进程**，该进程继承父进程的
    stdout/stderr。若用 subprocess 的 capture_output=True（管道），管道永远
    等不到 EOF，communicate() 就无限期挂住 —— 表现为「命令无输出、被 SIGTERM
    杀掉」。所以这里把输出写到临时文件，而不是管道。
    坑二：偶尔会在 open 上挂死，故设超时护栏。
    """
    fd, tmp = tempfile.mkstemp(suffix=".ab.log")
    os.close(fd)
    init = os.environ.get("AB_INIT")
    head = [NODE, AB, "--session", SESSION]
    if init:
        head += ["--init-script", init]     # 页面加载前注入钩子
    try:
        with open(tmp, "w+", encoding="utf-8", errors="replace") as out:
            try:
                subprocess.run(head + [str(a) for a in args],
                               stdout=out, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, timeout=timeout)
            except subprocess.TimeoutExpired:
                print("!! 超时 %ds: agent-browser %s"
                      % (timeout, " ".join(str(a) for a in args)), flush=True)
                return ""
            out.seek(0)
            text = out.read().strip()
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if "command not found" in text:
        text = "\n".join(l for l in text.splitlines() if "command not found" not in l).strip()
    return text


_READY_JS = ("typeof SceneManager !== 'undefined' && SceneManager._scene"
             " ? SceneManager._scene.constructor.name : 'BOOTING'")


def wait_ready(timeout=30, keep=False):
    """等 MZ 离开 Scene_Boot。

    两个坑：
    - boot 期间按键会被丢掉，必须等；
    - 若守护进程已死，会话里的页面会变成空白页，此时 eval 拿到的是
      'BOOTING' 或 ReferenceError 文本，不能当成「已就绪」。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        scene = ab("eval", _READY_JS)
        if scene and "Scene_Boot" not in scene and "BOOTING" not in scene \
                and "error" not in scene.lower():
            print("  已就绪: %s（%.1fs）" % (scene.strip('"'), time.time() - t0), flush=True)
            return True
        time.sleep(1)
    print("!! 等待就绪超时，当前: %s" % scene, flush=True)
    return False


def key(code, hold_ms=25):
    """按一次键：keydown → 停 hold_ms → keyup，**全部在浏览器内定时**。

    code 可用键名（ok/up/down/left/right/cancel）或直接给键码。

    四个坑，缺一个测出来的结果就是假的：

    1. **定时必须在浏览器内**。若用 Python 的 sleep 控制按住时长，实际时长会被
       `ab()` 每次新起 node 进程的 1~2 秒开销吞掉，一按走 6 格。
       用页面里的 setTimeout，时长才准。
    2. **不能在同一 tick 按下又抬起**。MZ 的 Input 是每帧轮询 `_currentState`，
       keydown+keyup 同帧发完，游戏一帧都看不见（表现为「按键完全没反应」）。
    3. **按住太久，消息窗会被推进关闭**。MZ 把「确定键仍按住」当作连续确认，
       窗口刚开就被关掉，看起来像「对话根本没触发」。实测 600ms 必关。
    4. **墙钟时长换算不出格数**。headless Chrome 的 rAF 帧率不等于 60fps，
       MZ 的移动是按帧推进的，所以「按住 280ms 走几格」随环境而变。

    实测（headless Chrome）：**25ms ≈ 恰好一格**，60ms 足够且不会误触推进。
    方向键用 25，确定/取消用 60。
    """
    if isinstance(code, str) and not code.isdigit():
        code = KEYS[code]
    code = int(code)
    return ab("eval", _DOWN % (code, hold_ms))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd, rest = sys.argv[1], sys.argv[2:]

    if cmd == "key":
        key(rest[0], int(rest[1]) if len(rest) > 1 else 250)
    elif cmd == "shots":
        # shots <前缀> <键码1> <键码2> ... 逐步按键并截图
        prefix = rest[0]
        for i, k in enumerate(rest[1:], 1):
            key(k)
            time.sleep(0.8)
            ab("screenshot", "%s-%02d.png" % (prefix, i))
    elif cmd == "seq":
        # seq <url> <outdir> <名字:键码[:按住ms]> ... —— 一条命令跑完整个验收序列
        url, outdir = rest[0], rest[1]
        os.makedirs(outdir, exist_ok=True)
        print("重置浏览器会话…", flush=True)
        ab("close", "--all")
        time.sleep(1)
        ab("open", url)
        wait_ready()
        for i, step in enumerate(rest[2:], 1):
            parts = step.split(":")
            name = parts[0]
            if parts[1] == "wait":
                time.sleep(int(parts[2]) / 1000.0)
                note = "wait %sms" % parts[2]
            elif parts[1] == "eval":
                # JS 里会有冒号，所以用 ":" 重新拼回去
                js = ":".join(parts[2:])
                note = ab("eval", js)
            else:
                key(parts[1], int(parts[2]) if len(parts) > 2 else 250)
                time.sleep(0.8)
                note = "key %s" % parts[1]
            if not name.startswith("-"):   # 名字以 - 开头：只做动作，不截图
                path = os.path.join(outdir, "%02d-%s.png" % (i, name))
                ab("screenshot", path)
            print("  %02d %-12s %s" % (i, name, note), flush=True)
    else:
        print(ab(cmd, *rest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
