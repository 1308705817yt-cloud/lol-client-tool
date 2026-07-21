"""League Client API 连接、战绩查询和自动 BP。"""

import asyncio

from lcu_driver import Connector

import shared
from match_utils import (
    QUEUE_NAMES,
    assign_team_positions,
    extract_games,
    format_groups,
    format_tree_rows,
    parse_ranks,
    player_name,
    premade_champions,
    queue_ids_for_mode,
    summarize_games,
)
from utils import ChampionObj, HAS_PINYIN, analyze_premades

connector = Connector()

GLOBAL_CONN = None
GLOBAL_LOOP = None
lobby_processed = False
is_processing = False
executed_actions = set()


def configured_blacklist():
    blacklist = shared.CURRENT_CONFIG.get("黑名单", {})
    if isinstance(blacklist, list):
        return {name: "无历史记录" for name in blacklist}
    return blacklist


def warn_if_blacklisted(name, location):
    record = configured_blacklist().get(name)
    if not record:
        return
    shared.gui_print(f"\n玩家备注提醒：【{name}】位于{location}", "loss")
    for line in record.splitlines():
        if line.strip():
            shared.gui_print(f"历史记录：{line.strip()}", "loss")
    shared.gui_print("=" * 65 + "\n", "sys")


async def fetch_rank_and_games(connection, puuid):
    solo = flex = "未定级"
    games = []
    try:
        rank_response = await connection.request(
            "get", f"/lol-ranked/v1/ranked-stats/{puuid}"
        )
        if rank_response.status == 200:
            solo, flex = parse_ranks((await rank_response.json()).get("queues", []))

        history_response = await connection.request(
            "get",
            f"/lol-match-history/v1/products/lol/{puuid}/matches?begIndex=0&endIndex=20",
        )
        if history_response.status == 200:
            games = extract_games(await history_response.json())
    except Exception:
        pass
    return solo, flex, games


def cache_players(players):
    for player in players:
        shared.LAST_MATCH_PLAYERS_DICT[player["display_name"]] = {
            "name": player["display_name"],
            "champ": player["champ_name"],
            "kda_str": player["kda_str"],
            "mode": shared.CURRENT_GAME_MODE,
        }
    shared.update_blacklist(
        [
            f"{player['name']}({player['champ']})"
            for player in shared.LAST_MATCH_PLAYERS_DICT.values()
        ]
    )


def champion_id(player):
    """兼容客户端把英雄 ID 返回为数字或字符串。"""
    try:
        return int(player.get("championId") or 0)
    except (TypeError, ValueError):
        return 0


def update_position_targets(my_team, enemy_team):
    """用双方英雄名更新快捷发送的五个位置目标。"""
    targets = {}
    for side, team in (("己方", my_team), ("敌方", enemy_team)):
        selected_players = [player for player in team if champion_id(player)]
        for position, player in assign_team_positions(selected_players).items():
            selected_champion_id = champion_id(player)
            champion_name = (
                shared.CHAMPION_DICT.get(selected_champion_id)
                or player.get("championName")
                or f"英雄{selected_champion_id}"
            )
            if champion_name:
                targets[f"{side}{position}"] = champion_name

    changed = False
    for key, value in targets.items():
        config_key = f"目标_{key}"
        if shared.CURRENT_CONFIG.get(config_key) != value:
            shared.CURRENT_CONFIG[config_key] = value
            changed = True

    if changed:
        shared.save_config()
    if targets:
        shared.update_targets(targets)
    if changed:
        summary = " | ".join(f"{key}:{value}" for key, value in targets.items())
        shared.gui_print(f"已更新位置目标：{summary}", "success")
    return bool(targets)


def update_targets_from_champ_select(session):
    """选人会话对自定义局更可靠，优先用它提前更新目标。"""
    return update_position_targets(
        session.get("myTeam", []),
        session.get("theirTeam", []),
    )


