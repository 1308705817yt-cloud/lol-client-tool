"""程序入口：准备 Windows 环境并启动后台服务与界面。"""

import ctypes
import os
import sys
import threading
import traceback
from pathlib import Path

from utils import is_admin


def configure_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def application_directory():
    executable = sys.executable if getattr(sys, "frozen", False) else __file__
    return Path(executable).resolve().parent


def ensure_admin():
    if is_admin():
        return True

    print("当前权限不足，正在请求管理员权限...")
    parameters = "" if getattr(sys, "frozen", False) else f'"{Path(__file__).resolve()}"'
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, parameters, None, 1
    )
    if result <= 32:
        raise RuntimeError("管理员权限请求被取消或启动失败")
    return False


def start_worker(name, target):
    thread = threading.Thread(name=name, target=target, daemon=True)
    thread.start()
    return thread


def run_application():
    # 延迟导入，确保工作目录和权限在模块读取配置前已经准备完毕。
    from gui import start_gui
    from lcu_core import run_lcu_in_background
    from quick_chat import hotkey_worker

    start_worker("lcu-client", run_lcu_in_background)
    start_worker("quick-chat-hotkeys", hotkey_worker)
    start_gui()


def main():
    configure_dpi_awareness()
    if not ensure_admin():
        return

    os.chdir(application_directory())
    run_application()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("\n" + "=" * 50)
        print("程序启动失败")
        print("=" * 50)
        traceback.print_exc()
        print("=" * 50)
        try:
            input("请保存上方报错信息，按【回车键】退出...")
        except EOFError:
            pass
