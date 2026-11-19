# -*- coding: utf-8 -*-
"""
ui_tray —— 原生宿主：隐藏窗口 + 托盘图标 + 全局热键

为什么单独一个线程 + 隐藏窗口：
  Shell_NotifyIconW 和 RegisterHotKey 都要求有一个能收消息的窗口，
  而 Tkinter 不暴露 WndProc。所以这里用 ctypes 建一个 WS_POPUP 隐藏窗口，
  在自带的消息循环里统一处理托盘回调与 WM_HOTKEY，事件通过 queue 交回主线程。

对外只暴露线程安全的 set_hotkeys / set_icon / set_tooltip / quit。
"""
import ctypes
import ctypes.wintypes as wt
import os
import threading
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

WM_APP = 0x8000
WM_TRAY = WM_APP + 1
WM_RELOAD_HOTKEYS = WM_APP + 20
WM_UPDATE_ICON = WM_APP + 21
WM_QUIT_HOST = WM_APP + 22
WM_DESTROY = 0x0002
WM_CLOSE_W = 0x0010
WM_HOTKEY = 0x0312
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_LBUTTONDBLCLK = 0x0203

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x01, 0x02, 0x04

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
WS_POPUP = 0x80000000
WS_EX_TOOLWINDOW = 0x00000080
IDI_APPLICATION = 32512

_ULONG_PTR = ctypes.c_size_t


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", wt.HWND),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HICON),
        ("szTip", wt.WCHAR * 128),
        ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD),
        ("szInfo", wt.WCHAR * 256),
        ("uVersion", wt.UINT),
        ("szInfoTitle", wt.WCHAR * 64),
        ("dwInfoFlags", wt.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wt.HICON),
    ]


WNDPROC = ctypes.WINFUNCTYPE(_ULONG_PTR, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


user32.DefWindowProcW.restype = _ULONG_PTR
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.RegisterClassW.restype = wt.ATOM
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.LoadImageW.restype = wt.HANDLE
user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
user32.RegisterWindowMessageW.restype = wt.UINT
user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
user32.DestroyWindow.argtypes = [wt.HWND]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]