def player_is_current(player, current_summoner):
    """自定义局可能不返回 puuid，依次使用可用的身份字段匹配。"""
    identity_fields = (
        ("puuid", "puuid"),
        ("summonerId", "summonerId"),
        ("accountId", "accountId"),
        ("summonerInternalName", "summonerInternalName"),
        ("summonerInternalName", "internalName"),
    )
    for player_field, current_field in identity_fields:
        player_value = player.get(player_field)
        current_value = current_summoner.get(current_field)
        if player_value not in (None, "", 0) and str(player_value) == str(current_value):
            return True
    return False


def relative_teams(team_one, team_two, current_summoner):
    if any(player_is_current(player, current_summoner) for player in team_one):
        return team_one, team_two
    if any(player_is_current(player, current_summoner) for player in team_two):
        return team_two, team_one
    # 无身份字段时仍保留客户端顺序，并输出诊断信息，避免静默失败。
    shared.gui_print("未能确认所在队伍，暂按客户端队伍顺序填入。", "loss")
    return team_one, team_two


async def fetch_ready_gameflow_session(connection, attempts=8, interval=2):
    """等待进入游戏初期尚未就绪的队伍与英雄数据。"""
    last_session = {}
    for attempt in range(attempts):
        response = await connection.request("get", "/lol-gameflow/v1/session")
        if response.status == 200:
            last_session = await response.json()
            game_data = last_session.get("gameData", {})
            team_one = game_data.get("teamOne") or last_session.get("teamOne") or []
            team_two = game_data.get("teamTwo") or last_session.get("teamTwo") or []
            players = team_one + team_two
            if players and all(champion_id(player) for player in players):
                return last_session, team_one, team_two
        if attempt + 1 < attempts:
            await asyncio.sleep(interval)

    game_data = last_session.get("gameData", {})
    return (
        last_session,
        game_data.get("teamOne") or last_session.get("teamOne") or [],
        game_data.get("teamTwo") or last_session.get("teamTwo") or [],
    )


async def update_current_game_info(connection):
    try:
        res = await connection.request('get', '/lol-gameflow/v1/session')
        if res.status == 200:
            data = await res.json()
            g_data = data.get('gameData', {})
            q_id = g_data.get('queue', {}).get('id', 0)
            
            shared.CURRENT_GAME_ID = g_data.get('gameId', 0)
            
            if q_id == 0 and g_data.get('isCustomGame'):
                shared.CURRENT_GAME_MODE = "自定义模式"
            else:
                shared.CURRENT_GAME_MODE = QUEUE_NAMES.get(q_id, "特殊模式")
    except Exception as exc:
        shared.gui_print(f"当前对局信息读取失败: {exc}", "loss")

