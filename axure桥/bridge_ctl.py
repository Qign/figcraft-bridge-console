# -*- coding: utf-8 -*-
"""
转换桥启停管理（供「启用桥.bat」「停用桥.bat」「查看状态.bat」调用）

    python bridge_ctl.py start     启动常驻桥（后台静默、无窗口）
    python bridge_ctl.py stop      结束桥进程（含调试模式的 python.exe 实例）
    python bridge_ctl.py status    查看运行 / 暂停 / FigCraft 连接状态
    python bridge_ctl.py pause     暂停（进程不退，热键不再转换）
    python bridge_ctl.py resume    恢复

只匹配命令行含 figcraft_axure_bridge.py 的 python.exe / pythonw.exe，
并排除 --toast 提示子进程，不会影响机器上其它 python 程序。
"""
import os
import socket
import subprocess
import sys
import tempfile
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(APP_DIR, "figcraft_axure_bridge.py")
PAUSE_FLAG = os.path.join(tempfile.gettempdir(), "figcraft2axure", "paused.flag")
LOG_PATH = os.path.join(tempfile.gettempdir(), "figcraft2axure", "bridge.log")
KEY = "figcraft_axure_bridge.py"
DEFAULT_PORT = 47900
NO_WINDOW = 0x08000000

PS_PIDS = (
    "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
    "Where-Object { $_.CommandLine -like '*" + KEY + "*' "
    "-and $_.CommandLine -notlike '*--toast*' } | "
    "ForEach-Object { $_.ProcessId }"
)


def bridge_pids():
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", PS_PIDS],
                             capture_output=True, text=True, timeout=25,
                             creationflags=NO_WINDOW)
        if out.stdout.startswith("#< CLIXML"):
            text = out.stderr
        else:
            text = out.stdout
        return [int(x) for x in text.split() if x.strip().isdigit()]
    except Exception:
        return []


def pythonw_path():
    exe = sys.executable or ""
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.isfile(cand):
        return cand
    return "pythonw"


def port_alive(port=DEFAULT_PORT):
    s = socket.socket()
    s.settimeout(0.6)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def write_flag(on):
    os.makedirs(os.path.dirname(PAUSE_FLAG), exist_ok=True)
    with open(PAUSE_FLAG, "w", encoding="utf-8") as fp:
        fp.write(time.strftime("%Y-%m-%d %H:%M:%S") if on else "off")


def is_paused():
    try:
        with open(PAUSE_FLAG, "r", encoding="utf-8") as fp:
            return fp.read().strip().lower() not in ("off", "resume", "resumed")
    except Exception:
        return False


def describe():
    pids = bridge_pids()
    paused = is_paused()
    port = port_alive()
    if not pids:
        head = "转换桥：未运行 —— 按 Ctrl+Alt+C 不应有任何提示"
    elif paused:
        head = "转换桥：运行中但已暂停（PID %s）—— 按热键只弹提示、不转换" % ", ".join(map(str, pids))
    else:
        head = "转换桥：运行中（PID %s）—— 热键有效" % ", ".join(map(str, pids))
    tail = ("FigCraft：已连接控制端口 %d" % DEFAULT_PORT) if port else \
        ("FigCraft：未打开（端口 %d 无响应）—— 此时按热键只会提示先打开 FigCraft" % DEFAULT_PORT)
    return head, tail, pids, paused, port


def cmd_status():
    head, tail, _, _, _ = describe()
    print(head)
    print(tail)
    return 0


def cmd_start():
    if not os.path.isfile(SCRIPT):
        print("[错误] 找不到 figcraft_axure_bridge.py")
        return 1
    running = bridge_pids()
    if running:
        write_flag(False)
        print("转换桥已在运行（PID %s），无需重复启动，已确保为启用状态。" % ", ".join(map(str, running)))
        print("  转换 Ctrl+Alt+C    暂停/恢复 Ctrl+Alt+S")
        if not port_alive():
            print("  提示：FigCraft 还没打开，先用「启动FigCraft(带转换桥).lnk」打开它")
        return 0
    write_flag(False)
    subprocess.Popen([pythonw_path(), SCRIPT], creationflags=NO_WINDOW,
                     cwd=APP_DIR, close_fds=True)
    for _ in range(12):
        time.sleep(0.4)
        got = bridge_pids()
        if got:
            print("转换桥已启用（PID %s，后台静默运行）。" % ", ".join(map(str, got)))
            print("  FigCraft 里选中画板 → Ctrl+Alt+C → Axure 画布 Ctrl+V")
            print("  临时避让：Ctrl+Alt+S 暂停，再按一次恢复")
            print("  彻底停用：双击「停用桥.bat」")
            if not port_alive():
                print("  提示：FigCraft 还没打开，先用「启动FigCraft(带转换桥).lnk」打开它")
            return 0
    print("[失败] 桥没启动起来。日志尾部：")
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as fp:
            for line in fp.readlines()[-5:]:
                print("  " + line.rstrip())
    except Exception:
        print("  （读不到日志 %s）" % LOG_PATH)
    return 1


def cmd_stop():
    pids = bridge_pids()
    if not pids:
        print("转换桥当前没有在运行。")
        print("  若按 Ctrl+Alt+C 仍有提示，说明还有进程活着，请再运行一次本脚本。")
        return 0
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                       capture_output=True, creationflags=NO_WINDOW)
    time.sleep(0.8)
    left = bridge_pids()
    if left:
        print("[提示] 还有 %d 个桥进程没退出（PID %s），可能被安全软件拦截，"
              "可在任务管理器结束 pythonw.exe / python.exe。" % (len(left), ", ".join(map(str, left))))
        return 1
    write_flag(False)
    print("转换桥已停用（结束 %d 个进程：%s）。" % (len(pids), ", ".join(map(str, pids))))
    print("  Ctrl+Alt+C / Ctrl+Alt+S 都不会有反应，剪贴板不会被改动。")
    print("  需要时双击「启用桥.bat」恢复。")
    return 0


def cmd_pause(on):
    if not bridge_pids():
        print("转换桥没在运行，先双击「启用桥.bat」。")
        return 1
    try:
        write_flag(on)
    except Exception as exc:
        print("[错误] %s" % exc)
        return 1
    print("已暂停：进程仍在，但按 Ctrl+Alt+C 不会转换。" if on
          else "已恢复：Ctrl+Alt+C 可正常转换。")
    return 0


if __name__ == "__main__":
    action = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    table = {"start": cmd_start, "stop": cmd_stop, "status": cmd_status,
             "pause": lambda: cmd_pause(True), "resume": lambda: cmd_pause(False)}
    fn = table.get(action)
    if not fn:
        print("用法：python bridge_ctl.py start|stop|status|pause|resume")
        sys.exit(2)
    sys.exit(fn() or 0)
