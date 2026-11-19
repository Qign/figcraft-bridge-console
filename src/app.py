# -*- coding: utf-8 -*-
"""
app —— FigCraft 双向桥控制台 主程序

职责：单实例 + 配置 + 日志 + 状态机 + 托盘 + 面板 + 热键分发。
转换逻辑全部在 core_f2a / core_a2f 里，本文件不碰具体转换细节。

运行：pythonw src\\app.py       （绿色免安装，P1~P4 阶段为脚本版）
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN = bool(getattr(sys, "frozen", False))
APP_ROOT = os.path.dirname(HERE) if not FROZEN else os.path.dirname(sys.executable)
if FROZEN:
    sys.path.insert(0, HERE)

LOG_DIR = os.path.join(APP_ROOT, "logs")
WORK_DIR = os.path.join(LOG_DIR, "work")
CONFIG_PATH = os.path.join(APP_ROOT, "config.json")
ASSETS = os.path.join(HERE, "assets")

# 无控制台打包（--noconsole）时 stdout/stderr 为 None，任何写入都会抛异常，先兜底
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

VERSION = "1.0"
MUTEX_NAME = "Local\\FigCraftBridgeConsole_v1"

DEFAULT_CONFIG = {
    "port": 47900,
    "figcraft_exe": "",
    "depth": 30,
    "hotkeys": {"to_axure": "ctrl+alt+c", "to_figcraft": "ctrl+alt+v"},
    "bridges": {"to_axure": {"enabled": True, "paused": False},
                "to_figcraft": {"enabled": True, "paused": False}},
    "autostart": False,
    "close_to_tray": True,
    "window": {"x": None, "y": None},
}

BRIDGE_NAMES = ("to_axure", "to_figcraft")
BRIDGE_LABEL = {"to_axure": "FigCraft→Axure", "to_figcraft": "Axure→FigCraft"}
HOTKEY_ID = {"to_axure": 1, "to_figcraft": 2}

C_OK = "#00A870"
C_ERR = "#E34D59"
C_WARN = "#ED7B2F"
C_SUB = "#4E5969"

core_f2a = None
core_a2f = None


# =====================================================================
# 日志
# =====================================================================
_log_lock = threading.Lock()


def log(msg, level="INFO"):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, "bridge-%s.log" % datetime.now().strftime("%Y%m%d"))
        try:
            if os.path.getsize(path) > 2 * 1024 * 1024:
                old = path + ".1"
                if os.path.exists(old):
                    os.remove(old)
                os.replace(path, old)
        except OSError:
            pass
        line = "%s [%s] %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), level, msg)
        with _log_lock:
            with open(path, "a", encoding="utf-8") as fp:
                fp.write(line)
    except Exception:
        pass


def current_log_path():
    return os.path.join(LOG_DIR, "bridge-%s.log" % datetime.now().strftime("%Y%m%d"))


# =====================================================================
# 配置
# =====================================================================
def _deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8-sig") as fp:
                cfg = _deep_merge(cfg, json.load(fp))
            log("配置已加载: %s" % CONFIG_PATH)
        except Exception as exc:
            log("配置损坏，使用默认值: %s" % exc, "WARN")
    else:
        save_config(cfg)
        log("首次运行，已生成默认配置: %s" % CONFIG_PATH)
    return cfg


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fp:
            json.dump(cfg, fp, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except Exception as exc:
        log("保存配置失败: %s" % exc, "ERROR")


# =====================================================================
# 热键解析
# =====================================================================
MOD = {"ctrl": 0x0002, "control": 0x0002, "alt": 0x0001, "shift": 0x0004,
       "win": 0x0008, "meta": 0x0008, "cmd": 0x0008}

VK_SPECIAL = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B,
              "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
              "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28,
              "left": 0x25, "right": 0x27}


def parse_hotkey(text):
    """'ctrl+alt+c' -> (mods, vk)；非法返回 (0, 0)。"""
    if not text:
        return 0, 0
    mods, vk = 0, 0
    for raw in str(text).replace(" ", "").split("+"):
        t = raw.strip().lower()
        if not t:
            continue
        if t in MOD:
            mods |= MOD[t]
        elif t in VK_SPECIAL:
            vk = VK_SPECIAL[t]
        elif len(t) == 1 and t.isalpha():
            vk = ord(t.upper())
        elif len(t) == 1 and t.isdigit():
            vk = ord(t)
        elif t.startswith("f") and t[1:].isdigit() and 1 <= int(t[1:]) <= 24:
            vk = 0x70 + int(t[1:]) - 1
        else:
            log("无法识别的热键片段: %r（来自 %s）" % (raw, text), "WARN")
            return 0, 0
    if not vk:
        return 0, 0
    return mods, vk


def hotkey_label(text):
    parts = []
    for raw in str(text or "").replace(" ", "").split("+"):
        t = raw.strip()
        if not t:
            continue
        low = t.lower()
        parts.append({"ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "shift": "Shift",
                      "win": "Win", "meta": "Win"}.get(low, t.upper() if len(t) == 1 else t.capitalize()))
    return " + ".join(parts)


# =====================================================================
# 进程 / 端口探测
# =====================================================================
def port_alive(port, timeout=0.35):
    try:
        s = socket.create_connection(("127.0.0.1", int(port)), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_k32.OpenProcess.restype = wt.HANDLE
_k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
_k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
_k32.CloseHandle.argtypes = [wt.HANDLE]


def _load_enum_processes():
    """EnumProcesses 在 psapi.dll / K32EnumProcesses 在 kernel32，逐个尝试。"""
    for dll, fname in (("psapi", "EnumProcesses"), ("kernel32", "K32EnumProcesses"),
                       ("kernel32", "EnumProcesses")):
        try:
            fn = getattr(ctypes.WinDLL(dll), fname)
        except Exception:
            continue
        fn.restype = wt.BOOL
        fn.argtypes = [ctypes.POINTER(wt.DWORD), wt.DWORD, ctypes.POINTER(wt.DWORD)]
        return fn
    return None


_ENUM_PROC = _load_enum_processes()


def process_path(pid):
    h = _k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return ""
    finally:
        _k32.CloseHandle(h)


def find_process(exe_names):
    """返回第一个命中的 (pid, path)，未命中返回 (None, "")。"""
    if not _ENUM_PROC:
        return None, ""
    count = 1024
    for _ in range(3):
        arr = (wt.DWORD * count)()
        needed = wt.DWORD()
        if not _ENUM_PROC(arr, ctypes.sizeof(arr), ctypes.byref(needed)):
            return None, ""
        n = needed.value // ctypes.sizeof(wt.DWORD)
        if n < count:
            break
        count *= 2
    else:
        n = count
    names = set(x.lower() for x in exe_names)
    me = os.getpid()
    for i in range(n):
        pid = arr[i]
        if not pid or pid == me:
            continue
        p = process_path(pid)
        if p and os.path.basename(p).lower() in names:
            return pid, p
    return None, ""


def figcraft_process():
    return find_process(["figcraft.exe"])


# =====================================================================
# 单实例
# =====================================================================
def acquire_single_instance():
    h = _k32.CreateMutexW(None, False, MUTEX_NAME)
    if not h:
        return True
    if ctypes.get_last_error() == 183:      # ERROR_ALREADY_EXISTS
        _k32.CloseHandle(h)
        return False
    return True


def wake_existing(port):
    try:
        s = socket.create_connection(("127.0.0.1", int(port) + 1), timeout=1.0)
        s.sendall(b"SHOW\n")
        s.close()
        return True
    except Exception:
        return False


# =====================================================================
# 自启动（仅当前用户）
# =====================================================================
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "FigCraftBridgeConsole"


def autostart_command():
    if FROZEN:
        return '"%s"' % sys.executable
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.isfile(pyw):
        exe = pyw
    return '"%s" "%s"' % (exe, os.path.abspath(__file__))


def autostart_value():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            v, _ = winreg.QueryValueEx(k, RUN_VALUE)
            return v
    except FileNotFoundError:
        return ""
    except Exception:
        return ""


def set_autostart(on):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(k, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except Exception as exc:
        log("设置开机自启失败: %s" % exc, "ERROR")
        return False


# =====================================================================
# 主应用
# =====================================================================
class App(object):
    def __init__(self):
        global core_f2a, core_a2f
        self.q = queue.Queue()
        self.cfg = load_config()
        self.port = int(self.cfg.get("port") or 47900)
        self.busy = False
        self.last_msg = ""
        self.last_level = C_SUB
        self.port_ok = False
        self.fc_pid = None
        self.fc_path = ""
        self.hk_state = {}
        self._hk_sent = None

        os.makedirs(WORK_DIR, exist_ok=True)
        sys.path.insert(0, HERE)
        core_f2a = __import__("core_f2a")
        core_a2f = __import__("core_a2f")
        core_f2a.configure(work_dir=WORK_DIR, logger=lambda m: log(m, "CORE"))
        core_a2f.configure(work_dir=WORK_DIR, logger=lambda m: log(m, "CORE"))

        self.panel = None
        self.host = None
        self._stop = threading.Event()

    # ---------- 状态 ----------
    def bridges_state(self):
        out = {}
        for b in BRIDGE_NAMES:
            cfg = self.cfg["bridges"].get(b) or {}
            if not cfg.get("enabled", True):
                out[b] = "disabled"
            elif cfg.get("paused"):
                out[b] = "paused"
            else:
                out[b] = "running"
        return out

    def state_dict(self):
        return {
            "scale": getattr(self, "scale", 1.0),
            "version": VERSION,
            "port": self.port,
            "port_alive": self.port_ok,
            "fc_running": self.fc_pid is not None,
            "hotkey_state": dict(self.hk_state),
            "hotkeys": {b: hotkey_label(self.cfg["hotkeys"].get(b, "")) for b in BRIDGE_NAMES},
            "bridges": self.bridges_state(),
            "autostart": bool(self.cfg.get("autostart")),
            "busy": self.busy,
            "busy_msg": self.last_msg if self.busy else "",
            "last_msg": self.last_msg,
            "last_level": self.last_level,
            "window_pos": {k: v for k, v in (self.cfg.get("window") or {}).items() if v is not None},
        }

    def set_msg(self, text, level=C_SUB):
        self.last_msg = text
        self.last_level = level
        log(text, "UI")
        self.refresh_ui()

    def refresh_ui(self):
        if self.panel:
            try:
                self.panel.refresh(self.state_dict())
            except Exception as exc:
                log("刷新界面失败: %s" % exc, "ERROR")

    # ---------- 启动 ----------
    def detect_dpi(self):
        scale = 1.0
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem()
            if dpi:
                scale = dpi / 96.0
        except Exception:
            try:
                hdc = ctypes.windll.user32.GetDC(0)
                scale = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88) / 96.0
                ctypes.windll.user32.ReleaseDC(0, hdc)
            except Exception:
                scale = 1.0
        return max(1.0, min(scale, 3.0))

    def start(self):
        import ui_panel
        import ui_tray

        self.scale = self.detect_dpi()
        self.tray_mod = ui_tray
        self._probe_env()

        cfg_auto = bool(autostart_value())
        if cfg_auto != bool(self.cfg.get("autostart")):
            self.cfg["autostart"] = cfg_auto

        hooks = {
            "close": self.on_close,
            "settings": self.on_settings,
            "retry": self.on_retry,
            "all_on": lambda: self.on_all(True),
            "all_off": lambda: self.on_all(False),
            "open_log": self.on_open_log,
            "toggle_autostart": self.on_toggle_autostart,
            "pause": self.on_pause,
            "disable": self.on_disable,
            "launch_figcraft": self.on_launch_figcraft,
            "moved": self.on_moved,
        }
        self.panel = ui_panel.Panel(self.state_dict(), hooks)
        try:
            self.panel.canvas.focus_set()
        except Exception:
            pass

        self.host = ui_tray.TrayHost(self.q, ASSETS)
        self.host.start()
        self.apply_hotkeys(force=True)
        self.update_tray()

        self.panel.after(80, self.pump)
        threading.Thread(target=self.env_loop, name="env", daemon=True).start()
        threading.Thread(target=self.wake_listener, name="wake", daemon=True).start()

        log("控制台已启动（port=%d, scale=%.2f）" % (self.port, self.scale))
        if not self.port_ok:
            self.set_msg("FigCraft 控制端口未连接：请用带 --control %d 的方式启动 FigCraft" % self.port, C_WARN)
        else:
            self.set_msg("就绪：Ctrl+Alt+C 转 Axure，Ctrl+Alt+V 落入 FigCraft", C_SUB)

    # ---------- 环境探测 ----------
    def _probe_env(self):
        self.port_ok = port_alive(self.port)
        pid, path = figcraft_process()
        self.fc_pid, self.fc_path = pid, path

    def env_loop(self):
        while not self._stop.is_set():
            try:
                old = (self.port_ok, self.fc_pid)
                self._probe_env()
                if old != (self.port_ok, self.fc_pid):
                    log("环境变化: 端口%s, FigCraft %s" % ("连接" if self.port_ok else "断开",
                                                          "运行中" if self.fc_pid else "未运行"))
                    self.q.put(("env",))
            except Exception as exc:
                log("环境探测异常: %s" % exc, "ERROR")
            self._stop.wait(2.5)

    def wake_listener(self):
        port = self.port + 1
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", port))
            srv.listen(2)
            srv.settimeout(1.0)
        except Exception as exc:
            log("唤醒端口 %d 绑定失败: %s" % (port, exc), "WARN")
            return
        while not self._stop.is_set():
            try:
                conn, _ = srv.accept()
                conn.settimeout(0.5)
                try:
                    conn.recv(16)
                except Exception:
                    pass
                conn.close()
                self.q.put(("show",))
            except socket.timeout:
                continue
            except Exception:
                break

    # ---------- 热键 ----------
    def hotkey_specs(self):
        specs = []
        for b in BRIDGE_NAMES:
            mods, vk = parse_hotkey(self.cfg["hotkeys"].get(b))
            enabled = self.bridges_state()[b] != "disabled" and bool(vk)
            specs.append({"id": HOTKEY_ID[b], "name": b, "mods": mods, "vk": vk, "enabled": enabled})
        return specs

    def apply_hotkeys(self, force=False):
        specs = self.hotkey_specs()
        key = json.dumps(specs, sort_keys=True)
        if not force and key == self._hk_sent:
            return
        self._hk_sent = key
        if self.host:
            self.host.set_hotkeys(specs)
        log("热键注册: %s" % ", ".join("%s=%s%s" % (s["name"], self.cfg["hotkeys"].get(s["name"]),
                                                   "" if s["enabled"] else "(停用)") for s in specs))

    # ---------- 托盘 ----------
    def tray_variant(self):
        st = self.bridges_state()
        if all(v == "disabled" for v in st.values()):
            return "off"
        if not self.port_ok:
            return "error"
        if any(v == "paused" for v in st.values()):
            return "paused"
        return "normal"

    def update_tray(self):
        if not self.host:
            return
        st = self.bridges_state()
        brief = {"running": "运行中", "paused": "已暂停", "disabled": "已停用"}
        tip = "FigCraft 桥控制台 · %s" % (
            "端口未连接" if not self.port_ok else "/".join(brief[v] for v in st.values()))
        self.host.set_icon(self.tray_variant())
        self.host.set_tooltip(tip)

    # ---------- 事件泵 ----------
    def pump(self):
        try:
            while True:
                ev = self.q.get_nowait()
                self.handle_event(ev)
        except queue.Empty:
            pass
        except Exception as exc:
            log("事件处理异常: %s\n%s" % (exc, traceback.format_exc()), "ERROR")
        try:
            self.panel.after(80, self.pump)
        except Exception:
            pass

    def handle_event(self, ev):
        kind = ev[0]
        if kind == "hotkey":
            self.on_hotkey(int(ev[1]))
        elif kind == "hotkey_state":
            self.hk_state = ev[1]
            for name, ok in self.hk_state.items():
                if ok is False:
                    self.last_msg = "%s 热键被占用（%s）" % (BRIDGE_LABEL.get(name, name),
                                                          self.cfg["hotkeys"].get(name))
                    self.last_level = C_WARN
                    log(self.last_msg, "WARN")
            self.refresh_ui()
        elif kind == "tray_show" or kind == "show":
            self.panel.show_panel()
        elif kind == "tray_menu":
            self.show_menu()
        elif kind == "env":
            self.refresh_ui()
            self.update_tray()
        elif kind == "result":
            self.on_result(*ev[1:])
        elif kind == "host_error":
            log("托盘宿主异常: %s" % ev[1], "ERROR")
            self.last_msg = "托盘初始化失败（详见日志）"
            self.last_level = C_ERR
            self.refresh_ui()

    def show_menu(self):
        st = self.bridges_state()
        brief = {"running": "运行中", "paused": "已暂停", "disabled": "已停用"}
        items = [("显示控制面板", self.panel.show_panel, None), ("-", None, None)]
        for b in BRIDGE_NAMES:
            verb = "恢复" if st[b] == "paused" else "暂停"
            items.append(("%s（%s）→ %s" % (BRIDGE_LABEL[b], brief[st[b]], verb),
                          (lambda bb=b: self.on_pause(bb)), None))
            items.append(("%s → %s" % (BRIDGE_LABEL[b], "启用" if st[b] == "disabled" else "停用"),
                          (lambda bb=b: self.on_disable(bb)), None))
        items.append(("-", None, None))
        items.append(("全部启用", lambda: self.on_all(True), None))
        items.append(("全部停用", lambda: self.on_all(False), None))
        items.append(("开机自启", self.on_toggle_autostart, bool(self.cfg.get("autostart"))))
        items.append(("查看日志", self.on_open_log, None))
        items.append(("-", None, None))
        items.append(("退出", self.on_quit, None))
        try:
            self.panel.show_tray_menu(items)
        except Exception as exc:
            log("弹出托盘菜单失败: %s" % exc, "ERROR")

    # ---------- 交互动作 ----------
    def on_close(self):
        self.cfg["window"] = {k: v for k, v in self.state_dict()["window_pos"].items()}
        save_config(self.cfg)
        self.panel.hide_panel()
        self.last_msg = "已隐藏到托盘，热键仍然有效"
        self.last_level = C_SUB
        log(self.last_msg)

    def on_moved(self, pos):
        self.cfg["window"] = pos
        save_config(self.cfg)

    def on_retry(self):
        self._probe_env()
        self.set_msg("重新检测完成：端口%s，FigCraft %s" %
                     ("已连接" if self.port_ok else "未连接", "运行中" if self.fc_pid else "未运行"),
                     C_OK if self.port_ok else C_WARN)
        self.refresh_ui()
        self.update_tray()

    def on_settings(self):
        try:
            os.startfile(CONFIG_PATH)
            self.set_msg("已打开 config.json（改完热键后重启生效）", C_SUB)
        except Exception as exc:
            self.set_msg("打开配置失败：%s" % exc, C_ERR)

    def on_open_log(self):
        try:
            os.startfile(LOG_DIR)
            self.set_msg("已打开日志目录", C_SUB)
        except Exception as exc:
            self.set_msg("打开日志目录失败：%s" % exc, C_ERR)

    def on_toggle_autostart(self):
        want = not bool(self.cfg.get("autostart"))
        ok = set_autostart(want)
        self.cfg["autostart"] = want if ok else bool(autostart_value())
        save_config(self.cfg)
        self.set_msg("开机自启已%s" % ("开启" if self.cfg["autostart"] else "关闭"),
                     C_OK if ok else C_ERR)
        self.refresh_ui()

    def on_all(self, enable):
        for b in BRIDGE_NAMES:
            self.cfg["bridges"][b] = {"enabled": enable, "paused": False}
        save_config(self.cfg)
        self.hk_state = {}
        self.apply_hotkeys()
        self.set_msg("已%s两个方向的桥" % ("启用" if enable else "停用"), C_OK if enable else C_SUB)
        self.update_tray()

    def on_pause(self, bridge):
        cfg = self.cfg["bridges"].setdefault(bridge, {"enabled": True, "paused": False})
        if not cfg.get("enabled", True):
            return
        cfg["paused"] = not bool(cfg.get("paused"))
        save_config(self.cfg)
        self.set_msg("%s 已%s" % (BRIDGE_LABEL[bridge], "暂停" if cfg["paused"] else "恢复"),
                     C_WARN if cfg["paused"] else C_OK)
        self.update_tray()

    def on_disable(self, bridge):
        cfg = self.cfg["bridges"].setdefault(bridge, {"enabled": True, "paused": False})
        cfg["enabled"] = not bool(cfg.get("enabled", True))
        cfg["paused"] = False
        save_config(self.cfg)
        self.hk_state.pop(bridge, None)
        self.apply_hotkeys()
        self.set_msg("%s 已%s" % (BRIDGE_LABEL[bridge], "启用" if cfg["enabled"] else "停用"),
                     C_OK if cfg["enabled"] else C_SUB)
        self.update_tray()

    def on_launch_figcraft(self, bridge=None):
        from tkinter import messagebox
        exe = self.find_figcraft_exe()
        if not exe:
            self.set_msg("没找到 figcraft.exe，请在 config.json 里填 figcraft_exe 路径", C_ERR)
            return
        if self.fc_pid:
            if not messagebox.askyesno(
                    "重新启动 FigCraft",
                    "FigCraft 已经在运行，但没有开放控制端口 %d。\n\n"
                    "需要先结束当前 FigCraft 进程，再用带 --control %d 的参数重新启动。\n"
                    "未保存的文件请先手动保存。是否继续？" % (self.port, self.port)):
                return
            subprocess.run(["taskkill", "/PID", str(self.fc_pid), "/F"], capture_output=True)
            time.sleep(0.8)
        try:
            subprocess.Popen([exe, "--control", str(self.port)], cwd=os.path.dirname(exe))
            log("启动 FigCraft: %s --control %d" % (exe, self.port))
            self.set_msg("正在启动 FigCraft（控制端口 %d），稍候自动检测" % self.port, C_SUB)
            self.panel.after(4000, self.on_retry)
        except Exception as exc:
            self.set_msg("启动 FigCraft 失败：%s" % exc, C_ERR)

    def find_figcraft_exe(self):
        p = (self.cfg.get("figcraft_exe") or "").strip('" ')
        if p and os.path.isfile(p):
            return p
        candidates = []
        if self.fc_path:
            candidates.append(self.fc_path)
        local = os.environ.get("LOCALAPPDATA", "")
        for base in (r"D:\AI\FigCraft", os.path.join(local, "Programs"), r"C:\Program Files",
                     os.path.join(local, "FigCraft")):
            if base and os.path.isdir(base):
                candidates.append(os.path.join(base, "figcraft.exe"))
                try:
                    for name in os.listdir(base):
                        candidates.append(os.path.join(base, name, "figcraft.exe"))
                except OSError:
                    pass
        for c in candidates:
            if os.path.isfile(c):
                return c
        return ""

    # ---------- 转换 ----------
    def on_hotkey(self, hid):
        bridge = {v: k for k, v in HOTKEY_ID.items()}.get(hid)
        if not bridge:
            return
        state = self.bridges_state().get(bridge)
        if state == "disabled":
            self.notify("%s 已停用" % BRIDGE_LABEL[bridge], C_WARN)
            return
        if state == "paused":
            self.notify("%s 已暂停，先在面板恢复" % BRIDGE_LABEL[bridge], C_WARN)
            return
        if self.busy:
            self.notify("上一轮转换还没结束，请稍候", C_WARN)
            return
        if not self.port_ok:
            self.notify("FigCraft 控制端口 %d 未连接" % self.port, C_WARN)
            return
        self.busy = True
        self.last_msg = "正在转换（%s）…" % BRIDGE_LABEL[bridge]
        self.last_level = C_SUB
        self.refresh_ui()
        threading.Thread(target=self._worker, args=(bridge,), daemon=True).start()

    def _worker(self, bridge):
        t0 = time.time()
        try:
            if bridge == "to_axure":
                info = core_f2a.convert_selection(port=self.port, depth=int(self.cfg.get("depth") or 30),
                                                  do_copy=True)
                msg = "已复制「%s」：%d 组 / %d 文本 / %d 原生 / %d 矢量（%.1f KB）→ 切到 Axure 按 Ctrl+V" % (
                    info["title"], info["groups"], info["texts"], info["natives"], info["shapes"], info["kb"])
                self.q.put(("result", bridge, True, msg, C_OK, round(time.time() - t0, 2)))
            else:
                info = core_a2f.import_to_figcraft(port=self.port)
                msg = "%s（%d 条命令，%.1f 秒）" % (core_a2f.summary_text(info), info["commands"],
                                                 time.time() - t0)
                self.q.put(("result", bridge, True, msg, C_OK, round(time.time() - t0, 2)))
        except Exception as exc:
            self.q.put(("result", bridge, False, str(exc), C_ERR, round(time.time() - t0, 2)))

    def on_result(self, bridge, ok, msg, level, elapsed):
        self.busy = False
        self.last_msg = msg
        self.last_level = level
        log("[%s] %s" % (BRIDGE_LABEL[bridge], msg), "OK" if ok else "ERROR")
        self.refresh_ui()
        self.notify(msg, level)

    def notify(self, msg, level):
        if self.panel and self.panel.is_visible():
            self.last_msg = msg
            self.last_level = level
            self.refresh_ui()
        elif self.panel:
            self.panel.toast(msg[:60], level)

    # ---------- 退出 ----------
    def on_quit(self):
        log("用户退出控制台")
        self._stop.set()
        try:
            self.cfg["window"] = {k: v for k, v in self.state_dict()["window_pos"].items()}
            save_config(self.cfg)
        except Exception:
            pass
        try:
            if self.host:
                self.host.quit()
        except Exception:
            pass
        time.sleep(0.2)
        try:
            self.panel.destroy()
        except Exception:
            pass


def main():
    if not acquire_single_instance():
        cfg = load_config()
        if wake_existing(int(cfg.get("port") or 47900)):
            log("已有实例在运行，已唤出面板")
        else:
            log("已有实例在运行（唤醒通道未响应）", "WARN")
        return 0
    try:
        app = App()
    except Exception as exc:
        log("初始化失败: %s\n%s" % (exc, traceback.format_exc()), "ERROR")
        raise
    try:
        app.start()
    except Exception as exc:
        log("启动失败: %s\n%s" % (exc, traceback.format_exc()), "ERROR")
        raise
    try:
        app.panel.mainloop()
    finally:
        app._stop.set()
        log("主循环结束")
    return 0


def _excepthook(exc_type, exc_value, exc_tb):
    """全局兜底：把未捕获异常写入 crash.log，避免无控制台打包后只弹一个看不懂的框。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, "crash.log"), "a", encoding="utf-8") as fp:
            fp.write("=" * 60 + "\n")
            fp.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
            fp.write("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
            fp.write("\n")
    except Exception:
        pass
    try:
        log("未捕获异常: %s" % exc_value, "ERROR")
    except Exception:
        pass


sys.excepthook = _excepthook

if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        _excepthook(*sys.exc_info())
        raise