@connector.ready
async def connect(connection):
    global lobby_processed, is_processing, GLOBAL_CONN, GLOBAL_LOOP
    GLOBAL_CONN = connection
    GLOBAL_LOOP = asyncio.get_running_loop()
    lobby_processed = False
    is_processing = False

    shared.gui_print("已连接英雄联盟客户端。", "success")
    if not HAS_PINYIN:
        shared.gui_print("未安装 pypinyin，拼音搜索不可用。", "loss")

    try:
        champ_res = await connection.request(
            "get", "/lol-game-data/assets/v1/champion-summary.json"
        )
        if champ_res.status == 200:
            summary_data = await champ_res.json()
            valid_champs = [champ for champ in summary_data if champ.get("id", -1) > 0]

            shared.gui_print("正在加载英雄数据...", "sys")
            sem = asyncio.Semaphore(15)

            async def fetch_champ(cid):
                async with sem:
                    res = await connection.request(
                        "get", f"/lol-game-data/assets/v1/champions/{cid}.json"
                    )
                    if res.status == 200:
                        return await res.json()
                    return None

            results = await asyncio.gather(
                *[fetch_champ(champ["id"]) for champ in valid_champs]
            )

            loaded_champs = []
            for champ in results:
                if champ:
                    c_obj = ChampionObj(
                        champ["id"],
                        champ.get("name", ""),
                        champ.get("title", ""),
                        champ.get("alias", ""),
                    )
                    loaded_champs.append(c_obj)

            loaded_champs.sort(key=lambda x: x.display_name)
            shared.ALL_CHAMPS[:] = loaded_champs
            shared.CHAMPION_DICT.clear()
            shared.CHAMPION_DICT.update({c.id: c.name for c in loaded_champs})
            shared.CHAMPION_NAME_TO_ID.clear()
            shared.CHAMPION_NAME_TO_ID.update(
                {champ.display_name: champ.id for champ in loaded_champs}
            )

            shared.update_champions()
            shared.gui_print("英雄数据加载完成。", "success")
    except Exception as exc:
        shared.gui_print(f"英雄数据加载失败: {exc}", "loss")

    try:
        phase_response = await connection.request("get", "/lol-gameflow/v1/gameflow-phase")
        if phase_response.status == 200:
            current_phase = await phase_response.json()
            if current_phase == "InProgress":
                asyncio.create_task(fetch_full_game_stats(connection))
            elif current_phase == "ChampSelect":
                session_response = await connection.request(
                    "get", "/lol-champ-select/v1/session"
                )
                if session_response.status == 200:
                    update_targets_from_champ_select(await session_response.json())
    except Exception as exc:
        shared.gui_print(f"当前游戏阶段读取失败: {exc}", "loss")

async def fetch_and_print_stats(connection, session_data):
    await update_current_game_info(connection)
    
    shared.LAST_MATCH_PLAYERS_DICT.clear()
    shared.update_blacklist([])

    my_team = session_data.get('myTeam', [])
    if not my_team:
        return False

    mode = shared.CURRENT_CONFIG["查询模式"]
    match_count_limit = shared.CURRENT_CONFIG["查询场数"]
    target_queues = queue_ids_for_mode(mode)

    shared.gui_clear()
    shared.gui_print("="*75, "sys")
    shared.gui_print(
        f"正在读取队友战绩（模式：{mode}，最近 {match_count_limit} 场）...",
        "info",
    )
    shared.gui_print("="*75, "sys")

    async def get_player_info(player):
        summoner_id = player.get('summonerId')
        if not summoner_id or summoner_id == 0:
            return None
        try:
            res = await connection.request('get', f'/lol-summoner/v1/summoners/{summoner_id}')
            if res.status == 200:
                data = await res.json()
                return {
                    'summoner_id': summoner_id,
                    'puuid': data.get('puuid'),
                    'display_name': player_name(data, f"玩家_{summoner_id}")
                }
        except Exception:
            pass
        return None

    team_players = [p for p in await asyncio.gather(*[get_player_info(p) for p in my_team]) if p]
    if not team_players:
        return False

    for player in team_players:
        warn_if_blacklisted(player['display_name'], "你的队伍中")

    summ_to_champ = {
        player.get('summonerId'): shared.CHAMPION_DICT.get(
            player.get('championId', 0), "未知/未选"
        )
        for player in my_team
    }

    data_results = await asyncio.gather(
        *[fetch_rank_and_games(connection, player['puuid']) for player in team_players]
    )

    player_data_list = []
    for player, (solo, flex, games) in zip(team_players, data_results):
        summary = summarize_games(
            games,
            shared.CHAMPION_DICT,
            target_queues=target_queues,
            limit=match_count_limit,
            include_mode=mode == "全部",
        )

        player_data_list.append({
            'display_name': player['display_name'],
            'champ_name': summ_to_champ.get(player['summoner_id'], "未知/未选"),
            'solo_rank': solo,
            'flex_rank': flex,
            'matches_display': summary['matches'],
            'kda': summary['kda'],
            'kda_str': "暂无(选人中)",
            'recent_win_rate': summary['win_rate'],
        })

    if player_data_list:
        player_data_list.sort(key=lambda x: x['kda'], reverse=True)
        
        cache_players(player_data_list)

        titles = shared.CURRENT_CONFIG.get(
            "KDA称号", ["S", "A", "B", "C", "D"]
        ).copy()
        while len(titles) < len(player_data_list):
            titles.append("未分级")

        shared.gui_print("\n本局队伍 KDA 排名", "rank")
        shared.gui_print("-" * 65, "sys")
        for i, p_data in enumerate(player_data_list):
            title = titles[i]
            shared.gui_print(
                f" {i + 1}. [{title}] {p_data['display_name']} | "
                f"KDA: {p_data['kda']:>5.2f} | "
                f"胜率: {p_data['recent_win_rate']:>5.1f}%",
                "rank",
            )
        shared.gui_print("-" * 65, "sys")

        for i, p_data in enumerate(player_data_list):
            shared.gui_print(
                f"玩家ID: {p_data['display_name']}  "
                f"(近期KDA: {p_data['kda']:.2f} | "
                f"近期胜率: {p_data['recent_win_rate']:.1f}%)",
                "player",
            )
            shared.gui_print(f"   单双排: {p_data['solo_rank']}", "rank")
            shared.gui_print(f"   灵活排位: {p_data['flex_rank']}", "rank")
            
            if p_data['matches_display']:
                shared.gui_print_matches(p_data['matches_display'])
            else:
                shared.gui_print(f"   最近战绩: 官方可见记录中无 [{mode}] 对局", "sys")
                
            shared.gui_print("-" * 75, "sys")

        shared.gui_print("="*75 + "\n", "sys")
        return True
    return False

