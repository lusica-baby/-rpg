"""Day 1 最小链路 —— 从 newdata 模板生成一个可玩的 RPG Maker MZ 工程。

产物：1 张地图（17x13）+ 2 个事件（说话的 NPC、会叫的癞头蟆），玩家起始点在地图上。
目的：验证「直写 JSON」这条路可行，为管线 F 阶段（工程生成器）探路。

本轮新增两条验证：
  1. 非 RTP 自制素材能否注入并正确渲染（$ 前缀单角色图）
  2. 播放 SE 指令（code 250）能否触发

用法：
    python build_day1.py
"""
import json
import os
import shutil

MZ = r"D:\Steam\steamapps\common\RPG Maker MZ"
TEMPLATE = os.path.join(MZ, "newdata")
ROOT = r"C:\Users\lenovo\WorkBuddy\2026-09-22-19-16-43\rpgmaker-ai-pipeline"
TARGET = os.path.join(ROOT, "CuzhiDemo")
# 自制素材。目录结构与工程一致，构建时整棵覆盖过去。
ASSETS = os.path.join(ROOT, "assets")

# ---- 本工程的内容参数（后续由管线 A-D 阶段产出）----
TITLE = "促织"
MAP_NAME = "村口"
PLAYER_X, PLAYER_Y = 8, 8
FALLBACK_FONTS = "Microsoft YaHei, SimHei, sans-serif"

# 玩家 = 成名。行走图与脸图都在 assets/ 里，靠 Actors.json 引用。
PLAYER_NAME = "成名"
PLAYER_CHAR = "$ChengMing"
PLAYER_FACE = "ChengMing"

# 里胥 —— 催缴的人。有行走图，暂无脸图，所以对话不显示头像框。
LIXU_POS = (8, 4)
LIXU_NAME = "里胥"
LIXU_IMAGE = {
    "tileId": 0,
    "characterName": "$LiXu",   # $ 前缀 = 单角色图，3 列 × 4 行
    "direction": 2,             # 面朝下，正对玩家
    "pattern": 1,
    "characterIndex": 0,        # 单角色图只有第 0 个
}
LIXU_LINES = [
    "成名，县里催缴蟋蟀，已催到第九回了。",
    "再交不上来，你那点薄产就抵了吧。",
]

# 成子 —— 行走图和脸图都有，用来验证「小人 + 头像」同时在游戏里渲染。
CHENGZI_POS = (5, 8)
CHENGZI_NAME = "成子"
CHENGZI_IMAGE = {
    "tileId": 0,
    "characterName": "$ChengZi",
    "direction": 2,
    "pattern": 1,
    "characterIndex": 0,
}
CHENGZI_FACE = ("ChengZi", 0)      # 索引 0 = 脸图第 1 张（忧虑）
CHENGZI_LINES = [
    "爹，天都黑了，你怎么还不睡？",
    "……我梦见自己变成了一只蟋蟀。",
]

# 癞头蟆 —— 验证自制素材 + 播放 SE
FROG_POS = (11, 8)
FROG_NAME = "癞头蟆"
FROG_IMAGE = {
    "tileId": 0,
    "characterName": "$Frog",   # $ 前缀 = 单角色图，3 列 × 4 行
    "direction": 2,
    "pattern": 1,
    "characterIndex": 0,        # 单角色图只有第 0 个
}
FROG_SE = {"name": "Frog", "volume": 90, "pitch": 100, "pan": 0}
FROG_LINES = [
    "一只癞头蟆伏在草丛里，鼓着眼睛看你。",
    "你一动，它便猝然跃去，没了踪影。",
]


