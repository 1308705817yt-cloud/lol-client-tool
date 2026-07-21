"""游戏内预设快捷发送与热键处理。"""

import ctypes
import random
import threading
import time

import shared
from game_input import game_auto_chat


_typing_lock = threading.Lock()
_is_waiting_for_target = False

SPEED_DELAYS = {
    "档位1": (1.5, 2.5),
    "档位2": (0.8, 1.5),
    "档位3": (0.3, 0.7),
    "档位4": (0.1, 0.3),
    "档位5": (0.01, 0.05),
}


def set_target(role):
    if shared.CURRENT_CONFIG.get("指名道姓开关"):
        shared.TARGET_ROLE = role
        shared.TARGET_EVENT.set()


def toggle_send_to_all():
    new_state = not shared.CURRENT_CONFIG.get("拆字发所有人", True)
    shared.CURRENT_CONFIG["拆字发所有人"] = new_state
    shared.save_config()

    shared.update_send_channel(new_state)

    channel = "【所有人频道 (Shift+Enter)】" if new_state else "【仅队伍频道 (Enter)】"
    shared.gui_print(f"发送频道已切换至: {channel}", "rank")


def _split_settings():
    try:
        minimum = max(1, int(shared.CURRENT_CONFIG.get("拆字最小字数", 1)))
        maximum = max(minimum, int(shared.CURRENT_CONFIG.get("拆字最大字数", 1)))
    except (TypeError, ValueError):
        minimum = maximum = 1

    speed = shared.CURRENT_CONFIG.get("拆字发送速度", "档位3 (正常)")
    delay = next(
        (value for level, value in SPEED_DELAYS.items() if level in speed),
        SPEED_DELAYS["档位3"],
    )
    return minimum, maximum, speed, delay


def _split_text(text, minimum, maximum):
    chunks = []
    index = 0
    while index < len(text):
        step = random.randint(minimum, maximum)
        chunks.append(text[index:index + step])
        index += step
    return chunks


def _append_target(text, send_to_all):
    global _is_waiting_for_target

    shared.gui_print(
        "3 秒内可按小键盘 1~5 追加目标，再按一次发送键可跳过等待。",
        "info",
    )
    shared.TARGET_ROLE = ""
    shared.TARGET_EVENT.clear()
    _is_waiting_for_target = True
    shared.TARGET_EVENT.wait(3.0)
    _is_waiting_for_target = False

    if not shared.TARGET_ROLE:
        return text

    side = "敌方" if send_to_all else "己方"
    target = shared.CURRENT_CONFIG.get(
        f"目标_{side}{shared.TARGET_ROLE}", f"{side}{shared.TARGET_ROLE}"
    ).strip()
    if not target:
        return text
    return random.choice((f"{target}，{text}", f"{text}，{target}"))


def process_and_send(text):
    global _is_waiting_for_target

    if not text:
        return
    if not _typing_lock.acquire(blocking=False):
        shared.gui_print("当前已有发送任务，请稍后重试。", "loss")
        return

    try:
        send_to_all = shared.CURRENT_CONFIG.get("拆字发所有人", True)

        if shared.CURRENT_CONFIG.get("指名道姓开关"):
            text = _append_target(text, send_to_all)

        min_chars, max_chars, speed_level, delay = _split_settings()
        chunks = _split_text(text, min_chars, max_chars)

        shared.gui_print(
            f"开始发送（每次 {min_chars}~{max_chars} 字）：{text} | 速度：{speed_level}",
            "info"
        )
        for index, chunk in enumerate(chunks):
            if not shared.CURRENT_CONFIG.get("拆字发送开关"):
                shared.gui_print("预设发送已中止。", "sys")
                break
            game_auto_chat(chunk, send_to_all)
            if index < len(chunks) - 1:
                time.sleep(random.uniform(*delay))
        else:
            shared.gui_print("发送完毕。", "success")
    except Exception as exc:
        shared.gui_print(f"快捷发送失败: {exc}", "loss")
    finally:
        _is_waiting_for_target = False
        _typing_lock.release()


def _skip_target_wait_if_needed():
    if not _is_waiting_for_target:
        return False
    shared.TARGET_ROLE = ""
    shared.TARGET_EVENT.set()
    return True


def send_random_sentence():
    if _skip_target_wait_if_needed() or not shared.CURRENT_CONFIG.get("拆字发送开关"):
        return
    lines = [
        line.strip()
        for line in shared.CURRENT_CONFIG.get("句子库", "").splitlines()
        if line.strip()
    ]
    if not lines:
        shared.gui_print("句子库为空，请先添加内容。", "loss")
        return
    threading.Thread(
        target=process_and_send, args=(random.choice(lines),), daemon=True
    ).start()


def send_fixed_sentence():
    if _skip_target_wait_if_needed() or not shared.CURRENT_CONFIG.get("拆字发送开关"):
        return
    text = shared.CURRENT_CONFIG.get("预设单句", "").strip()
    if not text:
        shared.gui_print("固定单句为空，请先填写内容。", "loss")
        return
    threading.Thread(target=process_and_send, args=(text,), daemon=True).start()


def hotkey_worker():
    keys = {
        0x60: send_fixed_sentence,       # 小键盘 0
        0x61: lambda: set_target("上单"),
        0x62: lambda: set_target("打野"),
        0x63: lambda: set_target("中单"),
        0x64: lambda: set_target("AD"),
        0x65: lambda: set_target("辅助"),
        0x66: toggle_send_to_all,        # 小键盘 6
        0x6E: send_random_sentence,      # 小键盘 .
    }
    key_states = {key: False for key in keys}

    shared.gui_print("快捷发送热键已就绪。", "sys")
    while True:
        for virtual_key, callback in keys.items():
            is_down = bool(ctypes.windll.user32.GetAsyncKeyState(virtual_key) & 0x8000)
            if is_down and not key_states[virtual_key]:
                key_states[virtual_key] = True
                callback()
            elif not is_down:
                key_states[virtual_key] = False
        time.sleep(0.02)