async def fetch_full_game_stats(connection):
    shared.gui_print("\n" + "="*75, "sys")
    shared.gui_print("游戏已进入加载或对局阶段，正在读取双方信息...", "info")
    
    await update_current_game_info(connection)

    shared.LAST_MATCH_PLAYERS_DICT.clear()
    shared.update_blacklist([])

    try:
        session_data, team_one, team_two = await fetch_ready_gameflow_session(connection)
        if not team_one and not team_two:
            shared.gui_print("对局队伍数据尚未就绪，未能自动填入目标。", "loss")
            return

        my_summoner_res = await connection.request('get', '/lol-summoner/v1/current-summoner')
        my_data = await my_summoner_res.json() if my_summoner_res.status == 200 else {}

        my_team, enemy_team = relative_teams(team_one, team_two, my_data)
        if not update_position_targets(my_team, enemy_team):
            shared.gui_print("已取得队伍数据，但英雄信息仍为空。", "loss")

        player_semaphore = asyncio.Semaphore(5)

        async def process_player(player, team_name):
            async with player_semaphore:
                puuid = player.get('puuid')
                summoner_id = player.get('summonerId')
                name = f"玩家_{summoner_id}"
                try:
                    response = await connection.request(
                        'get', f'/lol-summoner/v1/summoners/{summoner_id}'
                    )
                    if response.status == 200:
                        name = player_name(await response.json(), name)
                except Exception:
                    pass

                warn_if_blacklisted(name, team_name)
                solo, flex, games = await fetch_rank_and_games(connection, puuid)
                summary = summarize_games(games, shared.CHAMPION_DICT)
                return {
                    "team_name": team_name,
                    "display_name": name,
                    "champ_name": shared.CHAMPION_DICT.get(
                        player.get('championId'), "未知"
                    ),
                    "kda_str": "暂无(游戏中)",
                    "rank_text": f"单:{solo}/灵:{flex}",
                    "kda_text": f"{summary['kda']:.2f}",
                    "winrate_text": f"{summary['win_rate']:.1f}%",
                    "recent_game_ids": summary['recent_game_ids'],
                }

        async def process_team(team, team_name):
            return await asyncio.gather(
                *[process_player(player, team_name) for player in team]
            )

        my_team_data, enemy_team_data = await asyncio.gather(
            process_team(my_team, "我方"),
            process_team(enemy_team, "敌方"),
        )

        cache_players(my_team_data + enemy_team_data)

        my_premades = analyze_premades(my_team_data)
        enemy_premades = analyze_premades(enemy_team_data)

        my_premades_champs = premade_champions(my_team_data, my_premades)
        enemy_premades_champs = premade_champions(enemy_team_data, enemy_premades)

        if my_premades_champs:
            shared.gui_print(
                f"发现我方组队玩家: {format_groups(my_premades_champs)}",
                "info",
            )
        if enemy_premades_champs:
            shared.gui_print(
                f"发现敌方组队玩家: {format_groups(enemy_premades_champs)}",
                "loss",
            )

        my_tree_data = format_tree_rows(my_team_data, my_premades)
        enemy_tree_data = format_tree_rows(enemy_team_data, enemy_premades)

        shared.update_tree(my_tree_data, enemy_tree_data)

        shared.gui_print("双方对局信息读取完成。", "success")

    except Exception as exc:
        shared.gui_print(f"双方对局信息读取失败: {exc}", "loss")

