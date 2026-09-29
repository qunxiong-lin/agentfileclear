import os
import sys
from pathlib import Path


def resolve_home() -> Path:
    return Path.home()


def current_os() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform == "win32":
        return "win32"
    # Linux 以及其他 Unix 都走 XDG 目录。
    return "linux"


def template_map(home: Path, os_name: str, *, use_env: bool = True) -> dict[str, str]:
    if os_name == "darwin":
        app_support = home / "Library" / "Application Support"
        data_home = app_support
        cache_home = home / "Library" / "Caches"
    elif os_name == "win32":
        appdata = os.environ.get("APPDATA") if use_env else None
        local = os.environ.get("LOCALAPPDATA") if use_env else None
        app_support = Path(appdata) if appdata else home / "AppData" / "Roaming"
        data_home = Path(local) if local else home / "AppData" / "Local"
        cache_home = data_home
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME") if use_env else None
        xdg_data = os.environ.get("XDG_DATA_HOME") if use_env else None
        xdg_cache = os.environ.get("XDG_CACHE_HOME") if use_env else None
        app_support = Path(xdg_config) if xdg_config else home / ".config"
        data_home = Path(xdg_data) if xdg_data else home / ".local" / "share"
        cache_home = Path(xdg_cache) if xdg_cache else home / ".cache"
    return {
        "home": str(home),
        "app_support": str(app_support),
        "data_home": str(data_home),
        "cache_home": str(cache_home),
    }


def expand_path(template: str, home: Path, os_name: str, *, use_env: bool = True) -> Path:
    rendered = template
    for key, value in template_map(home, os_name, use_env=use_env).items():
        rendered = rendered.replace("{" + key + "}", value)
    if "{" in rendered or "}" in rendered:
        raise ValueError(f"路径模板有未知占位符: {template}")
    return Path(rendered)
