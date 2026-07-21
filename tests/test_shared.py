import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

import shared


class ConfigPersistenceTests(unittest.TestCase):
    def test_load_config_discards_removed_or_unknown_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = os.path.join(temp_dir, "config.json")
            with open(config_file, "w", encoding="utf-8") as file:
                json.dump({"查询场数": 10, "已删除功能": "旧数据"}, file)

            with (
                patch.object(shared, "CONFIG_FILE", config_file),
                patch.object(shared, "_CONFIG_NEEDS_REWRITE", False),
            ):
                config = shared.load_config()

            self.assertEqual(config["查询场数"], 10)
            self.assertNotIn("已删除功能", config)

    def test_save_config_writes_valid_json_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = os.path.join(temp_dir, "config.json")
            config = {"查询模式": "全部", "查询场数": 8}

            with (
                patch.object(shared, "BASE_DIR", temp_dir),
                patch.object(shared, "CONFIG_FILE", config_file),
                patch.object(shared, "CURRENT_CONFIG", config),
            ):
                shared.save_config()

            with open(config_file, "r", encoding="utf-8") as file:
                self.assertEqual(json.load(file), config)

            leftovers = [name for name in os.listdir(temp_dir) if name.endswith(".tmp")]
            self.assertEqual(leftovers, [])

    def test_concurrent_saves_do_not_corrupt_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = os.path.join(temp_dir, "config.json")
            config = {"句子库": "测试\n内容", "拆字发送开关": True}

            with (
                patch.object(shared, "BASE_DIR", temp_dir),
                patch.object(shared, "CONFIG_FILE", config_file),
                patch.object(shared, "CURRENT_CONFIG", config),
            ):
                workers = [threading.Thread(target=shared.save_config) for _ in range(8)]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join()

            with open(config_file, "r", encoding="utf-8") as file:
                self.assertEqual(json.load(file), config)


if __name__ == "__main__":
    unittest.main()