async def fetch_eog_stats(connection):
    try:
        res = await connection.request('get', '/lol-end-of-game/v1/eog-stats-block')
        if res.status == 200:
            data = await res.json()
            game_id = data.get('gameId', 0)
            
            if shared.CURRENT_GAME_ID != 0 and game_id != 0 and game_id != shared.CURRENT_GAME_ID:
                return

            players = []
            shared.LAST_MATCH_PLAYERS_DICT.clear()
            for team in data.get('teams', []):
                for player in team.get('players', []):
                    name = player_name(player, "")
                    if not name:
                        continue
                    stats = player.get('stats', {})
                    players.append(
                        {
                            "display_name": name,
                            "champ_name": shared.CHAMPION_DICT.get(
                                player.get('championId', 0), "未知"
                            ),
                            "kda_str": (
                                f"{stats.get('CHAMPIONS_KILLED', 0)}/"
                                f"{stats.get('NUM_DEATHS', 0)}/"
                                f"{stats.get('ASSISTS', 0)}"
                            ),
                        }
                    )

            if players:
                cache_players(players)
                shared.gui_print("对局结算数据已更新。", "success")
    except Exception as exc:
        shared.gui_print(f"结算数据读取失败: {exc}", "loss")

async def manual_requery_task():
    global lobby_processed, is_processing
    if not GLOBAL_CONN:
        shared.gui_print("尚未连接到客户端，无法查询。", "loss")
        return
    if is_processing:
        shared.gui_print("数据处理中，请稍后重试。", "sys")
        return
        
    is_processing = True
    try:
        res = await GLOBAL_CONN.request('get', '/lol-champ-select/v1/session')
        if res.status == 200:
            session_data = await res.json()
            valid_found = await fetch_and_print_stats(GLOBAL_CONN, session_data)
            if valid_found:
                lobby_processed = True
        else:
            shared.gui_print("重新查询只能在英雄选择界面使用。", "loss")
    except Exception as exc:
        shared.gui_print(f"查询请求失败: {exc}", "loss")
    finally:
        is_processing = False

@connector.ws.register(
    "/lol-champ-select/v1/session", event_types=("CREATE", "UPDATE")
)
async def champ_select_changed(connection, event):
    global lobby_processed, is_processing
    session_data = event.data
    update_targets_from_champ_select(session_data)
    
    # 将获取到的英雄池，赋值给全局变量给 GUI 轮询使用
    bench_champs = session_data.get("benchChampions", [])
    bench_ids = []
    for champ in bench_champs:
        if isinstance(champ, dict):
            bench_ids.append(champ.get("championId"))
        elif isinstance(champ, int):
            bench_ids.append(champ)
            
    shared.CURRENT_BENCH = bench_ids
        
    if lobby_processed or is_processing:
        return
    is_processing = True
    try:
        if await fetch_and_print_stats(connection, session_data):
            lobby_processed = True
    finally:
        is_processing = False

