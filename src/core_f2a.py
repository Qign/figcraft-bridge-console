# -*- coding: utf-8 -*-
"""
core_f2a —— FigCraft -> Axure 转换核心

来源：D:\\AI\\FigCraft\\axure桥\\figcraft_axure_bridge.py
处理方式：转换逻辑（Converter / 几何 / 模板 / 剪贴板 / control 通道）整体搬迁，逻辑零改动。
仅剥离外壳：日志改为可注入回调、输出目录改为运行时配置、删除 hotkey / flag / 单实例 / main。

对外入口（保持不变）：
    convert_selection(port=47900, depth=30, do_copy=True, verbose=False) -> info dict，失败抛异常
"""
import ctypes
import json
import os
import socket
import time
import uuid

# ---------------- 运行时配置（由 app.py 注入） ----------------
WORK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_work")
_LOGGER = None
_TPL_PATHS = None


def configure(work_dir=None, logger=None, template_paths=None):
    """注入输出目录与日志回调。transform 逻辑不依赖这里，仅影响落盘位置与记录。"""
    global WORK_DIR, _LOGGER, _TPL_PATHS
    if work_dir:
        WORK_DIR = work_dir
    if logger is not None:
        _LOGGER = logger
    if template_paths:
        _TPL_PATHS = template_paths


def log(msg):
    if _LOGGER:
        try:
            _LOGGER(msg)
            return
        except Exception:
            pass


def _tpl_candidates():
    if _TPL_PATHS:
        return list(_TPL_PATHS)
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    return [
        os.path.join(here, "assets", "axvg_tpl.json"),
        os.path.join(here, "axvg_tpl.json"),
        os.path.join(parent, "axvg_tpl.json"),
        os.path.join(parent, "assets", "axvg_tpl.json"),
        os.path.join(here, "..", "..", "axure桥", "axvg_tpl.json"),
    ]


DEFAULT_PORT = 47900

