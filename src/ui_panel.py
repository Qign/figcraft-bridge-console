# -*- coding: utf-8 -*-
"""
ui_panel —— 760x524 控制面板（Tkinter Canvas 绘制，无第三方依赖）

设计依据：D:\\AI\\FigCraft\\面板设计\\桥控制面板_v1.png + 界面设计说明_v1.md
布局（逻辑像素，S 为 DPI 缩放）：
    0..64    标题栏（白）：logo + 标题/副标题 + 设置 + 关闭
    64..112  环境状态条（白）：状态点 + 端口/进程/热键 + 重新检测
    124..250 卡片1 FigCraft -> Axure
    256..382 卡片2 Axure -> FigCraft
    392..428 底部操作行：全部启用 / 全部停用 / 查看日志 / 开机自启
    440      最近一次动作提示
    478      底部说明
"""
import math
import os
import tkinter as tk
import tkinter.font as tkfont

W, H = 760, 524

C_BG = "#F5F6F8"
C_WHITE = "#FFFFFF"
C_LINE = "#E5E8EC"
C_TEXT = "#1D2129"
C_SUB = "#4E5969"
C_MUTED = "#86909C"
C_PRIMARY = "#0052D9"
C_PRIMARY_HOVER = "#1F62D9"
C_BTN_BG = "#F2F3F5"
C_BTN_HOVER = "#E6E9EE"
C_GHOST_LINE = "#DCDEE3"
C_GREEN = "#00A870"
C_ORANGE = "#ED7B2F"
C_GRAY = "#9EA6B0"
C_DISABLED = "#C9CDD4"
C_MAGIC = "#FF00FE"          # 圆角外的透明色

FAMILY = "Microsoft YaHei UI"

STATE_TEXT = {"running": "运行中", "paused": "已暂停", "disabled": "已停用"}
STATE_COLOR = {"running": (C_GREEN, "#E8F8F2"), "paused": ("#0E9F9F", "#E4F6F6"),
               "disabled": (C_MUTED, "#F2F3F5"), "down": (C_ORANGE, "#FEF0E6")}


