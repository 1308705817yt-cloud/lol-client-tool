import unittest
from unittest.mock import patch

import lcu_core
import match_utils
import quick_chat
import shared
from utils import ChampionObj


class LcuHelperTests(unittest.TestCase):
    def test_parse_ranks(self):
        solo, flex = match_utils.parse_ranks(
            [
                {"queueType": "RANKED_SOLO_5x5", "tier": "GOLD", "division": "II"},
                {"queueType": "RANKED_FLEX_SR", "tier": "MASTER", "division": "I"},
            ]
        )
        self.assertEqual(solo, "黄金 II")
        self.assertEqual(flex, "超凡大师")

    def test_extract_games_accepts_both_lcu_shapes(self):
        games = [{"gameId": 1}]
        self.assertEqual(match_utils.extract_games({"games": games}), games)
        self.assertEqual(match_utils.extract_games({"games": {"games": games}}), games)

    def test_summarize_games_filters_and_limits(self):
        games = [
            {
                "gameId": 1,
                "queueId": 420,
                "participants": [
                    {
                        "championId": 10,
                        "stats": {"kills": 5, "deaths": 2, "assists": 3, "win": True},
                    }
                ],
            },
            {
                "gameId": 2,
                "queueId": 440,
                "participants": [
                    {
                        "championId": 11,
                        "stats": {"kills": 1, "deaths": 4, "assists": 1, "win": False},
                    }
                ],
            },
        ]
        summary = match_utils.summarize_games(
            games,
            {10: "英雄甲", 11: "英雄乙"},
            target_queues=[420],
            limit=1,
        )

        self.assertEqual(summary["matches"], ["胜-英雄甲(5/2/3)"])
        self.assertEqual(summary["kda"], 4)
        self.assertEqual(summary["win_rate"], 100)
        self.assertEqual(summary["recent_game_ids"], {1})

    def test_assign_team_positions_uses_roles_then_fills_missing_slots(self):
        players = [
            {"name": "辅助", "selectedPosition": "UTILITY"},
            {"name": "上单", "assignedPosition": "TOP"},
            {"name": "未知位置"},
            {"name": "打野", "teamPosition": "JUNGLE"},
            {"name": "中单", "individualPosition": "MIDDLE"},
        ]
        assigned = match_utils.assign_team_positions(players)

        self.assertEqual(assigned["上单"]["name"], "上单")
        self.assertEqual(assigned["打野"]["name"], "打野")
        self.assertEqual(assigned["中单"]["name"], "中单")
        self.assertEqual(assigned["AD"]["name"], "未知位置")
        self.assertEqual(assigned["辅助"]["name"], "辅助")

    def test_assign_team_positions_falls_back_to_team_order(self):
        players = [{"index": index} for index in range(5)]
        assigned = match_utils.assign_team_positions(players)
        self.assertEqual(
            [assigned[position]["index"] for position in match_utils.POSITIONS],
            [0, 1, 2, 3, 4],
        )

    def test_position_targets_are_written_and_sent_to_ui(self):
        my_team = [
            {"championId": 1, "selectedPosition": "TOP"},
            {"championId": 2},
        ]
        enemy_team = [
            {"championId": 3, "selectedPosition": "MIDDLE"},
            {"championId": 4},
        ]
        config = {}
        champion_names = {1: "英雄甲", 2: "英雄乙", 3: "英雄丙", 4: "英雄丁"}

        with (
            patch.object(shared, "CURRENT_CONFIG", config),
            patch.object(shared, "CHAMPION_DICT", champion_names),
            patch.object(shared, "save_config") as save_config,
            patch.object(shared, "update_targets") as update_targets,
            patch.object(shared, "gui_print"),
        ):
            lcu_core.update_position_targets(my_team, enemy_team)

        self.assertEqual(config["目标_己方上单"], "英雄甲")
        self.assertEqual(config["目标_己方打野"], "英雄乙")
        self.assertEqual(config["目标_敌方中单"], "英雄丙")
        self.assertEqual(config["目标_敌方上单"], "英雄丁")
        save_config.assert_called_once()
        update_targets.assert_called_once()

    def test_champ_select_targets_ignore_unselected_slots(self):
        session = {
            "myTeam": [
                {"championId": 0, "assignedPosition": "TOP"},
                {"championId": "2", "assignedPosition": "JUNGLE"},
            ],
            "theirTeam": [{"championId": 3, "assignedPosition": "MIDDLE"}],
        }
        config = {}
        with (
            patch.object(shared, "CURRENT_CONFIG", config),
            patch.object(shared, "CHAMPION_DICT", {2: "英雄乙", 3: "英雄丙"}),
            patch.object(shared, "save_config"),
            patch.object(shared, "update_targets"),
            patch.object(shared, "gui_print"),
        ):
            self.assertTrue(lcu_core.update_targets_from_champ_select(session))

        self.assertNotIn("目标_己方上单", config)
        self.assertEqual(config["目标_己方打野"], "英雄乙")
        self.assertEqual(config["目标_敌方中单"], "英雄丙")

    def test_relative_teams_supports_custom_games_without_puuid(self):
        team_one = [{"summonerId": 10}]
        team_two = [{"summonerId": 20}]
        my_team, enemy_team = lcu_core.relative_teams(
            team_one, team_two, {"summonerId": "20"}
        )
        self.assertIs(my_team, team_two)
        self.assertIs(enemy_team, team_one)

        internal_name_team = [{"summonerInternalName": "custom-player"}]
        my_team, _ = lcu_core.relative_teams(
            internal_name_team, team_two, {"internalName": "custom-player"}
        )
        self.assertIs(my_team, internal_name_team)


class UtilityTests(unittest.TestCase):
    def test_champion_display_and_search_fields(self):
        champion = ChampionObj(1, "测试英雄", "测试称号", "TestHero")
        self.assertEqual(champion.display_name, "测试称号 - 测试英雄 (TestHero)")
        self.assertIn("testhero", champion.search_keys)

    def test_split_text_preserves_content_and_limits(self):
        chunks = quick_chat._split_text("一二三四五六七八", 2, 3)
        self.assertEqual("".join(chunks), "一二三四五六七八")
        self.assertTrue(all(2 <= len(chunk) <= 3 for chunk in chunks[:-1]))
        self.assertLessEqual(len(chunks[-1]), 3)


if __name__ == "__main__":
    unittest.main()
