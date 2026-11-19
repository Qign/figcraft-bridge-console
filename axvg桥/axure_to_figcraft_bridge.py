# -*- coding: utf-8 -*-
"""
Axure Cloud -> FigCraft 反向转换桥（常驻热键）

用途：在 Axure 里选中元件 -> Ctrl+C（或右键「复制为 Axure Cloud」），
按 Ctrl+Alt+V，把剪贴板里的 axvg 内容直接落到当前打开的 FigCraft 文件里。

前提：FigCraft 必须以 --control 47900 启动（与正向桥共用同一端口）。
      双击「启动FigCraft(带转换桥).lnk」或本目录「启动FigCraft(带反向桥).lnk」。
"""

import ctypes
import ctypes.wintypes as wintypes
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import uuid

LOG_DIR = os.path.join(tempfile.gettempdir(), "axure2figcraft")
LOG_PATH = os.path.join(LOG_DIR, "bridge.log")
PAUSE_FLAG = os.path.join(LOG_DIR, "paused.flag")

HERE = os.path.dirname(os.path.abspath(__file__))
CONVERTER = os.path.join(HERE, "axvg_to_figcraft.py")

DEFAULT_PORT = 47900
DEFAULT_HOTKEY = "ctrl+alt+v"
DEFAULT_PAUSE_HOTKEY = "ctrl+alt+s"
MUTEX_NAME = "Local\\axure_to_figcraft_bridge_singleton"

AXVG_HEADER = "// axvg"


# ---------------- 日志 ----------------
def log(msg):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fp:
            fp.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


# ---------------- 暂停开关 ----------------
def is_paused():
    """flag 内容为 off / resume / resumed 时视为正常，其余（含 paused、空）视为暂停。"""
    try:
        with open(PAUSE_FLAG, "r", encoding="utf-8") as fp:
            return fp.read().strip().lower() not in ("off", "resume", "resumed")
    except Exception:
        return False