def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def jdump(path, obj):
    """按 MZ 自己的写法落盘：单行、不转义非 ASCII、紧凑分隔符。"""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def inject_assets():
    """把 assets/ 整棵覆盖进工程，用于注入非 RTP 的自制素材。

    要让 $Frog.png 生效，就放在 assets/img/characters/ 下。
    这是「素材替换接口」：Day 6 若要换掉整批 RTP 角色，替换 assets 内容即可，
    构建脚本与事件数据一行都不用改。
    """
    if not os.path.isdir(ASSETS):
        return 0
    shutil.copytree(ASSETS, TARGET, dirs_exist_ok=True)
    return sum(len(fs) for _, _, fs in os.walk(ASSETS))


def configure_actors():
    """把玩家（actor 1）换成成名，并把队伍砍成单人。

    队伍默认是 4 人，会有 3 个跟随者排队跟在玩家身后 —— 单人叙事下既遮挡场景，
    又容易被误判成「地图上多出来的 NPC」（Day 1 就这么误判过一次）。
    """
    ap = os.path.join(TARGET, "data", "Actors.json")
    actors = jload(ap)
    for a in actors:
        if a and a["id"] == 1:
            a["name"] = PLAYER_NAME
            a["nickname"] = PLAYER_NAME
            a["characterName"] = PLAYER_CHAR
            a["characterIndex"] = 0
            a["faceName"] = PLAYER_FACE
            a["faceIndex"] = 0
    jdump(ap, actors)

    sp = os.path.join(TARGET, "data", "System.json")
    sysj = jload(sp)
    sysj["partyMembers"] = [1]
    jdump(sp, sysj)
    return "%s（行走图 %s / 脸图 %s）" % (PLAYER_NAME, PLAYER_CHAR, PLAYER_FACE)


def build_dialogue(lines, face, speaker):
    """人类可读的对话 → MZ 事件指令序列。

    101 = 显示文字 [脸图文件名, 脸图索引, 背景, 位置, 说话人]
    401 = 文本续行 [一行文字]
    0   = 指令列表结束标记
    """
    cmds = [{"code": 101, "indent": 0, "parameters": [face[0], face[1], 0, 2, speaker]}]
    for line in lines:
        cmds.append({"code": 401, "indent": 0, "parameters": [line]})
    cmds.append({"code": 0, "indent": 0, "parameters": []})
    return cmds


