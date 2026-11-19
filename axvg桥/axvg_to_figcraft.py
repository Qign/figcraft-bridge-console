# -*- coding: utf-8 -*-
"""axvg (Axure Cloud 复制内容) -> FigCraft 命令脚本"""
import json, os, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\zxqch\Desktop\复制为axure cloud.txt"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_NAME = sys.argv[2] if len(sys.argv) > 2 else "axure_import_script.json"


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


def main():
    txt = open(SRC, encoding="utf-8-sig").read()
    lines = txt.split("\n", 1)
    assert lines[0].strip() == "// axvg"
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

    p = os.path.join(OUT_DIR, OUT_NAME)
    json.dump(cmds, open(p.replace("axure_import_script.json", OUT_NAME), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    stat = {}
    for c in cmds:
        stat[c["command"]] = stat.get(c["command"], 0) + 1
    print("命令数:", len(cmds), stat)
    print("脚本:", p)


if __name__ == "__main__":
    main()
