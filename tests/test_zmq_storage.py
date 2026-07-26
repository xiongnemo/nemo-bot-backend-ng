import os
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from store.database import Database
from store.zmq_daemon import KVStorageDaemon
from store.zmq_client import ZmqStateStore


class TestZmqStorage(unittest.TestCase):
    def setUp(self):
        self.db_path = "data/test_zmq_storage.sqlite"
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass
        self.db = Database(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass
        # Clean up shm/wal files if any
        for ext in ["-shm", "-wal"]:
            p = self.db_path + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def test_daemon_and_client_basic(self):
        endpoint = "inproc://test-zmq-basic"
        daemon = KVStorageDaemon(endpoint=endpoint, db=self.db, max_cache_size=10)
        daemon.start(background=True)
        time.sleep(0.2)  # give ZMQ time to bind

        client = ZmqStateStore(endpoint=endpoint)
        try:
            self.assertTrue(client.ping())

            # Basic CRUD
            self.assertIsNone(client.get("test", "g", "k1"))
            client.set("test", "g", "k1", {"hello": "world"})
            self.assertEqual(client.get("test", "g", "k1"), {"hello": "world"})

            self.assertEqual(client.list_keys("test", "g"), ["k1"])
            self.assertEqual(client.list_all("test", "g"), {"k1": {"hello": "world"}})

            self.assertTrue(client.delete("test", "g", "k1"))
            self.assertFalse(client.delete("test", "g", "k1"))
            self.assertIsNone(client.get("test", "g", "k1"))

            # Convenience Wrappers
            client.set_plugin_config("demo_plugin", {"enabled": True, "limit": 10})
            self.assertEqual(client.get_plugin_config("demo_plugin"), {"enabled": True, "limit": 10})

            client.set_alias("天气", "weather")
            self.assertEqual(client.get_alias("天气"), "weather")
            self.assertEqual(client.list_aliases(), {"天气": "weather"})
            client.delete_alias("天气")
            self.assertIsNone(client.get_alias("天气"))
        finally:
            client.close()
            daemon.stop()

    def test_high_concurrency(self):
        endpoint = "inproc://test-zmq-conc"
        daemon = KVStorageDaemon(endpoint=endpoint, db=self.db, max_cache_size=500)
        daemon.start(background=True)
        time.sleep(0.2)

        client = ZmqStateStore(endpoint=endpoint)
        try:
            self.assertTrue(client.ping())

            def worker_task(worker_id: int):
                local_client = ZmqStateStore(endpoint=endpoint)
                try:
                    for i in range(50):
                        key = f"w{worker_id}_k{i}"
                        val = {"worker": worker_id, "idx": i, "timestamp": time.time()}
                        local_client.set("conc", "pool", key, val)
                        res = local_client.get("conc", "pool", key)
                        assert res == val, f"Mismatch for {key}: {res} != {val}"
                    return True
                finally:
                    local_client.close()

            # 20 concurrent workers executing 50 operations each = 1,000 total ops
            with ThreadPoolExecutor(max_workers=20) as pool:
                futures = [pool.submit(worker_task, w) for w in range(20)]
                results = [f.result() for f in futures]

            self.assertEqual(len(results), 20)
            self.assertTrue(all(results))

            # Verify all 1,000 keys were written accurately without lock conflicts
            all_keys = client.list_keys("conc", "pool")
            self.assertEqual(len(all_keys), 1000)
        finally:
            client.close()
            daemon.stop()

    def test_zmq_rocksdb_backend(self):
        endpoint = "inproc://test-zmq-rocksdb"
        rdb_path = "data/test_zmq_rdb"
        import shutil
        shutil.rmtree(rdb_path, ignore_errors=True)

        daemon = KVStorageDaemon(endpoint=endpoint, backend="rocksdb", rocksdb_path=rdb_path)
        daemon.start(background=True)
        time.sleep(0.2)

        client = ZmqStateStore(endpoint=endpoint)
        try:
            self.assertTrue(client.ping())
            client.set("plugin", "vision", "api_key", "secret-key")
            self.assertEqual(client.get("plugin", "vision", "api_key"), "secret-key")
            self.assertEqual(client.list_keys("plugin", "vision"), ["api_key"])
            self.assertTrue(client.delete("plugin", "vision", "api_key"))
            self.assertIsNone(client.get("plugin", "vision", "api_key"))
        finally:
            client.close()
            daemon.stop()
            if hasattr(daemon, "engine") and hasattr(daemon.engine, "destroy"):
                daemon.engine.destroy()
            shutil.rmtree(rdb_path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
