import glob
import importlib
import logging
from os.path import basename, dirname, isfile
import sys
from types import ModuleType

logger = logging.getLogger(__name__)

modules = glob.glob(dirname(__file__) + "/*.py")
__all__ = [
    basename(f)[:-3] for f in modules if isfile(f) and not basename(f).startswith("__")
]  # exclude __init__.py
plugin_names = __all__

_loaded_plugins: dict[str, ModuleType] = {}


def get_loaded_plugins(reload: bool = False) -> dict[str, ModuleType]:
    """Load and return all valid plugin modules. Cached after initial load unless reload=True.

    Ensures plugins are imported only ONCE across the entire application runtime
    (Ruleset, ToolRegistry, Man helper, TG commands menu) rather than repeated
    separate imports and duplicate warnings.
    """
    global _loaded_plugins, plugin_names

    if _loaded_plugins and not reload:
        return _loaded_plugins

    # Re-discover files if reloading or empty
    mods = glob.glob(dirname(__file__) + "/*.py")
    plugin_names = [
        basename(f)[:-3] for f in mods if isfile(f) and not basename(f).startswith("__")
    ]

    loaded = {}
    for name in plugin_names:
        full_mod_name = f"plugins.{name}"
        try:
            if reload and full_mod_name in sys.modules:
                mod = importlib.reload(sys.modules[full_mod_name])
            else:
                mod = sys.modules.get(full_mod_name) or importlib.import_module(full_mod_name)
            loaded[name] = mod
        except (ModuleNotFoundError, ImportError) as e:
            missing_mod = getattr(e, "name", None) or str(e)
            logger.error("!!!!!! %s 插件似乎缺少 %s module !!!!!!", name, missing_mod, exc_info=True)
        except Exception:
            logger.error("!!!!!! %s 插件导入失败 !!!!!!", name, exc_info=True)

    _loaded_plugins = loaded
    return _loaded_plugins
