# -*- coding: utf-8 -*-
"""
core_a2f —— Axure -> FigCraft 转换核心

来源：D:\\AI\\FigCraft\\axvg桥\\axure_to_figcraft_bridge.py
      D:\\AI\\FigCraft\\axvg桥\\axvg_to_figcraft.py
处理方式：axvg -> 命令脚本（hx / fill_of / stroke_of / text_of / svg_path / collect / build_commands）
          与执行侧（read_clipboard_text / resolve_refs / top_level_bounds / import_to_figcraft）整体搬迁，
          逻辑零改动。唯一变化：原来靠 subprocess 调 axvg_to_figcraft.py，现改为同进程调用 build_commands，
          避免打包成 exe 后 sys.executable 指向 exe 自身而失效。
仅剥离外壳：日志改为可注入回调、输出目录改为运行时配置、删除 hotkey / flag / 单实例 / main。

对外入口（保持不变）：
    import_to_figcraft(port=47900) -> info dict
    summary_text(info) -> str
"""
import ctypes
import ctypes.wintypes as wintypes
import json
import os
import socket
import time
import uuid

# ---------------- 运行时配置（由 app.py 注入） ----------------
WORK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_work")
_LOGGER = None


def configure(work_dir=None, logger=None):
    global WORK_DIR, _LOGGER
    if work_dir:
        WORK_DIR = work_dir
    if logger is not None:
        _LOGGER = logger


def log(msg):
    if _LOGGER:
        try:
            _LOGGER(msg)
            return
        except Exception:
            pass


DEFAULT_PORT = 47900
AXVG_HEADER = "// axvg"


# =====================================================================
# 一、axvg 文本 -> FigCraft 命令脚本（原 axvg_to_figcraft.py，逻辑不变）
# =====================================================================
def hx(c):
    if not c:
        return None
    r = int(round(c.get("r", 0) * 255)); g = int(round(c.get("g", 0) * 255)); b = int(round(c.get("b", 0) * 255))
    a = c.get("a", 1.0)
    if a >= 0.999:
        return "#%02X%02X%02X" % (r, g, b)
    return "#%02X%02X%02X%02X" % (r, g, b, int(round(a * 255)))


def fill_of(it):
    fills = it.get("backgroundFills") or []
    for f in fills:
        if f.get("enabled") is False:
            continue
        col = f.get("color")
        if col and col.get("a", 1) > 0.001:
            return hx(col)
    return None


def stroke_of(it):
    w = it.get("strokeThickness") or 0
    if w <= 0:
        return None, None
    for s in (it.get("strokes") or []):
        col = ((s or {}).get("fill") or {}).get("color")
        if col and col.get("a", 1) > 0.001:
            return hx(col), w
    return None, None


def text_of(it):
    t = it.get("text")
    if not t:
        return None, None
    paras = t.get("paragraphs") or []
    lines, first = [], None
    for para in paras:
        s = ""
        for inl in para.get("inlines") or []:
            s += inl.get("text") or ""
            if first is None and (inl.get("text") or ""):
                first = (para, inl)
        lines.append(s)
    body = "\n".join(lines)
    if not body.strip():
        return None, None
    return body, first


def svg_path(path, w, h):
    data = path.get("data") or []
    if not data:
        return None
    closed = path.get("closed", True)

    def P(p):
        if not p:
            return None
        return (round(p["x"] * w, 2), round(p["y"] * h, 2))

    def Q(h, fb):
        return P(h) or P(fb)

    pts = data
    d = ["M %s %s" % P(pts[0]["to"])]
    for i in range(1, len(pts)):
        prev, cur = pts[i - 1], pts[i]
        c1 = Q(prev.get("lowerHandle"), prev["to"])
        c2 = Q(cur.get("higherHandle"), cur["to"])
        to = P(cur["to"])
        d.append("C %s %s %s %s %s %s" % (c1[0], c1[1], c2[0], c2[1], to[0], to[1]))
    if closed and len(pts) > 1:
        prev, p0 = pts[-1], pts[0]
        c1 = Q(prev.get("lowerHandle"), prev["to"])
        c2 = Q(p0.get("higherHandle"), p0["to"])
        to = P(p0["to"])
        d.append("C %s %s %s %s %s %s" % (c1[0], c1[1], c2[0], c2[1], to[0], to[1]))
        d.append("Z")
    return " ".join(d)


