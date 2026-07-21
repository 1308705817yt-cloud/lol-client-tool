"""基于 Windows SendInput 的游戏聊天输入。"""

import ctypes
import random
import time
from ctypes import wintypes


USER32 = ctypes.WinDLL("user32", use_last_error=True)
wintypes.ULONG_PTR = wintypes.WPARAM

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_UNICODE = 0x0004
MAPVK_VK_TO_VSC = 0
VK_ENTER = 0x0D
VK_SHIFT = 0x10


class KeyboardInput(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.ULONG_PTR),
    )


class MouseInput(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.ULONG_PTR),
    )


class HardwareInput(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class InputValue(ctypes.Union):
    _fields_ = (("keyboard", KeyboardInput), ("mouse", MouseInput), ("hardware", HardwareInput))


class Input(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("value", InputValue))


USER32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int)
USER32.SendInput.restype = wintypes.UINT


def _send_keyboard(scan_code, flags):
    value = InputValue()
    value.keyboard = KeyboardInput(0, scan_code, flags, 0, 0)
    event = Input(INPUT_KEYBOARD, value)
    if USER32.SendInput(1, ctypes.byref(event), ctypes.sizeof(event)) != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def send_key(virtual_key, pressed):
    scan_code = USER32.MapVirtualKeyW(virtual_key, MAPVK_VK_TO_VSC)
    flags = KEYEVENTF_SCANCODE | (0 if pressed else KEYEVENTF_KEYUP)
    _send_keyboard(scan_code, flags)


def tap_key(virtual_key):
    send_key(virtual_key, True)
    time.sleep(random_delay(15, 35))
    send_key(virtual_key, False)


def send_unicode(text):
    # SendInput 接收 UTF-16 code unit；按两个字节拆分可正确处理 emoji。
    encoded = text.encode("utf-16-le")
    for index in range(0, len(encoded), 2):
        code_unit = int.from_bytes(encoded[index:index + 2], "little")
        _send_keyboard(code_unit, KEYEVENTF_UNICODE)
        _send_keyboard(code_unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
        time.sleep(0.005)


def random_delay(minimum_ms=15, maximum_ms=45):
    return random.uniform(minimum_ms, maximum_ms) / 1000


def game_auto_chat(message, to_all=False):
    """打开聊天框、输入一段文本并发送。"""
    try:
        if to_all:
            send_key(VK_SHIFT, True)
            time.sleep(random_delay(10, 20))
            tap_key(VK_ENTER)
            time.sleep(random_delay(10, 20))
            send_key(VK_SHIFT, False)
        else:
            tap_key(VK_ENTER)

        time.sleep(random_delay(50, 90))
        send_unicode(message)
        time.sleep(random_delay(40, 80))
        tap_key(VK_ENTER)
    finally:
        # 任何异常都不应让修饰键保持按下状态。
        send_key(VK_SHIFT, False)
        send_key(VK_ENTER, False)
