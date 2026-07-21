"""与界面和 LCU 无关的通用工具。"""

import ctypes
from dataclasses import dataclass, field

try:
    from pypinyin import Style, pinyin

    HAS_PINYIN = True
except ImportError:
    HAS_PINYIN = False


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


@dataclass(slots=True)
class ChampionObj:
    id: int
    name: str
    title: str
    alias: str
    display_name: str = field(init=False)
    search_keys: str = field(init=False)

    def __post_init__(self):
        self.display_name = (
            f"{self.title} - {self.name} ({self.alias})" if self.title else self.name
        )
        search_parts = [self.name, self.title, self.alias]
        if HAS_PINYIN:
            chinese_text = self.name + self.title
            search_parts.extend(
                (
                    "".join(item[0] for item in pinyin(chinese_text, style=Style.NORMAL)),
                    "".join(
                        item[0]
                        for item in pinyin(chinese_text, style=Style.FIRST_LETTER)
                    ),
                )
            )
        self.search_keys = " ".join(search_parts).lower()


def analyze_premades(players):
    """根据近期共同对局 ID 推测当前队伍中的组队关系。"""
    groups = []
    visited = set()

    for index, player in enumerate(players):
        if index in visited:
            continue

        group = [index]
        for candidate_index in range(index + 1, len(players)):
            if candidate_index in visited:
                continue
            candidate = players[candidate_index]
            if player["recent_game_ids"] & candidate["recent_game_ids"]:
                group.append(candidate_index)
                visited.add(candidate_index)

        if len(group) > 1:
            visited.add(index)
            groups.append([players[item]["display_name"] for item in group])

    return groups