def set_paused(on):
    """暂停 = 进程不退、只是不再响应转换热键；状态落在 flag 文件里，重启桥后依然生效。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(PAUSE_FLAG, "w", encoding="utf-8") as fp:
            fp.write(time.strftime("%Y-%m-%d %H:%M:%S") if on else "off")
    except Exception:
        pass


# ---------------- 提示（独立进程，不抢焦点） ----------------
def notify(text, seconds=2.6):
    try:
        exe = sys.executable or ""
        if exe.lower().endswith("python.exe"):
            cand = exe[:-len("python.exe")] + "pythonw.exe"
            if os.path.isfile(cand):
                exe = cand
        subprocess.Popen([exe, os.path.abspath(__file__), "--toast", "%d" % int(seconds * 1000), text],
                         creationflags=0x08000000)
    except Exception:
        pass


def show_toast(text, ms=2600):
    import tkinter as tk
    root = tk.Tk()
    root.overrideredirect(True)
    try:
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.95)
    except Exception:
        pass
    lbl = tk.Label(root, text=text, bg="#1F2430", fg="#FFFFFF",
                   font=("Microsoft YaHei", 10), padx=18, pady=11, justify="left")
    lbl.pack()
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry("+%d+%d" % (max(0, (sw - w) // 2), int(sh * 0.78)))
    root.after(ms, root.destroy)
    root.mainloop()


# ---------------- 剪贴板读取（只读 CF_UNICODETEXT） ----------------
def read_clipboard_text():
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    CF_UNICODETEXT = 13
    u32.OpenClipboard.argtypes = [wintypes.HWND]
    u32.OpenClipboard.restype = wintypes.BOOL
    u32.GetClipboardData.argtypes = [wintypes.UINT]
    u32.GetClipboardData.restype = wintypes.HANDLE
    u32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    u32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalLock.restype = wintypes.LPVOID
    k32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k32.GlobalUnlock.restype = wintypes.BOOL

    for _ in range(10):
        if u32.OpenClipboard(None):
            break
        time.sleep(0.08)
    else:
        raise RuntimeError("剪贴板正被其它程序占用，稍后再试")
    try:
        if not u32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ""
        h = u32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        p = k32.GlobalLock(h)
        if not p:
            return ""
        try:
            return ctypes.wstring_at(p)
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


# ---------------- FigCraft control channel ----------------
class Control(object):
    def __init__(self, port, timeout=60.0):
        self.port = int(port)
        self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=4.0)
        self.sock.settimeout(timeout)
        self.f = self.sock.makefile("rwb")
        self.rid = 0

    def request(self, method, params=None):
        self.rid += 1
        obj = {"id": self.rid, "method": method}
        if params is not None:
            obj["params"] = params
        self.f.write((json.dumps(obj) + "\n").encode("utf-8"))
        self.f.flush()
        line = self.f.readline()
        if not line:
            raise RuntimeError("FigCraft 没有返回数据（窗口可能已关闭）")
        return json.loads(line.decode("utf-8"))

    def close(self):
        try:
            self.f.close()
            self.sock.close()
        except Exception:
            pass


def port_alive(port, timeout=0.4):
    try:
        s = socket.create_connection(("127.0.0.1", int(port)), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


# ---------------- 转换：axvg 文本 -> 命令脚本 ----------------
def axvg_to_commands(text):
    if not os.path.isfile(CONVERTER):
        raise RuntimeError("找不到转换器 %s" % CONVERTER)
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != AXVG_HEADER:
        raise ValueError("剪贴板里不是 Axure Cloud 的复制内容（首行应为 %s）" % AXVG_HEADER)
    if len(lines) < 2 or not lines[1].strip():
        raise ValueError("剪贴板内容不完整，缺少 JSON 数据")

    os.makedirs(LOG_DIR, exist_ok=True)
    tag = uuid.uuid4().hex[:8]
    src = os.path.join(LOG_DIR, "clip_%s.txt" % tag)
    out_name = "script_%s.json" % tag
    out_path = os.path.join(LOG_DIR, out_name)
    with open(src, "w", encoding="utf-8") as fp:
        fp.write(text)

    # 转换器会写到它自己所在的目录，故先复制到 LOG_DIR 再跑，避免污染安装目录
    tmp_conv = os.path.join(LOG_DIR, "axvg_to_figcraft_run.py")
    with open(CONVERTER, "r", encoding="utf-8") as fp:
        conv_code = fp.read()
    if not os.path.isfile(tmp_conv) or os.path.getmtime(tmp_conv) < os.path.getmtime(CONVERTER):
        with open(tmp_conv, "w", encoding="utf-8") as fp:
            fp.write(conv_code)

    r = subprocess.run([sys.executable, tmp_conv, src, out_name], cwd=LOG_DIR,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not os.path.isfile(out_path):
        raise RuntimeError("转换器没有产出脚本：%s" % ((r.stderr or r.stdout or "").strip()[-300:]))
    with open(out_path, "r", encoding="utf-8") as fp:
        cmds = json.load(fp)
    if not cmds:
        raise ValueError("转换结果为空，可能选区内没有可转换元件")
    return cmds


# ---------------- 执行 ----------------
def resolve_refs(obj, ids):
    """把 {"$ref": name} 换成真实节点 id（control 通道不支持 $ref）。"""
    if isinstance(obj, dict):
        if len(obj) == 1 and "$ref" in obj:
            key = obj["$ref"]
            if key not in ids:
                raise RuntimeError("引用了尚未创建的节点：%s" % key)
            return ids[key]
        return {k: resolve_refs(v, ids) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_refs(v, ids) for v in obj]
    return obj


def top_level_bounds(ctl):
    """当前页顶层节点集合，用于把新内容摆到已有内容右侧，避免叠在一起。"""
    try:
        r = ctl.request("document.inspect", {"depth": 2})
        pages = ((r.get("result") or {}).get("pages") or [])
        if not pages:
            return 0.0, 0
        kids = pages[0].get("children") or []
        right = 0.0
        for k in kids:
            b = k.get("absoluteBounds") or {}
            right = max(right, float(b.get("x", 0)) + float(b.get("width", 0)))
        return right, len(kids)
    except Exception:
        return 0.0, 0


def import_to_figcraft(port=DEFAULT_PORT):
    if not port_alive(port):
        raise RuntimeError("FigCraft 没有开控制端口 %d。请用「启动FigCraft(带转换桥).lnk」"
                           "（带 --control %d）启动 FigCraft 后再试。" % (port, port))

    text = read_clipboard_text()
    if not text.strip():
        raise RuntimeError("剪贴板是空的，先在 Axure 里复制要导入的内容")

    cmds = axvg_to_commands(text)

    ctl = Control(port)
    try:
        right, existing = top_level_bounds(ctl)
        ids = {}
        ok, fails = 0, []
        for c in cmds:
            name = c.get("command")
            params = resolve_refs(c.get("params", {}), ids)
            resp = ctl.request("engine.execute", {"command": name, "params": params})
            if resp.get("ok"):
                ok += 1
                if c.get("as"):
                    ids[c["as"]] = (resp.get("result") or {}).get("id")
            else:
                fails.append("%s: %s" % (name, str(resp.get("error"))[:120]))

        # 摆位：已有内容时放到最右侧，留 60 间隙
        moved = False
        root = ids.get("root")
        if root and existing > 0 and right > 0:
            try:
                cur = ctl.request("node.get", {"id": root}).get("result") or {}
                b = cur.get("absoluteBounds") or {}
                if float(b.get("x", 0)) < right + 20:
                    ctl.request("engine.execute", {"command": "node.set",
                                                   "params": {"id": root, "x": right + 60}})
                    moved = True
            except Exception:
                pass
    finally:
        ctl.close()

    stat = {}
    for c in cmds:
        stat[c.get("command")] = stat.get(c.get("command"), 0) + 1
    info = {
        "commands": len(cmds),
        "ok": ok,
        "failed": len(fails),
        "stat": stat,
        "moved": moved,
        "errors": fails[:6],
        "file": os.path.join(LOG_DIR, "last_axvg.txt"),
    }
    try:
        with open(info["file"], "w", encoding="utf-8") as fp:
            fp.write(text)
    except Exception:
        pass
    log("import %s" % json.dumps(info, ensure_ascii=False))
    return info


def summary_text(info):
    stat = info.get("stat") or {}
    parts = []
    if stat.get("frame.create"):
        parts.append("%d 组" % stat["frame.create"])
    if stat.get("node.create"):
        parts.append("%d 元件" % stat["node.create"])
    if stat.get("vector.create"):
        parts.append("%d 矢量" % stat["vector.create"])
    head = "已导入 " + "、".join(parts) if parts else "已导入"
    if info.get("failed"):
        head += "（失败 %d 条）" % info["failed"]
    return head


# ---------------- 单实例 ----------------
def acquire_single_instance():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    h = k32.CreateMutexW(None, False, MUTEX_NAME)
    if not h:
        return None
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return h


# ---------------- 热键 ----------------
def parse_hotkey(spec, fallback_key="V"):
    mods = 0
    key = None
    table = {"ctrl": 0x0002, "control": 0x0002, "alt": 0x0001, "shift": 0x0004, "win": 0x0008}
    for tok in str(spec or "").lower().replace(" ", "").split("+"):
        if not tok:
            continue
        if tok in table:
            mods |= table[tok]
        elif len(tok) == 1 and tok.isalnum():
            key = ord(tok.upper())
        elif tok.upper().startswith("F") and tok[1:].isdigit():
            key = 0x70 + int(tok[1:]) - 1
        elif tok in ("space", "空格"):
            key = 0x20
    if key is None:
        key = ord(fallback_key)
    if mods == 0:
        mods = 0x0002 | 0x0001
    return mods | 0x4000, key  # MOD_NOREPEAT


def do_import(port):
    if is_paused():
        log("paused, ignore hotkey")
        return
    try:
        if not port_alive(port):
            notify("FigCraft 控制端口未开（%d）\n请用「启动FigCraft(带转换桥).lnk」启动" % port)
            return
        info = import_to_figcraft(port)
        notify(summary_text(info))
    except Exception as exc:
        log("convert failed: %s\n%s" % (exc, traceback.format_exc()))
        notify("导入失败：%s" % str(exc)[:160], 4.0)


def do_toggle(hotkey):
    if is_paused():
        set_paused(False)
        log("bridge resumed")
        notify("反向桥已恢复\n在 Axure 复制后按 %s 即可导入" % hotkey.upper())
    else:
        set_paused(True)
        log("bridge paused")
        notify("反向桥已暂停（进程仍在，热键不再转换）\n按 %s 恢复；彻底停用请运行「停用桥.bat」"
               % DEFAULT_PAUSE_HOTKEY.upper())


def hotkey_loop(port, hotkey, pause_hotkey, depth=None):
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    m, k = parse_hotkey(hotkey, "V")
    if not u32.RegisterHotKey(None, 1, m, k):
        notify("热键 %s 被其它程序占用了\n可先运行「停用桥.bat」清干净，或用 --hotkey 换一组键"
               % hotkey.upper(), 4.0)
        log("register convert hotkey failed: %s" % hotkey)
        return 1
    pm, pk = parse_hotkey(pause_hotkey, "S")
    if not u32.RegisterHotKey(None, 2, pm, pk):
        log("register pause hotkey failed: %s" % pause_hotkey)

    log("hotkey loop started, port=%s hotkey=%s pause=%s" % (port, hotkey, pause_hotkey))
    msg = wintypes.MSG()
    try:
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                if msg.wParam == 1:
                    do_import(port)
                else:
                    do_toggle(hotkey)
    finally:
        u32.UnregisterHotKey(None, 1)
        u32.UnregisterHotKey(None, 2)
    return 0


# ---------------- 入口 ----------------
def main(argv):
    port = DEFAULT_PORT
    hotkey = DEFAULT_HOTKEY
    pause_hotkey = DEFAULT_PAUSE_HOTKEY
    args = list(argv[1:])

    if "--toast" in args:
        i = args.index("--toast")
        try:
            ms = int(args[i + 1])
            text = " ".join(args[i + 2:])
        except Exception:
            ms, text = 2600, "提示"
        show_toast(text, ms)
        return 0

    def take(name, default=None):
        if name in args:
            i = args.index(name)
            if i + 1 < len(args):
                return args[i + 1]
        return default

    port = int(take("--port", DEFAULT_PORT))
    hotkey = take("--hotkey", DEFAULT_HOTKEY)
    pause_hotkey = take("--pause-hotkey", DEFAULT_PAUSE_HOTKEY)

    if "--status" in args:
        print(json.dumps({"paused": is_paused(), "port": port, "portAlive": port_alive(port)}, ensure_ascii=False))
        return 0
    if "--pause" in args:
        set_paused(True)
        print("bridge paused")
        return 0
    if "--resume" in args:
        set_paused(False)
        print("bridge resumed")
        return 0
    if "--once" in args:
        try:
            info = import_to_figcraft(port)
            print(json.dumps(info, ensure_ascii=False, indent=2))
            return 0 if not info.get("failed") else 2
        except Exception as exc:
            print("ERROR: %s" % exc)
            return 1

    if not port_alive(port):
        print("提示：FigCraft 当前没有开控制端口 %d。" % port)
        print("请用「启动FigCraft(带转换桥).lnk」启动 FigCraft（带 --control %d）。" % port)

    if acquire_single_instance() is None:
        print("反向桥已经在运行，不必重复启动")
        print("彻底关闭请双击「停用桥.bat」")
        return 0

    log("bridge starting")
    return hotkey_loop(port, hotkey, pause_hotkey)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
