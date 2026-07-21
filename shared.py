"""配置、运行时共享状态和 UI 通知接口。"""

import json
import os
import sys
import tempfile
import threading
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG = {
    "查询模式": "单双排",
    "查询场数": 5,
    "自动接受": False,
    "自动禁用": False,
    "禁用英雄": "",
    "自动选择": False,
    "选择英雄": "",
    "KDA称号": ["S", "A", "B", "C", "D"],
    "黑名单": {},

    # 预设快捷发送
    "拆字发送开关": False,
    "拆字发所有人": True,
    "拆字最小字数": 1,
    "拆字最大字数": 1,
    "拆字发送速度": "档位3 (正常)",
    "预设单句": "注意敌方打野位置",
    "句子库": "小心草丛\n准备打团\n先发育，等关键装备",
    "指名道姓开关": False,
}

for side, label in (("敌方", "对面"), ("己方", "己方")):
    for position in ("上单", "打野", "中单", "AD", "辅助"):
        DEFAULT_CONFIG[f"目标_{side}{position}"] = f"{label}{position}"

_CONFIG_LOCK = threading.RLock()
_CONFIG_NEEDS_REWRITE = False


def load_config():
    global _CONFIG_NEEDS_REWRITE
    config = deepcopy(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as file:
                saved = json.load(file)
                if not isinstance(saved, dict):
                    raise ValueError("配置文件根节点必须是 JSON 对象")
                supported = {key: value for key, value in saved.items() if key in DEFAULT_CONFIG}
                _CONFIG_NEEDS_REWRITE = len(supported) != len(saved)
                config.update(supported)
        except Exception as exc:
            print(f"读取配置失败: {exc}")
    return config


CURRENT_CONFIG = load_config()


def save_config():
    temp_file = None
    try:
        # GUI、热键和 LCU 工作线程都可能保存配置。串行化并采用原子替换，
        # 避免并发写入或程序中途退出时留下半截 JSON。
        with _CONFIG_LOCK:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=BASE_DIR,
                prefix=".config.",
                suffix=".tmp",
                delete=False,
            ) as file:
                temp_file = file.name
                json.dump(CURRENT_CONFIG, file, ensure_ascii=False, indent=4)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_file, CONFIG_FILE)
            temp_file = None
    except Exception as exc:
        print(f"保存配置失败: {exc}")
        try:
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)
        except OSError:
            pass


if _CONFIG_NEEDS_REWRITE:
    save_config()

CHAMPION_DICT = {}
CHAMPION_NAME_TO_ID = {}
ALL_CHAMPS = []
LAST_MATCH_PLAYERS_DICT = {}

# 快捷发送目标选择状态
TARGET_EVENT = threading.Event()
TARGET_ROLE = ""

# 当前对局状态
CURRENT_GAME_ID = 0
CURRENT_GAME_MODE = "未知模式"

@dataclass(slots=True)
class UIHooks:
    print_message: Callable[..., None] | None = None
    clear_log: Callable[..., None] | None = None
    print_matches: Callable[..., None] | None = None
    update_tree: Callable[..., None] | None = None
    clear_tree: Callable[..., None] | None = None
    update_champions: Callable[..., None] | None = None
    update_blacklist: Callable[..., None] | None = None
    update_send_channel: Callable[..., None] | None = None
    update_targets: Callable[..., None] | None = None


UI = UIHooks()


def register_ui(**hooks):
    for name, callback in hooks.items():
        if not hasattr(UI, name):
            raise ValueError(f"未知 UI 回调: {name}")
        setattr(UI, name, callback)


def _call_ui(name, *args):
    callback = getattr(UI, name)
    if callback:
        callback(*args)


def gui_print(message, color_tag=None):
    if UI.print_message:
        UI.print_message(message, color_tag)
    else:
        print(message)


def gui_clear():
    _call_ui("clear_log")


def gui_print_matches(matches):
    _call_ui("print_matches", matches)


def update_tree(allies, enemies):
    _call_ui("update_tree", allies, enemies)


def clear_tree():
    _call_ui("clear_tree")


def update_champions():
    _call_ui("update_champions")


def update_blacklist(players):
    _call_ui("update_blacklist", players)


def update_send_channel(send_to_all):
    _call_ui("update_send_channel", send_to_all)


def update_targets(targets):
    _call_ui("update_targets", targets)
