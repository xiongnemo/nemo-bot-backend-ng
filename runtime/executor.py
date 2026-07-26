"""
Executor — two-tier worker pool for nemo-bot-backend-ng.

ProcessPoolExecutor  (plugin_pool):
    Runs sync plugin code in isolated worker processes.  Workers pre-load
    all plugins at fork/spawn time so subsequent calls are fast.

ThreadPoolExecutor  (dispatch_pool):
    Runs routing, agent loops, and delivery on the main process.  This
    keeps the Flask HTTP thread free (instant ACK) while still allowing
    the agent runner to call into the plugin pool synchronously.
"""

from __future__ import annotations

import importlib
import logging
import os
import traceback
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor

logger = logging.getLogger(__name__)


# ======================================================================
# Functions that run INSIDE a worker process
# ======================================================================

def _init_plugin_worker():
    """Called once per worker process on startup — preloads all plugins."""
    try:
        import plugins  # noqa: F401
        for name in plugins.plugin_names:
            importlib.import_module(f"plugins.{name}")
        logger.info(
            "Worker %s: preloaded %d plugins",
            os.getpid(), len(plugins.plugin_names),
        )
    except Exception:
        logger.error("Worker init failed:\n%s", traceback.format_exc())


# Global cache for smart hot-reloading within the worker process
_plugin_cache_meta: dict[str, dict[str, float | str]] = {}

def _run_plugin_in_worker(
    message_dict: dict,
    plugin_name: str,
    plugin_config: dict,
) -> dict:
    """
    Execute a single plugin inside a worker process.

    Uses RecordingMessage so the plugin's reply()/send() calls are
    captured as Actions instead of hitting the network.
    Returns a serialisable dict that can cross the process boundary.
    """
    from core.recording_message import RecordingMessage
    import hashlib

    msg = RecordingMessage(message_dict)
    msg.request.command = plugin_name
    mod = importlib.import_module(f"plugins.{plugin_name}")

    # Smart hot-reloading based on mtime and sha1
    try:
        if hasattr(mod, "__file__") and mod.__file__:
            file_path = mod.__file__
            current_mtime = os.path.getmtime(file_path)
            
            cache = _plugin_cache_meta.get(plugin_name, {})
            if not cache or current_mtime > cache.get("mtime", 0):
                # mtime changed or first time loading, check hash
                with open(file_path, "rb") as f:
                    current_sha1 = hashlib.sha1(f.read()).hexdigest()
                
                if cache and current_sha1 != cache.get("sha1"):
                    logger.info("Plugin %s has been hot-reloaded! (sha1: %s)", plugin_name, current_sha1[:8])
                    importlib.reload(mod)
                    
                _plugin_cache_meta[plugin_name] = {"mtime": current_mtime, "sha1": current_sha1}
    except Exception as e:
        logger.warning("Failed to check hot-reload status for plugin %s: %s", plugin_name, e)
        # Fallback to unconditional reload if we can't check
        importlib.reload(mod)

    try:
        mod.bot_execute(msg, plugin_config)
        return {
            "ok": True,
            "actions": [a.to_dict() for a in msg.outbox],
            "payload": msg.payload,
            "error": "",
            "config": plugin_config,  # may have been mutated by the plugin
        }
    except Exception as e:
        traceback.print_exc()
        return {
            "ok": False,
            "actions": [],
            "payload": None,
            "error": f"{type(e).__name__}: {e}",
            "config": plugin_config,
        }


# ======================================================================
# Executor — the public API
# ======================================================================

class Executor:
    def __init__(
        self,
        plugin_workers: int | None = None,
        dispatch_workers: int = 8,
    ):
        pw = plugin_workers or max(2, os.cpu_count() or 2)
        logger.info(
            "Starting Executor: %d plugin workers, %d dispatch threads",
            pw, dispatch_workers,
        )
        self.plugin_pool = ProcessPoolExecutor(
            max_workers=pw,
            initializer=_init_plugin_worker,
            max_tasks_per_child=200,
        )
        self.dispatch_pool = ThreadPoolExecutor(
            max_workers=dispatch_workers,
            thread_name_prefix="dispatch",
        )

    # ------------------------------------------------------------------
    # Plugin execution (process pool)
    # ------------------------------------------------------------------

    def submit_plugin(
        self,
        message_dict: dict,
        plugin_name: str,
        plugin_config: dict,
    ) -> Future:
        """Non-blocking: submit a plugin job to the process pool."""
        return self.plugin_pool.submit(
            _run_plugin_in_worker, message_dict, plugin_name, plugin_config,
        )

    def run_plugin_sync(
        self,
        message_dict: dict,
        plugin_name: str,
        plugin_config: dict,
        timeout: float = 60.0,
    ) -> dict:
        """
        Blocking: execute a plugin and wait for the result.
        Used by the agent tool executor (runs in a dispatch thread,
        blocks until the plugin worker finishes).
        """
        future = self.submit_plugin(message_dict, plugin_name, plugin_config)
        return future.result(timeout=timeout)

    # ------------------------------------------------------------------
    # Dispatch (thread pool)
    # ------------------------------------------------------------------

    def submit_dispatch(self, fn, *args, **kwargs) -> Future:
        """Submit a function to the dispatch thread pool."""
        return self.dispatch_pool.submit(fn, *args, **kwargs)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self, wait: bool = True):
        logger.info("Shutting down executor...")
        self.dispatch_pool.shutdown(wait=False)
        self.plugin_pool.shutdown(wait=wait)
        logger.info("Executor shutdown complete.")
