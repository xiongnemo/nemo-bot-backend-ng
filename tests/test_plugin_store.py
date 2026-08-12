import os
import unittest
from unittest import mock

import config as cfg_mod
from store.plugin_store import get_plugin_state_store, WorkerStateStore, MISCONFIG_WARNING


class TestPluginStoreTopology(unittest.TestCase):
    """Regression tests for the read/write split-brain: plugins must read
    the same canonical store the main process writes to."""

    def setUp(self):
        self.path = "data/test_plugin_store.sqlite"
        self._cleanup()
        self._saved_cfg = dict(cfg_mod.backend_config)
        cfg_mod.backend_config["database"] = {"path": self.path}

    def tearDown(self):
        cfg_mod.backend_config.clear()
        cfg_mod.backend_config.update(self._saved_cfg)
        self._cleanup()

    def _cleanup(self):
        for ext in ["", "-shm", "-wal"]:
            p = self.path + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def test_storage_disabled_direct_sqlite_no_warning(self):
        cfg_mod.backend_config["storage"] = {"enabled": False}
        store, warning = get_plugin_state_store()
        self.assertIsNone(warning)
        self.assertIsInstance(store, WorkerStateStore)

    def test_sqlite_backend_inproc_is_fine(self):
        cfg_mod.backend_config["storage"] = {"enabled": True, "backend": "sqlite",
                                             "endpoint": "inproc://nemo-kv"}
        store, warning = get_plugin_state_store()
        self.assertIsNone(warning)

    def test_rocksdb_inproc_warns_loudly(self):
        cfg_mod.backend_config["storage"] = {"enabled": True, "backend": "rocksdb",
                                             "endpoint": "inproc://nemo-kv"}
        store, warning = get_plugin_state_store()
        self.assertEqual(warning, MISCONFIG_WARNING)

    def test_tcp_daemon_down_warns(self):
        cfg_mod.backend_config["storage"] = {"enabled": True, "backend": "rocksdb",
                                             "endpoint": "tcp://127.0.0.1:59999"}
        store, warning = get_plugin_state_store()
        self.assertIsNotNone(warning)
        self.assertIn("无响应", warning)

    def test_worker_store_never_delegates(self):
        # even if the (forked) worker inherited a broken ZMQ client in
        # runtime.context, WorkerStateStore must not delegate to it
        from runtime import context
        cfg_mod.backend_config["storage"] = {"enabled": False}
        store, _ = get_plugin_state_store()

        class BrokenZmq:
            _is_zmq_client = True

            def get(self, *a, **k):
                raise RuntimeError("inproc socket across fork")

        saved = context.state_store
        context.state_store = BrokenZmq()
        try:
            store.set("t", "s", "k", 42)
            self.assertEqual(store.get("t", "s", "k"), 42)  # no delegation, no crash
        finally:
            context.state_store = saved

    def test_main_write_plugin_read_consistency(self):
        """The reported bug: main-process adjust succeeded but plugin reads
        kept returning the initial score. With storage disabled both sides
        must hit the same SQLite file."""
        cfg_mod.backend_config["storage"] = {"enabled": False}
        from store.database import Database
        from store.state_store import StateStore
        from store.affinity_store import AffinityStore

        main_store = AffinityStore(StateStore(Database(self.path)))   # main process
        main_store.adjust("U1", 40, "seed", source="system")

        plugin_ss, warning = get_plugin_state_store()                 # worker process
        self.assertIsNone(warning)
        plugin_view = AffinityStore(plugin_ss).get_state("U1")
        self.assertEqual(plugin_view["score"], 40.0)                  # not the default!


if __name__ == "__main__":
    unittest.main()
