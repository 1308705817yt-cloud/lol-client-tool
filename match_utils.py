"""战绩与队伍数据的纯转换函数。"""

TIER_NAMES = {
    "IRON": "黑铁", "BRONZE": "青铜", "SILVER": "白银", "GOLD": "黄金",
    "PLATINUM": "铂金", "EMERALD": "翡翠", "DIAMOND": "钻石",
    "MASTER": "超凡大师", "GRANDMASTER": "傲世宗师", "CHALLENGER": "最强王者",
    "UNRANKED": "未定级", "NONE": "未定级",
}

QUEUE_NAMES = {
    420: "单双排位", 440: "灵活排位", 430: "匹配模式", 400: "匹配模式",
    450: "极地大乱斗", 1700: "斗魂竞技场", 1900: "无限火力",
    2400: "海克斯大乱斗", 900: "无限乱斗", 0: "自定义",
}

QUEUE_IDS_BY_MODE = {
    "单双排": [420], "灵活排位": [440], "大乱斗": [450],
    "海克斯大乱斗": [2400], "匹配": [430, 400],
}

POSITIONS = ("上单", "打野", "中单", "AD", "辅助")
POSITION_ALIASES = {
    "TOP": "上单",
    "JUNGLE": "打野",
    "MIDDLE": "中单",
    "MID": "中单",
    "BOTTOM": "AD",
    "BOT": "AD",
    "ADC": "AD",
    "CARRY": "AD",
    "DUO_CARRY": "AD",
    "UTILITY": "辅助",
    "SUPPORT": "辅助",
    "DUO_SUPPORT": "辅助",
}


def queue_ids_for_mode(mode):
    return QUEUE_IDS_BY_MODE.get(mode, [])


def player_name(data, fallback):
    return (
        data.get("riotIdGameName")
        or data.get("summonerName")
        or data.get("gameName")
        or fallback
    )


def player_position(player):
    """将客户端不同版本使用的位置字段统一为界面中的五个位置。"""
    fields = (
        "selectedPosition",
        "assignedPosition",
        "teamPosition",
        "individualPosition",
        "position",
        "role",
        "lane",
    )
    for field in fields:
        value = str(player.get(field, "")).strip().upper().replace(" ", "_")
        if value in POSITION_ALIASES:
            return POSITION_ALIASES[value]
    return None


def assign_team_positions(players):
    """优先按位置字段分配，无法定位的玩家按原顺序填入剩余位置。"""
    assigned = {}
    unassigned = []

    for player in players:
        position = player_position(player)
        if position and position not in assigned:
            assigned[position] = player
        else:
            unassigned.append(player)

    remaining_positions = [position for position in POSITIONS if position not in assigned]
    assigned.update(zip(remaining_positions, unassigned))
    return {position: assigned[position] for position in POSITIONS if position in assigned}


def parse_ranks(queues):
    ranks = {"RANKED_SOLO_5x5": "未定级", "RANKED_FLEX_SR": "未定级"}
    for queue_data in queues:
        tier = queue_data.get("tier", "UNRANKED")
        queue_type = queue_data.get("queueType")
        if tier in {"NONE", "UNRANKED"} or queue_type not in ranks:
            continue
        division = (
            ""
            if tier in {"MASTER", "GRANDMASTER", "CHALLENGER"}
            else queue_data.get("division", "")
        )
        ranks[queue_type] = f"{TIER_NAMES.get(tier, tier)} {division}".strip()
    return ranks["RANKED_SOLO_5x5"], ranks["RANKED_FLEX_SR"]


def extract_games(payload):
    games = payload.get("games", {})
    if isinstance(games, dict):
        games = games.get("games", [])
    return games if isinstance(games, list) else []


def summarize_games(
    games, champion_names, target_queues=None, limit=None, include_mode=False
):
    matches = []
    kills = deaths = assists = wins = 0
    recent_game_ids = set()

    for game in games:
        game_id = game.get("gameId")
        if game_id:
            recent_game_ids.add(game_id)
        queue_id = game.get("queueId")
        if target_queues and queue_id not in target_queues:
            continue

        participants = game.get("participants", [])
        if not participants:
            continue
        participant = participants[0]
        stats = participant.get("stats", {})
        champion = champion_names.get(participant.get("championId"), "未知")
        kills_value = stats.get("kills", 0)
        deaths_value = stats.get("deaths", 0)
        assists_value = stats.get("assists", 0)
        won = bool(stats.get("win"))
        kills += kills_value
        deaths += deaths_value
        assists += assists_value
        wins += int(won)

        result = (
            f"{'胜' if won else '负'}-{champion}"
            f"({kills_value}/{deaths_value}/{assists_value})"
        )
        if include_mode:
            result += f"[{QUEUE_NAMES.get(queue_id, f'模式:{queue_id}')}]"
        matches.append(result)
        if limit and len(matches) >= limit:
            break

    game_count = len(matches)
    return {
        "matches": matches,
        "kda": (kills + assists) / max(1, deaths) if game_count else 0,
        "win_rate": wins / game_count * 100 if game_count else 0,
        "recent_game_ids": recent_game_ids,
    }


def premade_champions(players, groups):
    return [
        [player["champ_name"] for player in players if player["display_name"] in group]
        for group in groups
    ]


def format_tree_rows(players, premade_groups):
    rows = []
    for player in players:
        display_name = player["display_name"]
        group_number = next(
            (
                index
                for index, group in enumerate(premade_groups, start=1)
                if display_name in group
            ),
            None,
        )
        if group_number:
            display_name = f"组队{group_number} {display_name}"
        rows.append(
            (
                player["team_name"], display_name, player["champ_name"],
                player["rank_text"], player["kda_text"], player["winrate_text"],
            )
        )
    return rows


def format_groups(groups):
    return " | ".join(f"[{','.join(group)}]" for group in groups)