def build_frog_commands():
    """癞头蟆的指令序列：先出声，再说话。

    250 = 播放 SE（源码 command250 调 AudioManager.playSe）。
    注意它的参数是**一个音频对象** [{"name","volume","pitch","pan"}]，
    与 101 那种「多个平铺参数」不是同一种形状 —— 写错不会报错，只是没声音。
    蛤蟆没有脸图，faceName 传空字符串即不显示头像框。
    """
    cmds = [{"code": 250, "indent": 0, "parameters": [dict(FROG_SE)]}]
    cmds.append({"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, FROG_NAME]})
    for line in FROG_LINES:
        cmds.append({"code": 401, "indent": 0, "parameters": [line]})
    cmds.append({"code": 0, "indent": 0, "parameters": []})
    return cmds


def build_page(image, commands, trigger=0, priority=1):
    """事件页。trigger=0 表示「按确定键触发」，priority=1 表示与玩家同层。"""
    return {
        "conditions": {
            "actorId": 1, "actorValid": False,
            "itemId": 1, "itemValid": False,
            "selfSwitchCh": "A", "selfSwitchValid": False,
            "switch1Id": 1, "switch1Valid": False,
            "switch2Id": 1, "switch2Valid": False,
            "variableId": 1, "variableValid": False, "variableValue": 0,
        },
        "directionFix": False,
        "image": image,
        "list": commands,
        "moveFrequency": 3,
        "moveRoute": {
            "list": [{"code": 0, "parameters": []}],
            "repeat": True, "skippable": False, "wait": False,
        },
        "moveSpeed": 3,
        "moveType": 0,
        "priorityType": priority,
        "stepAnime": False,
        "through": False,
        "trigger": trigger,
        "walkAnime": True,
    }


def build_event(eid, name, x, y, image, lines=None, face=None, commands=None):
    if commands is None:
        commands = build_dialogue(lines, face, name)
    return {
        "id": eid,
        "name": name,
        "note": "",
        "pages": [build_page(image, commands)],
        "x": x,
        "y": y,
    }


def main():
    if os.path.isdir(TARGET):
        shutil.rmtree(TARGET)
    shutil.copytree(TEMPLATE, TARGET)
    print("[1/7] 模板已复制 -> %s" % TARGET)

    n = inject_assets()
    print("[2/7] 自制素材注入 %d 个文件（assets/ 整棵覆盖）" % n)

    # 工程标识文件：就是一行纯文本
    with open(os.path.join(TARGET, "game.rmmzproject"), "w", encoding="utf-8", newline="\n") as f:
        f.write("RPGMZ 1.0.1")
    print("[3/7] game.rmmzproject 已写入")

    # System.json：标题、起始点、中文字体回退、强制编辑器重载
    sp = os.path.join(TARGET, "data", "System.json")
    sysj = jload(sp)
    sysj["gameTitle"] = TITLE
    sysj["startMapId"] = 1
    sysj["startX"] = PLAYER_X
    sysj["startY"] = PLAYER_Y
    sysj["editMapId"] = 1
    sysj["advanced"]["fallbackFonts"] = FALLBACK_FONTS
    # 官方 newdata 模板缺这个字段，而引擎 Game_System.prototype.windowOpacity()
    # 是零兜底的 `return $dataSystem.advanced.windowOpacity;` —— 不补则一进标题画面
    # 就 `Cannot read properties of undefined (reading 'clamp')`。
    # 编辑器保存工程时会自动补上，手搓工程必须自己补。
    # 校验：tools/check_system_contract.py
    sysj["advanced"]["windowOpacity"] = sysj["advanced"].get("windowOpacity", 192)
    sysj["versionId"] = (sysj.get("versionId") or 0) + 1
    jdump(sp, sysj)
    print("[4/7] System.json 已修：标题=%s 起点=(%d,%d) 字体回退=%s"
          % (TITLE, PLAYER_X, PLAYER_Y, FALLBACK_FONTS))

    print("[5/7] Actors.json 已修：玩家 = %s" % configure_actors())

    # MapInfos.json：地图在地图树里的名字
    ip = os.path.join(TARGET, "data", "MapInfos.json")
    infos = jload(ip)
    for item in infos:
        if item and item["id"] == 1:
            item["name"] = MAP_NAME
    jdump(ip, infos)
    print("[6/7] MapInfos.json 已修：地图 1 -> %s" % MAP_NAME)

    # Map001.json：挂三个事件
    mp = os.path.join(TARGET, "data", "Map001.json")
    m = jload(mp)
    m["displayName"] = MAP_NAME
    lixu = build_event(1, LIXU_NAME, LIXU_POS[0], LIXU_POS[1], LIXU_IMAGE,
                       LIXU_LINES, ("", 0))          # 空 faceName = 不显示头像框
    frog = build_event(2, FROG_NAME, FROG_POS[0], FROG_POS[1], FROG_IMAGE,
                       commands=build_frog_commands())
    zi = build_event(3, CHENGZI_NAME, CHENGZI_POS[0], CHENGZI_POS[1], CHENGZI_IMAGE,
                     CHENGZI_LINES, CHENGZI_FACE)
    m["events"] = [None, lixu, frog, zi]
    jdump(mp, m)
    print("[7/7] Map001.json 已挂 3 个事件：%s@%s（无脸图）/ %s@%s / %s@%s（有脸图）"
          % (LIXU_NAME, LIXU_POS, FROG_NAME, FROG_POS, CHENGZI_NAME, CHENGZI_POS))
    print("      地图 %dx%d，瓦片数据长度 %d" % (m["width"], m["height"], len(m["data"])))

    print("\n完成。工程目录：%s" % TARGET)


if __name__ == "__main__":
    main()
