// 输入/事件链探针：用 --init-script 注入，页面加载前挂钩子。
// 读法：agent-browser eval "JSON.stringify(window.__log)"
//
// **上限 2000，别往下调。** 早先写的是 200（注释还写着 80，两边都不对），
// 结果一次多图走查跑下来：kd/ku 每次按键两条 + interpUpd 每条指令一条，
// 十几段对话就堆到 300+ —— 数组先在 200 截断，后面的记录**一条都不进**。
// 表现是「SE 调用：（无）」这种假阴性：蛤蟆的 playSe 确实响了，只是没记上。
// 上限的作用是防逐帧调用把数组撑爆，而这里挂的都是低频钩子，2000 远够。
window.__log = [];
window.__err = [];
// 音频**单独一个数组**，理由见下面的 swrap。
window.__se = [];
var LOG_MAX = 2000;
function L(s) {
    if (window.__log.length < LOG_MAX) {
        window.__log.push(s);
    } else if (window.__log.length === LOG_MAX) {
        window.__log.push("__LOG_TRUNCATED__");
    }
}

// 未捕获异常 —— 崩溃排查的第一现场。缺了它，「画面卡住」就查不出原因。
window.addEventListener("error", function (e) {
    window.__err.push("ERR " + e.message + " @" + (e.filename || "?") + ":" + e.lineno);
});
window.addEventListener("unhandledrejection", function (e) {
    var r = e.reason;
    window.__err.push("REJ " + ((r && r.message) || String(r)));
});
(function catchScene() {
    if (typeof SceneManager === "undefined") { setTimeout(catchScene, 100); return; }
    var orig = SceneManager.catchException;
    SceneManager.catchException = function (e) {
        window.__err.push("SCENE " + (e && (e.stack || e.message) || String(e)));
        return orig.apply(this, arguments);
    };
})();

document.addEventListener("keydown", function (e) { L("kd:" + e.keyCode); });
document.addEventListener("keyup", function (e) { L("ku:" + e.keyCode); });

(function patch() {
    if (typeof Game_Player === "undefined" || typeof Game_Interpreter === "undefined") {
        setTimeout(patch, 100);
        return;
    }
    function wrap(obj, name, tag, mk) {
        var orig = obj[name];
        obj[name] = function () {
            var out = mk ? mk.apply(this, arguments) : "";
            var r = orig.apply(this, arguments);
            L(tag + (out ? " " + out : "") + " -> " + r);
            return r;
        };
    }

    wrap(Game_Player.prototype, "checkEventTriggerThere", "there", function (t) { return JSON.stringify(t); });
    wrap(Game_Event.prototype, "start", "evStart", function () { return "#" + this._eventId; });
    wrap(Game_Map.prototype, "setupStartingEvent", "setupStarting");
    wrap(Game_Interpreter.prototype, "command101", "c101", function () { return "busy=" + $gameMessage.isBusy(); });
    wrap(Game_Message.prototype, "add", "msgAdd", function (t) { return JSON.stringify(String(t).slice(0, 12)); });
    wrap(Game_Message.prototype, "clear", "msgClear");
    wrap(Game_Interpreter.prototype, "terminate", "interpEnd");
    wrap(Window_Message.prototype, "startMessage", "winStartMsg");
    wrap(Window_Message.prototype, "open", "winOpen");
    // 音频：headless 里听不到，只能看调用。
    //
    // **音频不能塞进 __log。** 早先它是 walk 成 __log 里的 "playSe Frog" 一行，
    // 再由走查工具 filter 出来 —— 但 __log 有 2000 的上限（那是给逐帧钩子兜底的），
    // 一次三图走查的 kd/ku + interpUpd 正好把它顶到上限，于是**靠后的音频调用
    // 一条都不进**：M1 的蛤蟆亮着、M3 的蛤蟆没影，看着像 SE 没响。
    // 音频调用一局不超过二十次，独立数组 + 小上限即可，且不再受 __log 拖累。
    // 记的是**整个音频对象**，所以 volume/pitch/pan 缺哪个字段都看得出来。
    function swrap(obj, name, kind) {
        var orig = obj[name];
        obj[name] = function (b) {
            if (window.__se.length < 200) {
                window.__se.push(kind + " " + (b
                    ? b.name + " vol=" + b.volume + " pitch=" + b.pitch + " pan=" + b.pan
                    : String(b)));
            }
            return orig.apply(this, arguments);
        };
    }
    swrap(AudioManager, "playSe", "se");
    swrap(AudioManager, "playBgm", "bgm");
    swrap(AudioManager, "playBgs", "bgs");
    swrap(AudioManager, "playMe", "me");

    var lastIdx = -1;
    var origUpd = Game_Interpreter.prototype.update;
    Game_Interpreter.prototype.update = function () {
        var running = this.isRunning();
        if (running && this._index !== lastIdx) {
            lastIdx = this._index;
            L("interpUpd idx=" + this._index);
        }
        return origUpd.apply(this, arguments);
    };

    L("PATCHED");
})();