K_CORNER = 0.5523
IDENT = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
DEFAULT_STROKE = {"fill": {"color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 0.0}, "type": 1, "enabled": True},
                  "alignment": 0}


# ---------------- 模板与基础几何 ----------------
def load_templates():
    for p in _tpl_candidates():
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as fp:
                return json.load(fp)
    raise RuntimeError("找不到 axvg_tpl.json（应放在 src\\assets\\ 下）")


def mul(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return [a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1]


def mat(t):
    return list(t) if t else list(IDENT)


def color(c, alpha=None):
    return {"r": float(c.get("r", 0)), "g": float(c.get("g", 0)), "b": float(c.get("b", 0)),
            "a": float(c.get("a", 1) if alpha is None else alpha)}


def solid_fill(fills):
    for f in fills or []:
        if f.get("visible", True) and f.get("type") == "solid":
            c = dict(f.get("color") or {})
            c["a"] = float(c.get("a", 1)) * float(f.get("opacity", 1) or 1)
            return {"color": color(c), "type": 1, "enabled": True}
    return {"color": color({"r": 1, "g": 1, "b": 1, "a": 0.0}), "type": 1, "enabled": True}


def rrect_points(w, h, radii):
    radii = list(radii or [0, 0, 0, 0])
    while len(radii) < 4:
        radii.append(0)
    rx = min(max(radii[0], radii[1]), w / 2) / w if w else 0
    ry = min(max(radii[0], radii[3]), h / 2) / h if h else 0
    if rx <= 0 or ry <= 0:
        pts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        return [{"to": {"x": p[0], "y": p[1]}, "lowerHandle": None, "higherHandle": None, "type": 3} for p in pts]
    kx, ky = K_CORNER * rx, K_CORNER * ry
    P = lambda x, y: {"x": round(x, 5), "y": round(y, 5)}
    spec = [
        (P(rx, 0), None, None),
        (P(1 - rx, 0), P(1 - rx + kx, 0), None),
        (P(1, ry), None, P(1, ry - ky)),
        (P(1, 1 - ry), P(1, 1 - ry + ky), None),
        (P(1 - rx, 1), None, P(1 - rx + kx, 1)),
        (P(rx, 1), P(rx - kx, 1), None),
        (P(0, 1 - ry), None, P(0, 1 - ry + ky)),
        (P(0, ry), P(0, ry - ky), None),
    ]
    data = [{"to": to, "lowerHandle": lo, "higherHandle": hi, "type": 3} for to, hi, lo in spec]
    data[0]["lowerHandle"] = P(rx - kx, 0)
    return data


def ellipse_points(w, h):
    k = K_CORNER
    P = lambda x, y: {"x": round(x, 5), "y": round(y, 5)}
    data = [
        {"to": P(0.5, 0.0), "higherHandle": None, "lowerHandle": None, "type": 3},
        {"to": P(1.0, 0.5), "higherHandle": P(0.5 + k / 2, 0.0), "lowerHandle": P(1.0, 0.5 - k / 2), "type": 3},
        {"to": P(0.5, 1.0), "higherHandle": P(1.0, 0.5 + k / 2), "lowerHandle": P(0.5 + k / 2, 1.0), "type": 3},
        {"to": P(0.0, 0.5), "higherHandle": P(0.5 - k / 2, 1.0), "lowerHandle": P(0.0, 0.5 + k / 2), "type": 3},
        {"to": P(0.5, 0.0), "higherHandle": P(0.0, 0.5 - k / 2), "lowerHandle": P(0.5 - k / 2, 0.0), "type": 3},
    ]
    return data


# ---------------- 转换器（沿用已验证的 axvg 生成逻辑） ----------------
def base_item(tpl, node, absm, w, h):
    it = {k: json.loads(json.dumps(v)) for k, v in tpl.items() if k not in ("scene", "text")}
    it.update({
        "rect": {"location": {"x": round(absm[4], 2), "y": round(absm[5], 2)},
                 "size": {"width": round(w, 2), "height": round(h, 2)}},
        "rotation": 0.0,
        "visible": node.get("visible", True) is not False,
        "id": str(uuid.uuid4()),
        "name": node.get("name") or "图层",
    })
    return it


def build_text(characters, st, fill_color, align_h, ls_map):
    fs = float(st.get("font_size") or 13)
    ls = ls_map.get(fs) or round(fs * 0.75, 2)
    bold = "bold" in str(st.get("font_style", "")).lower()
    paras = []
    for seg in (characters or "").split("\n"):
        inline = {
            "text": seg,
            "textColor": fill_color,
            "highlight": {"r": 0.0, "g": 0.0, "b": 0.0, "a": 0.0},
            "size": fs,
            "family": st.get("font_family") or "Microsoft YaHei",
            "typeface": None,
            "underline": "underline" in str(st.get("font_style", "")).lower(),
            "strikethrough": "strikethrough" in str(st.get("font_style", "")).lower(),
            "superscript": 0, "baselineOffset": 0.0, "characterSpacing": 0.0,
            "transform": 0, "weight": 700 if bold else 400, "style": 0, "stretch": 5, "type": 0,
        }
        paras.append({"inlines": [inline], "horizontalAlignment": align_h, "lineSpacing": ls,
                      "textListInfo": {"indentLevel": 0, "listChar": None, "listType": 0}})
    return {"paragraphs": paras}


class Converter(object):
    """输入为已适配的节点字典（结构同 .figcraft 文件 nodes，坐标为绝对坐标减 origin）。"""

    def __init__(self, nodes, tpl):
        self.tpl = tpl
        self.grp_tpl = tpl["grp"]
        self.txt_tpl = tpl["txt"]
        self.shp_tpl = tpl["shp"]
        self.empty_text = json.loads(json.dumps(self.txt_tpl["text"]))
        for p in self.empty_text["paragraphs"]:
            for il in p["inlines"]:
                il["text"] = ""
        self.nodes = nodes
        self.ls_map = {}
        self.warnings = []

    # --- 图元 ---
    def conv_text(self, node, absm):
        w, h = node.get("width", 0), node.get("height", 0)
        it = base_item(self.txt_tpl, node, absm, w, h)
        st = node.get("style") or {}
        fill = solid_fill(node.get("fills"))
        tc = fill["color"] if fill["color"]["a"] > 0 else {"r": 0.2, "g": 0.2, "b": 0.2, "a": 1.0}
        al = node.get("align_h")
        ha = 1 if al == "center" else (2 if al == "right" else 0)
        it.update({
            "corners": [], "border": [], "booleanOperation": 0, "type": 0,
            "opacity": float(node.get("opacity", 1) or 1),
            "backgroundFills": [{"color": {"r": 1.0, "g": 1.0, "b": 1.0, "a": 0.0}, "type": 1, "enabled": True}],
            "strokes": [json.loads(json.dumps(DEFAULT_STROKE))],
            "strokePattern": [], "strokeThickness": 0.0,
            "text": build_text(node.get("characters"), st, tc, ha, self.ls_map),
            "textAlignment": ha, "textPadding": [0.0, 0.0, 0.0, 0.0],
            "textRotation": 0.0, "meta": None,
            "effects": json.loads(json.dumps(self.shp_tpl.get("effects") or [])),
            "textShadows": json.loads(json.dumps(self.shp_tpl.get("textShadows") or [])),
        })
        return it

    def conv_native(self, node, absm):
        """原生元件：矩形/圆角矩形/椭圆 → Axure Box 元件（type:0 + corners）。

        与矢量（type:2 + paths）的区别：圆角是元件属性而非烘焙路径，
        在 Axure 里可继续改圆角数值，拉伸时也不会变形。
        """
        w, h = node.get("width", 0), node.get("height", 0)
        it = base_item(self.shp_tpl, node, absm, w, h)
        stroke = solid_fill(node.get("strokes"))
        sdef = node.get("stroke") if isinstance(node.get("stroke"), dict) else {}
        thick = float(sdef.get("weight") or 0)
        if thick == 0 and node.get("strokes"):
            thick = 1.0
        if str(node.get("type")) == "ellipse":
            corners = [999, 999, 999, 999]
        else:
            cards = [float(c or 0) for c in ((node.get("corners") or {}).get("radii") or [0, 0, 0, 0])]
            while len(cards) < 4:
                cards.append(0.0)
            lim = (min(w, h) / 2.0) if (w and h) else 0.0
            corners = [round(min(max(c, 0.0), lim), 2) for c in cards[:4]]
        for k in ("paths", "svgPaths"):
            it.pop(k, None)
        it.update({
            "booleanOperation": 0, "type": 0,
            "opacity": float(node.get("opacity", 1) or 1),
            "backgroundFills": [solid_fill(node.get("fills"))],
            "strokes": [{"fill": stroke, "alignment": 0}] if thick > 0 else [],
            "strokePattern": [],
            "strokeThickness": thick if thick > 0 else 0.0,
            "corners": corners,
            "border": [thick, thick, thick, thick] if thick > 0 else [0.0, 0.0, 0.0, 0.0],
            "isNameDynamic": False,
            "text": json.loads(json.dumps(self.empty_text)),
            "textAlignment": 0, "textPadding": [0.0, 0.0, 0.0, 0.0],
            "textRotation": 0.0, "meta": None,
            "effects": json.loads(json.dumps(self.shp_tpl.get("effects") or [])),
            "textShadows": json.loads(json.dumps(self.shp_tpl.get("textShadows") or [])),
        })
        return it

    def conv_shape(self, node, absm):
        w, h = node.get("width", 0), node.get("height", 0)
        it = base_item(self.shp_tpl, node, absm, w, h)
        stroke = solid_fill(node.get("strokes"))
        sdef = node.get("stroke") if isinstance(node.get("stroke"), dict) else {}
        thick = float(sdef.get("weight") or 0)
        if thick == 0 and node.get("strokes"):
            thick = 1.0
        radii = (node.get("corners") or {}).get("radii") or [0, 0, 0, 0]
        it.update({
            "booleanOperation": 0, "type": 2,
            "opacity": float(node.get("opacity", 1) or 1),
            "backgroundFills": [solid_fill(node.get("fills"))],
            "strokes": [{"fill": stroke, "alignment": 0}],
            "strokePattern": [], "strokeThickness": thick,
            "paths": [{"startDecoration": 1, "endDecoration": 1, "closed": True,
                       "data": rrect_points(w, h, radii)}],
            "svgPaths": None,
            "text": json.loads(json.dumps(self.empty_text)),
            "textAlignment": 0, "textPadding": [0.0, 0.0, 0.0, 0.0],
            "textRotation": 0.0, "meta": None,
            "effects": json.loads(json.dumps(self.shp_tpl.get("effects") or [])),
            "textShadows": json.loads(json.dumps(self.shp_tpl.get("textShadows") or [])),
        })
        if str(node.get("type")) == "ellipse":
            it["paths"][0]["data"] = ellipse_points(w, h)
        return it

    def conv_group(self, node, absm):
        w, h = node.get("width", 0), node.get("height", 0)
        it = base_item(self.grp_tpl, node, absm, w, h)
        it.update({
            "clip": None,
            "effects": [],
            "itemType": 0,
            "rotation": 0.0,
            "scene": {"items": [self.conv_child(c, absm) for c in (node.get("children") or [])
                                if str(c) in self.nodes]},
        })
        it["scene"]["items"] = [x for x in it["scene"]["items"] if x]
        return it

    def conv_child(self, nid, parent_abs):
        # 适配阶段已把每个节点的 transform 写成自身绝对坐标，父矩阵不参与累乘
        node = self.nodes.get(str(nid))
        if not node:
            return None
        absm = mat(node.get("transform"))
        t = node.get("type")
        if t in ("frame", "group", "section", "component", "instance"):
            return self.conv_group(node, absm)
        if t == "text":
            return self.conv_text(node, absm)
        if t == "rectangle":
            return self.conv_native(node, absm)
        if t in ("ellipse", "vector", "line", "polygon", "star"):
            # 实测：原生 Box 的 corners 上限是 min(w,h)/2。正圆用 corners=999 完美；
            # 宽高不等的真椭圆走原生会退化成胶囊/圆角矩形，故仅正圆走原生元件，其余保持矢量。
            if t == "ellipse" and abs(float(node.get("width") or 0) - float(node.get("height") or 0)) <= 1.0:
                return self.conv_native(node, absm)
            if t not in ("vector", "ellipse"):
                self.warnings.append("图元类型 %s 按矢量近似: %s" % (t, node.get("name")))
            return self.conv_shape(node, absm)
        if t == "image":
            self.warnings.append("图片图元暂不支持，已跳过: %s" % (node.get("name")))
            return None
        self.warnings.append("未知图元 %s 按矩形近似: %s" % (t, node.get("name")))
        return self.conv_shape(node, absm)

    def convert(self, root_id):
        node = self.nodes.get(str(root_id))
        if not node:
            raise RuntimeError("找不到图层: %s" % root_id)
        self.warnings = []
        if node.get("type") in ("frame", "group", "section", "component", "instance"):
            root = self.conv_group(node, list(IDENT))
        else:
            root = self.conv_child(root_id, list(IDENT))
        return {"scene": {"items": [root] if root else []}, "masters": None, "imageMap": None}

    def stats(self, payload):
        cnt = {"组": 0, "文本": 0, "形状": 0, "原生元件": 0}

        def walk(items):
            for it in items:
                if it.get("itemType") == 0:
                    cnt["组"] += 1
                elif it.get("type") == 2:
                    cnt["形状"] += 1
                elif it.get("corners"):
                    cnt["原生元件"] += 1
                else:
                    cnt["文本"] += 1
                if it.get("scene"):
                    walk(it["scene"]["items"])

        walk(payload["scene"]["items"])
        return cnt


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


# ---------------- inspect 树 -> 转换器输入 ----------------
def hex_to_rgba(s, alpha=1.0):
    if not s:
        return {"r": 0.0, "g": 0.0, "b": 0.0, "a": alpha}
    h = str(s).lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        a = int(h[6:8], 16) / 255.0 if len(h) >= 8 else 1.0
    except ValueError:
        return {"r": 0.0, "g": 0.0, "b": 0.0, "a": alpha}
    return {"r": r, "g": g, "b": b, "a": a * alpha}


def paint_list(items):
    out = []
    for p in items or []:
        if not isinstance(p, dict):
            continue
        if p.get("type") != "solid" or p.get("visible") is False:
            continue
        out.append({"type": "solid",
                    "color": hex_to_rgba(p.get("color"), float(p.get("opacity", 1) or 1)),
                    "opacity": 1, "visible": True})
    return out


def radii_of(cr):
    if isinstance(cr, (int, float)):
        v = float(cr)
        return [v, v, v, v]
    if isinstance(cr, list):
        v = [float(x or 0) for x in cr][:4]
        while len(v) < 4:
            v.append(v[0] if v else 0.0)
        return v
    if isinstance(cr, dict):
        return radii_of(cr.get("radii") or [0, 0, 0, 0])
    return [0.0, 0.0, 0.0, 0.0]


def adapt_tree(nodes, ox, oy, out=None, parent=None):
    out = {} if out is None else out
    for node in nodes or []:
        ab = node.get("absoluteBounds") or {}
        try:
            ax = float(ab.get("x", node.get("x", 0)) or 0)
            ay = float(ab.get("y", node.get("y", 0)) or 0)
        except (TypeError, ValueError):
            ax = ay = 0.0
        t = str(node.get("type", "")).lower()
        rec = {
            "id": node.get("id"),
            "type": t,
            "name": node.get("name"),
            "parent": parent,
            "transform": [1.0, 0.0, 0.0, 1.0, ax - ox, ay - oy],
            "width": float(node.get("width", ab.get("width", 0)) or 0),
            "height": float(node.get("height", ab.get("height", 0)) or 0),
            "visible": node.get("visible", True) is not False,
            "opacity": float(node.get("opacity", 1) or 1),
            "fills": paint_list(node.get("fills")),
            "strokes": paint_list(node.get("strokes")),
            "stroke": {"weight": float(node.get("strokeWeight") or 0)},
            "corners": {"radii": radii_of(node.get("cornerRadius"))},
            "characters": node.get("characters"),
            "align_h": str(node.get("textAlign") or "left").lower(),
            "style": {
                "font_size": node.get("fontSize"),
                "font_family": node.get("fontFamily"),
                "font_style": node.get("fontStyle"),
            },
            "children": [],
        }
        out[str(rec["id"])] = rec
        kids = node.get("children") or []
        for c in kids:
            rec["children"].append(str(c.get("id")))
        adapt_tree(kids, ox, oy, out, rec["id"])
    return out


def index_selection(tree):
    idx = {}

    def walk(nodes, chain):
        for n in nodes or []:
            idx[n.get("id")] = (n, chain)
            walk(n.get("children") or [], chain + [n])

    walk(tree, [])
    return idx


# ---------------- 输出与剪贴板 ----------------
def serialize(payload):
    return "// axvg\r\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def write_payload(text, name):
    try:
        os.makedirs(WORK_DIR, exist_ok=True)
    except Exception:
        pass
    path = os.path.join(WORK_DIR, name)
    with open(path, "w", encoding="utf-8", newline="") as fp:
        fp.write(text)
    return path


def copy_to_clipboard(text):
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    k32 = ctypes.windll.kernel32
    u32 = ctypes.windll.user32
    k32.GlobalAlloc.restype = ctypes.c_void_p
    k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k32.GlobalLock.restype = ctypes.c_void_p
    k32.GlobalLock.argtypes = [ctypes.c_void_p]
    k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    u32.SetClipboardData.restype = ctypes.c_void_p
    u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

    data = text.encode("utf-16-le") + b"\x00\x00"
    for _ in range(6):
        if u32.OpenClipboard(None):
            break
        time.sleep(0.08)
    else:
        raise RuntimeError("剪贴板被其他程序占用")
    try:
        if not u32.EmptyClipboard():
            raise RuntimeError("清空剪贴板失败")
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            raise RuntimeError("分配剪贴板内存失败")
        p = k32.GlobalLock(h)
        if not p:
            raise RuntimeError("锁定剪贴板内存失败")
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        if not u32.SetClipboardData(CF_UNICODETEXT, h):
            raise RuntimeError("写入剪贴板失败")
    finally:
        u32.CloseClipboard()


# ---------------- 主流程 ----------------
def pick_targets(doc):
    """从 inspect 结果里决定要转换哪个画板，返回 (选中节点列表, 说明)。"""
    sel = [s for s in (doc.get("selection") or [])]
    if not sel:
        return [], "未选中"
    pages = doc.get("pages") or []
    # 旧版只索引 pages[0]，导致在 Page 2/3 里选中任何东西都会被判成"没内容"
    idx = {}
    for pg in pages:
        idx.update(index_selection(pg.get("children") or []))
    picked, seen = [], set()
    for sid in sel:
        if sid not in idx:
            continue
        node, chain = idx[sid]
        if str(node.get("type")).upper() != "FRAME":
            frames = [c for c in chain if str(c.get("type")).upper() == "FRAME"]
            target = frames[-1] if frames else node
        else:
            target = node
        if target.get("id") in seen:
            continue
        seen.add(target.get("id"))
        picked.append(target)
    return picked, ""


def convert_selection(port=DEFAULT_PORT, depth=30, do_copy=True, verbose=False):
    ctl = Control(port)
    try:
        r = ctl.request("document.inspect", {"depth": depth})
    finally:
        ctl.close()
    if not r.get("ok"):
        raise RuntimeError("读取 FigCraft 文档失败：%s" % r.get("error"))
    doc = r.get("result") or {}
    targets, why = pick_targets(doc)
    if not targets:
        raise RuntimeError("请先在 FigCraft 里选中一个画板（或图层）")

    # origin：单目标取自身左上，多目标取包围盒左上
    boxes = []
    for t in targets:
        ab = t.get("absoluteBounds") or {}
        boxes.append((float(ab.get("x", 0) or 0), float(ab.get("y", 0) or 0),
                      float(ab.get("width", t.get("width", 0)) or 0),
                      float(ab.get("height", t.get("height", 0)) or 0)))
    if len(targets) == 1:
        ox, oy = boxes[0][0], boxes[0][1]
    else:
        ox = min(b[0] for b in boxes)
        oy = min(b[1] for b in boxes)

    nodes = adapt_tree(targets, ox, oy)
    if len(targets) == 1:
        root_id = str(targets[0].get("id"))
        title = targets[0].get("name") or "画板"
    else:
        x2 = max(b[0] + b[2] for b in boxes)
        y2 = max(b[1] + b[3] for b in boxes)
        root_id = "__multi__"
        nodes[root_id] = {
            "id": root_id, "type": "frame", "name": "多选合并", "parent": None,
            "transform": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            "width": x2 - ox, "height": y2 - oy, "visible": True, "opacity": 1.0,
            "fills": [], "strokes": [], "stroke": {"weight": 0},
            "corners": {"radii": [0, 0, 0, 0]}, "characters": None, "align_h": "left",
            "style": {}, "children": [str(t.get("id")) for t in targets],
        }
        title = "多选合并"

    conv = Converter(nodes, load_templates())
    payload = conv.convert(root_id)
    cnt = conv.stats(payload)
    text = serialize(payload)
    doc_name = os.path.splitext(os.path.basename(doc.get("path") or "figcraft"))[0]
    path = write_payload(text, "%s_%s.txt" % (doc_name, str(root_id)))
    if do_copy:
        copy_to_clipboard(text)
    info = {"title": title, "groups": cnt["组"], "texts": cnt["文本"], "shapes": cnt["形状"],
            "natives": cnt["原生元件"],
            "kb": round(len(text.encode("utf-8")) / 1024.0, 1), "file": path,
            "warnings": conv.warnings[:20], "copied": do_copy}
    if verbose:
        log(json.dumps(info, ensure_ascii=False))
    return info