class TrayHost(object):
    """托盘 + 热键宿主。所有回调事件以 tuple 形式塞进 queue，由 Tk 主线程消费。"""

    def __init__(self, queue, icon_dir):
        self.q = queue
        self.icon_dir = icon_dir
        self._hwnd = None
        self._thread = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._hotkeys = []           # [{"name":..,"mods":..,"vk":..,"enabled":bool}]
        self._hk_state = {}
        self._icon_file = None
        self._icon_variant = "normal"
        self._tooltip = "FigCraft 桥控制台"
        self._hicon = None
        self._nid = None
        self._taskbar_msg = 0
        self._wndproc_ref = None

    # ---------------- 外部接口（任意线程可调） ----------------
    def start(self, timeout=5.0):
        self._thread = threading.Thread(target=self._run, name="tray-host", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)

    def is_ready(self):
        return self._ready.is_set()

    def set_hotkeys(self, specs):
        with self._lock:
            self._hotkeys = [dict(s) for s in specs]
        self._post(WM_RELOAD_HOTKEYS)

    def set_icon(self, variant):
        self._icon_variant = variant
        self._post(WM_UPDATE_ICON)

    def set_tooltip(self, text):
        self._tooltip = text[:120]
        self._post(WM_UPDATE_ICON)

    def post_message(self, msg, wparam=0, lparam=0):
        self._post(msg, wparam, lparam)

    def quit(self):
        self._post(WM_QUIT_HOST)

    def _post(self, msg, wparam=0, lparam=0):
        if self._hwnd:
            user32.PostMessageW(self._hwnd, msg, wparam, lparam)

    # ---------------- 线程主体 ----------------
    def _run(self):
        try:
            msg = wt.MSG()
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)  # 强制建立线程消息队列

            hinst = kernel32.GetModuleHandleW(None)
            self._wndproc_ref = WNDPROC(self._wndproc)
            cls = "FigCraftBridgeHostWnd_v1"
            wc = WNDCLASSW()
            wc.style = 0
            wc.lpfnWndProc = self._wndproc_ref
            wc.cbClsExtra = 0
            wc.cbWndExtra = 0
            wc.hInstance = hinst
            wc.hIcon = 0
            wc.hCursor = 0
            wc.hbrBackground = 0
            wc.lpszMenuName = None
            wc.lpszClassName = cls
            user32.RegisterClassW(ctypes.byref(wc))

            self._hwnd = user32.CreateWindowExW(WS_EX_TOOLWINDOW, cls, "FigCraftBridgeHost",
                                                WS_POPUP, 0, 0, 0, 0, None, None, hinst, None)
            if not self._hwnd:
                raise OSError("创建隐藏窗口失败: %s" % ctypes.get_last_error())
            self._taskbar_msg = user32.RegisterWindowMessageW("TaskbarCreated")
            self._add_icon()
            self._apply_hotkeys()
            self._ready.set()

            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret in (0, -1):
                    break
                if msg.message == WM_QUIT_HOST:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as exc:  # 宿主挂了也要让主程序知道
            self.q.put(("host_error", str(exc)))
            self._ready.set()
        finally:
            self._remove_icon()
            try:
                if self._hwnd:
                    user32.DestroyWindow(self._hwnd)
            except Exception:
                pass
            self._hwnd = None

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAY:
                low = lparam & 0xFFFF
                if low in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self.q.put(("tray_show",))
                    return 0
                if low == WM_RBUTTONUP:
                    self.q.put(("tray_menu",))
                    return 0
            elif msg == WM_HOTKEY:
                self.q.put(("hotkey", int(wparam)))
                return 0
            elif msg == WM_RELOAD_HOTKEYS:
                self._apply_hotkeys()
                return 0
            elif msg == WM_UPDATE_ICON:
                self._update_icon()
                return 0
            elif msg == WM_QUIT_HOST:
                user32.PostQuitMessage(0)
                return 0
            elif msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            elif self._taskbar_msg and msg == self._taskbar_msg:
                self._add_icon()
                return 0
        except Exception as exc:
            self.q.put(("host_error", "wndproc: %s" % exc))
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ---------------- 托盘图标 ----------------
    def _icon_path(self, variant):
        name = {"normal": "tray_normal.ico", "paused": "tray_paused.ico",
                "error": "tray_error.ico", "off": "tray_off.ico"}.get(variant, "tray_normal.ico")
        return os.path.join(self.icon_dir, name)

    def _load_icon(self, variant):
        p = self._icon_path(variant)
        if not os.path.isfile(p):
            return user32.LoadIconW(None, wt.LPCWSTR(IDI_APPLICATION))
        h = user32.LoadImageW(None, p, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if not h:
            h = user32.LoadIconW(None, wt.LPCWSTR(IDI_APPLICATION))
        return h

    def _add_icon(self):
        self._hicon = self._load_icon(self._icon_variant)
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._hicon
        nid.szTip = (self._tooltip or "FigCraft 桥控制台")[:120]
        self._nid = nid
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            time.sleep(0.4)
            shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _update_icon(self):
        if not self._nid:
            return
        try:
            self._hicon = self._load_icon(self._icon_variant)
            self._nid.hIcon = self._hicon
            self._nid.uFlags = NIF_ICON | NIF_TIP
            self._nid.szTip = (self._tooltip or "FigCraft 桥控制台")[:120]
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._nid))
        except Exception:
            pass

    def _remove_icon(self):
        try:
            if self._nid:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
        except Exception:
            pass

    # ---------------- 全局热键 ----------------
    def _apply_hotkeys(self):
        with self._lock:
            specs = [dict(s) for s in self._hotkeys]
        state = {}
        for s in specs:
            hid = int(s.get("id") or 0)
            user32.UnregisterHotKey(self._hwnd, hid)
            if s.get("enabled"):
                ok = bool(user32.RegisterHotKey(self._hwnd, hid, int(s.get("mods") or 0) | MOD_NOREPEAT,
                                                int(s.get("vk") or 0)))
                state[s.get("name")] = ok
            else:
                state[s.get("name")] = None       # None = 未注册（已停用）
        self._hk_state = state
        self.q.put(("hotkey_state", dict(state)))