def collect(cmd, out, ox, oy, as_name, parent_ref="root"):
    r = cmd.get("rect") or {}
    loc = r.get("location") or {}
    sz = r.get("size") or {}
    x = round((loc.get("x") or 0) - ox, 2)
    y = round((loc.get("y") or 0) - oy, 2)
    w = round(sz.get("width") or 0, 2)
    h = round(sz.get("height") or 0, 2)
    name = cmd.get("name") or "layer"
    props = {}
    body, first = text_of(cmd)
    kids = ((cmd.get("scene") or {}).get("items") or [])

    if kids:
        props["fill"] = "none"
        c = {"command": "frame.create", "params": {"x": x, "y": y, "width": w, "height": h, "name": name, "props": props}}
        c["as"] = as_name
        out.append(c)
        for i, k in enumerate(kids):
            collect(k, out, ox + x, oy + y, "%s_%d" % (as_name, i), as_name)
        return

    st_col, st_w = stroke_of(cmd)
    if cmd.get("type") == 2 or cmd.get("paths"):
        paths = cmd.get("paths") or []
        d = svg_path(paths[0], w, h) if paths else None
        if d:
            p = {"x": x, "y": y, "path": d, "name": name, "parent": {"$ref": parent_ref}}
            if fill_of(cmd):
                p["props"] = {"fill": fill_of(cmd)}
            else:
                p["props"] = {"fill": "none"}
            out.append({"command": "vector.create", "params": p})
            return

    has_bg = fill_of(cmd) is not None or st_col is not None
    if has_bg:
        corners = cmd.get("corners") or []
        cr = None
        if corners:
            uniq = set(round(v, 2) for v in corners)
            cr = round(corners[0], 2) if len(uniq) == 1 else [round(v, 2) for v in corners]
        props = {}
        f = fill_of(cmd)
        props["fill"] = f if f else "none"
        if cr:
            props["cornerRadius"] = cr
        if st_col:
            props["stroke"] = st_col
            props["strokeWeight"] = st_w
            props["strokeAlign"] = "inside"
        out.append({"command": "node.create", "params": {"type": "rectangle", "x": x, "y": y, "width": w, "height": h,
                                                         "name": name, "parent": {"$ref": parent_ref}, "props": props}})

    if body:
        para, inl = first
        fs = inl.get("size") or 13
        props = {
            "fontFamily": inl.get("family") or "Arial",
            "fontSize": round(fs, 2),
            "fontStyle": "Bold" if (inl.get("weight") or 400) >= 600 else "Regular",
            "fill": hx(inl.get("textColor")) or "#202020",
            "lineHeight": round(para.get("lineSpacing") or fs * 1.2, 2),
            "textAlign": {0: "left", 1: "center", 2: "right", 3: "justified"}.get(para.get("horizontalAlignment"), "left"),
            "textAutoResize": "none",
            "textAlignVertical": "top",
        }
        out.append({"command": "node.create", "params": {"type": "text", "x": x, "y": y, "width": w, "height": h,
                                                         "name": (body[:20] or name),
                                                         "parent": {"$ref": parent_ref}, "text": body, "props": props}})


def build_commands(txt):
    """把 axvg 文本解析成 FigCraft 命令列表（等价原 main() 的解析部分，不落盘）。"""
    lines = txt.replace("\r\n", "\n").split("\n", 1)
    if lines[0].strip().lstrip("\ufeff") != AXVG_HEADER:
        raise ValueError("剪贴板里不是 Axure Cloud 的复制内容（首行应为 %s）" % AXVG_HEADER)
    if len(lines) < 2 or not lines[1].strip():
        raise ValueError("剪贴板内容不完整，缺少 JSON 数据")
    pay = json.loads(lines[1])
    items = pay["scene"]["items"]
    cmds = []
    if len(items) == 1 and ((items[0].get("scene") or {}).get("items")):
        root = items[0]
        r = root["rect"]
        ox, oy = r["location"]["x"], r["location"]["y"]
        sz = r["size"]
        w, h = sz["width"], sz["height"]
        roots, root_name = [root], (root.get("name") or "Axure 页面")
        kids = root["scene"]["items"]
    else:
        roots = []
        xs, ys, x2, y2 = [], [], [], []
        for it in items:
            r = it.get("rect") or {}
            loc, sz = r.get("location") or {}, r.get("size") or {}
            xs.append(loc.get("x", 0)); ys.append(loc.get("y", 0))
            x2.append(loc.get("x", 0) + sz.get("width", 0)); y2.append(loc.get("y", 0) + sz.get("height", 0))
        ox, oy = min(xs), min(ys)
        w, h = max(x2) - ox, max(y2) - oy
        roots, root_name, kids = [], "Axure 导入 (%d 个元素)" % len(items), items

    cmds.append({"command": "frame.create", "as": "root",
                 "params": {"x": 0, "y": 0, "width": round(w, 2), "height": round(h, 2),
                            "name": root_name, "props": {"fill": "none"}}})
    tmp = []
    for i, k in enumerate(kids):
        collect(k, tmp, ox, oy, "n%d" % i, "root")
    for c in tmp:
        s2 = json.dumps(c, ensure_ascii=False).replace('"ROOTREF"', '"root"')
        cmds.append(json.loads(s2))
    return cmds


# =====================================================================
# 二、剪贴板读取（只读 CF_UNICODETEXT）
# =====================================================================
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


# =====================================================================
# 三、FigCraft control channel
# =====================================================================
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


# =====================================================================
# 四、转换：axvg 文本 -> 命令脚本 -> 执行
# =====================================================================
def axvg_to_commands(text):
    # 宽容处理：Axure 不同版本在首行 // axvg 之后可能带若干空行，这里只校验"首行是标记"
    # 且"标记之后存在 JSON 内容"，真正的解析仍交给 build_commands（与原脚本一致）。
    norm = text.replace("\r\n", "\n")
    lines = norm.split("\n")
    if not lines or lines[0].strip().lstrip("\ufeff") != AXVG_HEADER:
        raise ValueError("剪贴板里不是 Axure Cloud 的复制内容（首行应为 %s）" % AXVG_HEADER)
    if not "\n".join(lines[1:]).strip():
        raise ValueError("剪贴板内容不完整，缺少 JSON 数据")

    os.makedirs(WORK_DIR, exist_ok=True)
    tag = uuid.uuid4().hex[:8]
    src = os.path.join(WORK_DIR, "clip_%s.txt" % tag)
    out_path = os.path.join(WORK_DIR, "script_%s.json" % tag)
    with open(src, "w", encoding="utf-8") as fp:
        fp.write(text)

    cmds = build_commands(text)
    if not cmds:
        raise ValueError("转换结果为空，可能选区内没有可转换元件")
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(cmds, fp, ensure_ascii=False, indent=1)
    return cmds


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
        "file": os.path.join(WORK_DIR, "last_axvg.txt"),
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
