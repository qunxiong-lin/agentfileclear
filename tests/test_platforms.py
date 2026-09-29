import pytest

from agentfileclear.catalog import catalog_by_id
from agentfileclear.classify import classify_hits
from agentfileclear.models import Category
from agentfileclear.paths import expand_path
from agentfileclear.scan import collect_hits


def test_path_templates_match_each_platform(tmp_path):
    assert expand_path("{app_support}/Cursor", tmp_path, "darwin", use_env=False) == (
        tmp_path / "Library" / "Application Support" / "Cursor"
    )
    assert expand_path("{app_support}/Cursor", tmp_path, "linux", use_env=False) == (
        tmp_path / ".config" / "Cursor"
    )
    assert expand_path("{app_support}/Cursor", tmp_path, "win32", use_env=False) == (
        tmp_path / "AppData" / "Roaming" / "Cursor"
    )
    assert expand_path("{data_home}/JetBrains", tmp_path, "linux", use_env=False) == (
        tmp_path / ".local" / "share" / "JetBrains"
    )
    assert expand_path("{data_home}/JetBrains", tmp_path, "win32", use_env=False) == (
        tmp_path / "AppData" / "Local" / "JetBrains"
    )
    assert expand_path("{cache_home}/lingma", tmp_path, "darwin", use_env=False) == (
        tmp_path / "Library" / "Caches" / "lingma"
    )


def test_linux_honors_xdg_directories(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    assert expand_path("{app_support}/Cursor", tmp_path, "linux") == tmp_path / "cfg" / "Cursor"
    assert expand_path("{data_home}/zed", tmp_path, "linux") == tmp_path / "data" / "zed"
    assert expand_path("{cache_home}/lingma", tmp_path, "linux") == tmp_path / "cache" / "lingma"


def test_windows_honors_appdata(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert expand_path("{app_support}/Cursor", tmp_path, "win32") == tmp_path / "Roaming" / "Cursor"
    assert expand_path("{data_home}/JetBrains", tmp_path, "win32") == tmp_path / "Local" / "JetBrains"


@pytest.mark.parametrize(
    ("os_name", "parts"),
    [
        ("darwin", ("Library", "Application Support", "Cursor")),
        ("linux", (".config", "Cursor")),
        ("win32", ("AppData", "Roaming", "Cursor")),
    ],
)
def test_cursor_cache_is_found_on_each_os(tmp_path, os_name: str, parts: tuple[str, ...]):
    cache = tmp_path.joinpath(*parts, "Cache")
    cache.mkdir(parents=True)
    (cache / "a.txt").write_bytes(b"abc")
    other = tmp_path / "Library" / "Application Support" / "Cursor" / "Cache" / "nope.txt"
    if os_name != "darwin":
        other.parent.mkdir(parents=True)
        other.write_bytes(b"zzzz")

    hits = collect_hits(
        [catalog_by_id()["cursor"]],
        home=tmp_path,
        os_name=os_name,
        use_env=False,
    )
    findings = classify_hits(hits)
    caches = [item for item in findings if item.relative_path == "Cache"]
    assert len(caches) == 1
    assert caches[0].category == Category.cache
    assert caches[0].keep is False
    assert caches[0].size_bytes == 3