@connector.ws.register("/lol-champ-select/v1/session", event_types=("DELETE",))
async def champ_select_ended(connection, event):
    global lobby_processed, is_processing, executed_actions
    lobby_processed = False
    is_processing = False
    executed_actions.clear()
    
    # 离开选人界面时，清空工具上的英雄席
    shared.CURRENT_BENCH = []
        
    shared.gui_print("\n[-] 已离开选人界面，准备好迎接下一局...\n", "sys")

async def execute_bench_swap(champ_id):
    """直接调用接口绕过前端冷却"""
    if not GLOBAL_CONN:
        return
    try:
        res = await GLOBAL_CONN.request(
            "post", 
            f"/lol-champ-select/v1/session/bench/swap/{champ_id}"
        )
        if res.status in [200, 204]:
            champ_name = shared.CHAMPION_DICT.get(champ_id, str(champ_id))
            shared.gui_print(f"已成功抢到英雄: {champ_name}", "success")
    except Exception as exc:
        shared.gui_print(f"抢夺英雄请求失败: {exc}", "loss")


@connector.ws.register("/lol-gameflow/v1/gameflow-phase", event_types=("UPDATE",))
async def gameflow_changed(connection, event):
    phase = event.data
    if phase == "InProgress":
        await asyncio.sleep(3)
        await fetch_full_game_stats(connection)
    elif phase == "EndOfGame":
        await asyncio.sleep(2)
        await fetch_eog_stats(connection)
        shared.clear_tree()
    elif phase == "None":
        shared.clear_tree()


@connector.ws.register("/lol-matchmaking/v1/ready-check", event_types=("UPDATE",))
async def auto_accept_match(connection, event):
    if not shared.CURRENT_CONFIG.get("自动接受"):
        return
    ready_check = event.data
    if (
        ready_check.get("state") == "InProgress"
        and ready_check.get("playerResponse") == "None"
    ):
        res = await connection.request(
            "post", "/lol-matchmaking/v1/ready-check/accept"
        )
        if res.status == 204:
            shared.gui_print("已接受对局。", "success")


@connector.ws.register(
    "/lol-champ-select/v1/session", event_types=("CREATE", "UPDATE")
)
async def auto_pick_ban(connection, event):
    global executed_actions
    session = event.data
    local_player_cell_id = session.get("localPlayerCellId")
    phase = session.get("timer", {}).get("phase", "")

    if phase == "PLANNING":
        return

    for action_group in session.get("actions", []):
        for action in action_group:
            action_id = action.get("id")
            if action_id in executed_actions or action.get("completed"):
                continue

            is_local_action = action.get("actorCellId") == local_player_cell_id
            if is_local_action and action.get("isInProgress"):
                action_type = action.get("type")
                target_name = None

                if action_type == "ban" and shared.CURRENT_CONFIG.get("自动禁用"):
                    target_name = shared.CURRENT_CONFIG.get("禁用英雄")
                elif action_type == "pick" and shared.CURRENT_CONFIG.get("自动选择"):
                    target_name = shared.CURRENT_CONFIG.get("选择英雄")

                if target_name:
                    target_id = shared.CHAMPION_NAME_TO_ID.get(target_name)
                    if target_id:
                        executed_actions.add(action_id)
                        asyncio.create_task(
                            execute_action(
                                connection,
                                action_id,
                                target_id,
                                target_name,
                                action_type,
                            )
                        )


async def execute_action(connection, action_id, target_id, target_name, action_type):
    try:
        payload = {"championId": int(target_id), "completed": True}
        res = await connection.request(
            "patch",
            f"/lol-champ-select/v1/session/actions/{action_id}",
            json=payload,
        )
        if res.status in [200, 204]:
            verb = "已自动禁用" if action_type == "ban" else "已自动选择"
            color = "success" if action_type == "pick" else "loss"
            shared.gui_print(f"{verb}: {target_name}", color)
        else:
            executed_actions.remove(action_id)
    except Exception:
        executed_actions.discard(action_id)


def run_lcu_in_background():
    connector.start()