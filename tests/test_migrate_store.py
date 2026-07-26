import os
import shutil
import unittest
from store.database import Database
from store.engines.sqlite_engine import SqliteKVEngine
from store.engines.rocksdb_engine import RocksDBEngine
from scripts.migrate_store import migrate_sqlite_to_rocksdb


class TestMigrateStore(unittest.TestCase):
    def setUp(self):
        self.sqlite_path = "data/test_migration.sqlite"
        self.rocksdb_path = "data/test_migration_rocksdb"
        if os.path.exists(self.sqlite_path):
            try:
                os.remove(self.sqlite_path)
            except Exception:
                pass
        if os.path.exists(self.rocksdb_path):
            shutil.rmtree(self.rocksdb_path, ignore_errors=True)

    def tearDown(self):
        if os.path.exists(self.sqlite_path):
            try:
                os.remove(self.sqlite_path)
            except Exception:
                pass
        for ext in ["-shm", "-wal"]:
            p = self.sqlite_path + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        if os.path.exists(self.rocksdb_path):
            shutil.rmtree(self.rocksdb_path, ignore_errors=True)

    def test_migration_accuracy(self):
        db = Database(self.sqlite_path)
        sqlite_engine = SqliteKVEngine(db)

        # Populate 50 mock records across multiple namespaces and scopes
        for i in range(20):
            sqlite_engine.set("plugin_config", "vision", f"param_{i}", {"enabled": True, "val": i})
        for i in range(15):
            sqlite_engine.set("alias", "global", f"cmd_{i}", f"target_cmd_{i}")
        for i in range(15):
            sqlite_engine.set("user_link", "telegram", f"user_{i}", [1000 + i, "active"])

        sqlite_engine.close()

        # Run migration script
        migrated_count = migrate_sqlite_to_rocksdb(self.sqlite_path, self.rocksdb_path)
        self.assertEqual(migrated_count, 50)

        # Verify target RocksDB engine
        rocksdb_engine = RocksDBEngine(self.rocksdb_path)
        try:
            self.assertEqual(rocksdb_engine.get("plugin_config", "vision", "param_5"), {"enabled": True, "val": 5})
            self.assertEqual(rocksdb_engine.get("alias", "global", "cmd_10"), "target_cmd_10")
            self.assertEqual(rocksdb_engine.get("user_link", "telegram", "user_14"), [1014, "active"])

            vision_keys = rocksdb_engine.list_keys("plugin_config", "vision")
            self.assertEqual(len(vision_keys), 20)
            self.assertIn("param_0", vision_keys)
            self.assertIn("param_19", vision_keys)

            alias_all = rocksdb_engine.list_all("alias", "global")
            self.assertEqual(len(alias_all), 15)
            self.assertEqual(alias_all["cmd_0"], "target_cmd_0")
        finally:
            rocksdb_engine.destroy()


if __name__ == "__main__":
    unittest.main()