class Panel(tk.Tk):
    def __init__(self, state, hooks):
        tk.Tk.__init__(self)
        self.st = state                 # 由 app 维护的共享状态 dict
        self.hooks = hooks              # 回调集合
        self.S = float(state.get("scale") or 1.0)
        self.hit = {}
        self.hover = None
        self._drag = None
        self._fonts = {}

        self.overrideredirect(True)
        self.title("FigCraft 双向桥控制台")
        self.configure(bg=C_MAGIC)
        try:
            self.attributes("-transparentcolor", C_MAGIC)
        except tk.TclError:
            self.configure(bg=C_BG)

        ico = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "app.ico")
        if os.path.isfile(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass

        self.canvas = tk.Canvas(self, width=self.px(W), height=self.px(H),
                                bg=C_MAGIC, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda e: self._set_hover(None))
        self.bind("<Escape>", lambda e: self.hooks.get("close", lambda: None)())
        self.protocol("WM_DELETE_WINDOW", lambda: self.hooks.get("close", lambda: None)())

        self.place_window()
        self.render()

    # ---------------- 单位与基础图元 ----------------
    def px(self, v):
        return int(round(v * self.S))

    def _font(self, size, bold=False):
        key = (size, bold)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(family=FAMILY, size=-self.px(size),
                                           weight=("bold" if bold else "normal"))
        return self._fonts[key]

    def measure(self, text, size, bold=False):
        return self._font(size, bold).measure(text) / self.S

    def rr(self, x0, y0, x1, y1, r, fill, outline=None, width=1):
        pts = []
        seg = 6
        for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0),
                           (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
            for i in range(seg + 1):
                a = math.radians(a0 + 90.0 * i / seg)
                pts.append((self.px(cx + r * math.cos(a)), self.px(cy + r * math.sin(a))))
        flat = [c for p in pts for c in p]
        kw = {"fill": fill, "outline": outline or fill}
        if outline:
            kw["width"] = max(1, self.px(width))
        self.canvas.create_polygon(flat, **kw)

    def txt(self, x, y, s, size=13, color=C_TEXT, anchor="w", bold=False):
        return self.canvas.create_text(self.px(x), self.px(y), text=s, fill=color, anchor=anchor,
                                       font=self._font(size, bold))

    def dot(self, cx, cy, r, color):
        self.canvas.create_oval(self.px(cx - r), self.px(cy - r), self.px(cx + r), self.px(cy + r),
                                fill=color, outline=color)

    def hline(self, x0, x1, y, color=C_LINE):
        self.canvas.create_line(self.px(x0), self.px(y), self.px(x1), self.px(y), fill=color)

    # ---------------- 窗口位置 ----------------
    def place_window(self):
        pos = self.st.get("window_pos") or {}
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w, h = self.px(W), self.px(H)
        x = int(pos.get("x", sw - w - self.px(24)))
        y = int(pos.get("y", sh // 2 - h // 2))
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h - self.px(8)))
        self.geometry("%dx%d+%d+%d" % (w, h, x, y))

    # ---------------- 绘制 ----------------
    def render(self):
        cv = self.canvas
        cv.delete("all")
        self.hit = {}
        st = self.st

        # 底板
        self.rr(0, 0, W, H, 12, C_BG)
        self.rr(0, 0, W, 112, 12, C_WHITE)
        cv.create_rectangle(self.px(0), self.px(100), self.px(W), self.px(112), fill=C_WHITE, outline=C_WHITE)
        self.hline(0, W, 112)

        # ---- 标题栏 ----
        self._logo(28, 12, 36)
        self.txt(76, 21, st.get("app_title") or "转换桥控制面板", 16, C_TEXT, bold=True)
        self.txt(76, 42, "FigCraft ↔ Axure RP 11 双向转换 · v%s" % st.get("version", "1.0"), 11, C_MUTED)

        self._button("settings", W - 40 - 60, 18, 60, 28, "设置", "ghost", 12)
        self._icon_close(W - 34, 18)

        # ---- 环境状态条 ----
        alive = st.get("port_alive")
        fc = st.get("fc_running")
        hk = st.get("hotkey_state") or {}
        col = C_GREEN if alive else C_ORANGE
        self.dot(40, 88, 4, col)
        parts = ["FigCraft 控制端口 %d · %s" % (st.get("port", 47900), "已连接" if alive else "未连接")]
        parts.append("FigCraft 已运行" if fc else "FigCraft 未运行")
        if any(v is False for v in hk.values()):
            parts.append("热键冲突")
        elif hk and all(v is None for v in hk.values()):
            parts.append("热键已停用")
        elif hk:
            parts.append("热键正常")
        self.txt(52, 88, " · ".join(parts), 13, C_SUB)
        self._button("retry", W - 40 - 80, 76, 80, 28, "重新检测", "ghost", 12)

        # ---- 两张卡片 ----
        self._card("to_axure", 124, "FigCraft → Axure 桥",
                   "在 FigCraft 选中画板 → 按转换热键 → 切到 Axure 画布 Ctrl+V",
                   st.get("hotkeys", {}).get("to_axure", "Ctrl+Alt+C"))
        self._card("to_figcraft", 256, "Axure → FigCraft 桥",
                   "在 Axure 复制元件 → 按转换热键 → 直接落入当前 FigCraft 文件",
                   st.get("hotkeys", {}).get("to_figcraft", "Ctrl+Alt+V"))

        # ---- 底部操作行 ----
        y = 392
        self._button("all_on", 24, y, 96, 36, "全部启用", "primary", 13)
        self._button("all_off", 132, y, 96, 36,
                     "全部停用", "secondary", 13,
                     enabled=any(st.get("bridges", {}).get(k) != "disabled" for k in ("to_axure", "to_figcraft")))
        self._button("log", 240, y, 96, 36, "查看日志", "secondary", 13)

        # 开机自启
        label_w = self.measure("开机自启", 12)
        sx1 = W - 40
        sx0 = sx1 - 40
        self.txt(sx0 - 10, y + 18, "开机自启", 12, C_SUB, anchor="e")
        self._switch(sx0, y + 6, 40, 24, bool(st.get("autostart")))
        self.hit["autostart"] = (sx0 - label_w - 26, y, sx1, y + 36)

        # ---- 最近动作 ----
        msg = st.get("last_msg") or ""
        if st.get("busy"):
            msg = st.get("busy_msg") or "正在转换…"
        if msg:
            color = st.get("last_level") or C_SUB
            self.txt(24, 446, msg, 12, color)
        else:
            self.txt(24, 446, "就绪：两个热键在任意窗口下均可用", 12, C_MUTED)

        self.txt(W / 2, 486, "桥在后台静默运行，关闭面板不影响热键；日志见 logs 目录",
                 11, C_MUTED, anchor="center")

        cv.create_rectangle(self.px(0), self.px(0), self.px(W) - 1, self.px(H) - 1,
                            outline="#DFE3E8", width=1)

    def _logo(self, x, y, s):
        self.rr(x, y, x + s, y + s, 9, C_PRIMARY)
        cx, cy = x + s / 2, y + s / 2
        for dy, a0, a1 in ((-4.5, 200, 20), (4.5, 20, 200)):
            self.canvas.create_arc(self.px(cx - 10), self.px(cy + dy - 6), self.px(cx + 10), self.px(cy + dy + 6),
                                   start=a0, extent=(a1 - a0) % 360, style="arc", outline=C_WHITE,
                                   width=max(1, self.px(1.8)))

    def _icon_close(self, x, y):
        w = 28
        name = "close"
        hovered = self.hover == name
        if hovered:
            self.rr(x, y, x + w, y + w, 6, "#FDE7E7")
        c = "#E34D59" if hovered else "#8A919F"
        m = 8
        self.canvas.create_line(self.px(x + m), self.px(y + m), self.px(x + w - m), self.px(y + w - m),
                                fill=c, width=max(1, self.px(1.4)))
        self.canvas.create_line(self.px(x + w - m), self.px(y + m), self.px(x + m), self.px(y + w - m),
                                fill=c, width=max(1, self.px(1.4)))
        self.hit[name] = (x - 2, y - 2, x + w + 2, y + w + 2)

    def _button(self, name, x, y, w, h, label, kind="secondary", size=13, enabled=True, radius=6):
        hovered = self.hover == name and enabled
        if kind == "primary":
            bg = C_PRIMARY_HOVER if hovered else C_PRIMARY
            fg = C_WHITE
            outline = None
        elif kind == "ghost":
            bg = "#F2F3F5" if hovered else C_WHITE
            fg = C_PRIMARY
            outline = C_GHOST_LINE
        else:
            bg = C_BTN_HOVER if hovered else C_BTN_BG
            fg = C_TEXT
            outline = None
        if not enabled:
            bg = "#F7F8FA"
            fg = C_DISABLED
            outline = C_GHOST_LINE if kind == "ghost" else None
        self.rr(x, y, x + w, y + h, radius, bg, outline)
        self.txt(x + w / 2, y + h / 2, label, size, fg, anchor="center")
        if enabled:
            self.hit[name] = (x, y, x + w, y + h)

    def _switch(self, x, y, w, h, on):
        r = h / 2.0
        bg = C_PRIMARY if on else "#C9CDD4"
        self.rr(x, y, x + w, y + h, r, bg)
        kx = (x + w - r) if on else (x + r)
        self.canvas.create_oval(self.px(kx - r + 2), self.px(y + 2), self.px(kx + r - 2), self.px(y + h - 2),
                                fill=C_WHITE, outline=C_WHITE)

    def _card(self, bridge, top, title, desc, hotkey):
        st = self.st
        x0, x1 = 24, W - 24
        self.rr(x0, top, x1, top + 126, 12, C_WHITE)
        self.txt(x0 + 20, top + 26, title, 15, C_TEXT, bold=True)

        state = st.get("bridges", {}).get(bridge, "running")
        port_down = not st.get("port_alive")
        key = "down" if (port_down and state != "disabled") else state
        fg, bg = STATE_COLOR.get(key, STATE_COLOR["running"])
        label = "端口未连接" if key == "down" else STATE_TEXT.get(state, "运行中")
        tw = self.measure(label, 12)
        bw = tw + 20
        bx1 = x1 - 20
        self.rr(bx1 - bw, top + 14, bx1, top + 38, 12, bg)
        self.dot(bx1 - bw + 11, top + 26, 3, fg)
        self.txt(bx1 - bw + 18, top + 26, label, 12, fg, anchor="w")

        self.txt(x0 + 20, top + 56, desc, 12.5, C_SUB)

        # 热键行
        hy = top + 84
        self.txt(x0 + 20, hy, "转换热键", 12, C_MUTED, anchor="w")
        kw = max(126, self.measure(hotkey, 12) + 28)
        self.rr(x0 + 84, hy - 14, x0 + 84 + kw, hy + 14, 6, "#F7F8FA", "#E5E8EC")
        self.txt(x0 + 84 + kw / 2, hy, hotkey, 12, C_TEXT, anchor="center")

        # 右侧两块按钮
        bw2, bh2 = 72, 30
        bx = x1 - 20 - bw2
        disable_label = "启用" if state == "disabled" else "停用"
        self._button("%s_disable" % bridge, bx, hy - bh2 / 2, bw2, bh2, disable_label,
                     "secondary" if state != "disabled" else "ghost", 12)
        bx -= bw2 + 8
        pause_label = "恢复" if state == "paused" else "暂停"
        self._button("%s_pause" % bridge, bx, hy - bh2 / 2, bw2, bh2, pause_label, "secondary", 12,
                     enabled=(state != "disabled"))

        # 端口未连接提示行 / 热键冲突提示
        hint = None
        hint_color = C_ORANGE
        if st.get("hotkey_state", {}).get(bridge) is False:
            hint = "热键被其他程序占用，可在设置里改键"
        elif port_down and state != "disabled":
            hint = "端口 %d 未连接，热键暂不可用" % st.get("port", 47900)
        if hint:
            self.txt(x0 + 20, top + 108, hint, 11, hint_color)
        if port_down and state != "disabled":
            self._button("%s_launch" % bridge, x1 - 20 - 118, top + 96, 118, 24,
                         "启动 FigCraft", "ghost", 11)

    # ---------------- 事件 ----------------
    def _logical(self, event):
        return event.x / self.S, event.y / self.S

    def _hit_at(self, x, y):
        for name, (a, b, c, d) in self.hit.items():
            if a <= x <= c and b <= y <= d:
                return name
        return None

    def _set_hover(self, name):
        if name != self.hover:
            self.hover = name
            self.render()

    def _on_motion(self, event):
        x, y = self._logical(event)
        self._set_hover(self._hit_at(x, y))

    def _on_click(self, event):
        x, y = self._logical(event)
        name = self._hit_at(x, y)
        if name:
            self._dispatch(name)
            return
        if y <= 64:
            self._drag = (event.x_root - self.winfo_x(), event.y_root - self.winfo_y())

    def _on_drag(self, event):
        if not self._drag:
            return
        nx = event.x_root - self._drag[0]
        ny = event.y_root - self._drag[1]
        self.geometry("+%d+%d" % (nx, ny))

    def _on_release(self, event):
        if self._drag:
            self._drag = None
            self.st["window_pos"] = {"x": self.winfo_x(), "y": self.winfo_y()}
            if self.hooks.get("moved"):
                self.hooks["moved"](dict(self.st["window_pos"]))

    def _dispatch(self, name):
        h = self.hooks
        if name == "close":
            h.get("close", lambda: None)()
        elif name == "settings":
            h.get("settings", lambda: None)()
        elif name == "retry":
            h.get("retry", lambda: None)()
        elif name == "all_on":
            h.get("all_on", lambda: None)()
        elif name == "all_off":
            h.get("all_off", lambda: None)()
        elif name == "log":
            h.get("open_log", lambda: None)()
        elif name == "autostart":
            h.get("toggle_autostart", lambda: None)()
        elif name.endswith("_pause"):
            h.get("pause", lambda b: None)(name[:-6])
        elif name.endswith("_disable"):
            h.get("disable", lambda b: None)(name[:-8])
        elif name.endswith("_launch"):
            h.get("launch_figcraft", lambda b: None)(name[:-7])

    # ---------------- 对外 ----------------
    def refresh(self, state=None):
        if state is not None:
            self.st = state
        self.render()

    def show_panel(self):
        self.deiconify()
        self.lift()
        # FigCraft 是整屏大窗口，长时间占据前台；用一次"置顶脉冲"确保面板真的浮到它上面
        try:
            self.attributes("-topmost", True)
            self.after(120, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass
        try:
            self.focus_force()
        except tk.TclError:
            pass

    def hide_panel(self):
        self.withdraw()

    def is_visible(self):
        try:
            return self.state() != "withdrawn"
        except tk.TclError:
            return False

    def show_tray_menu(self, items):
        """items: [(label, callback, checked|None)]，checked 为 None 表示普通项"""
        m = tk.Menu(self, tearoff=0, font=self._font(12))
        for label, cb, checked in items:
            if label == "-":
                m.add_separator()
            elif checked is None:
                m.add_command(label=label, command=cb)
            else:
                m.add_checkbutton(label=label, command=cb, onvalue=1, offvalue=0,
                                  variable=tk.IntVar(value=1 if checked else 0))
        try:
            m.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            m.grab_release()

    def toast(self, text, level=C_TEXT, ms=2200):
        try:
            t = tk.Toplevel(self)
            t.overrideredirect(True)
            t.attributes("-topmost", True)
            fr = tk.Frame(t, bg=C_WHITE, highlightbackground="#DFE3E8", highlightthickness=1)
            fr.pack(fill="both", expand=True)
            tk.Label(fr, text=text, bg=C_WHITE, fg=level, font=self._font(12),
                     padx=self.px(16), pady=self.px(10)).pack()
            t.update_idletasks()
            w, h = t.winfo_reqwidth(), t.winfo_reqheight()
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            t.geometry("+%d+%d" % (sw - w - self.px(24), sh - h - self.px(64)))
            t.after(ms, t.destroy)
        except Exception:
            pass
