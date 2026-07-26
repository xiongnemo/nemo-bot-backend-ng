import os
import shutil
import unittest
from store.database import Database
from store.engines.sqlite_engine import SqliteKVEngine
from store.engines.rocksdb_engine import RocksDBEngine


class TestKVEngines(unittest.TestCase):
    def setUp(self):
        self.sqlite_path = "data/test_engines.sqlite"
        self.rocksdb_path = "data/test_engines_rocksdb"
        if os.path.exists(self.sqlite_path):
            try:
                os.remove(self.sqlite_path)
            except Exception:
                pass
        if os.path.exists(self.rocksdb_path):
            shutil.rmtree(self.rocksdb_path, ignore_errors=True)

        self.sqlite_db = Database(self.sqlite_path)

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

    def _test_engine_crud(self, engine):
        self.assertIsNone(engine.get("ns", "g", "k1"))
        self.assertEqual(engine.get("ns", "g", "k1", default="fallback"), "fallback")

        engine.set("ns", "g", "k1", {"foo": "bar", "num": 123})
        self.assertEqual(engine.get("ns", "g", "k1"), {"foo": "bar", "num": 123})

        engine.set("ns", "g", "k2", [1, 2, 3])
        engine.set("ns", "other", "k3", "secret")

        keys_g = engine.list_keys("ns", "g")
        self.assertEqual(sorted(keys_g), ["k1", "k2"])

        all_g = engine.list_all("ns", "g")
        self.assertEqual(all_g, {"k1": {"foo": "bar", "num": 123}, "k2": [1, 2, 3]})

        self.assertTrue(engine.delete("ns", "g", "k1"))
        self.assertFalse(engine.delete("ns", "g", "k1"))
        self.assertIsNone(engine.get("ns", "g", "k1"))
        self.assertEqual(engine.list_keys("ns", "g"), ["k2"])

    def test_sqlite_engine(self):
        engine = SqliteKVEngine(self.sqlite_db)
        self._test_engine_crud(engine)
        engine.close()

    def test_rocksdb_engine(self):
        engine = RocksDBEngine(self.rocksdb_path)
        try:
            self._test_engine_crud(engine)
        finally:
            engine.destroy()


if __name__ == "__main__":
    unittest.main()
