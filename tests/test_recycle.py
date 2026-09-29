from datetime import datetime, timedelta, timezone
from pathlib import Path

from agentfileclear.catalog import load_catalog
from agentfileclear.classify import classify_hits
from agentfileclear.installed import app_installed
import pytest

from agentfileclear.recycle import QuarantineError, isolate, list_trash, purge, quarantine_path
from agentfileclear.scan import collect_hits


def _cursor():
    return next(agent for agent in load_catalog() if agent.id == "cursor")


def test_purge_removes_only_expired_items(tmp_path: Path):
    cache = tmp_path / "Library" / "Application Support" / "Cursor" / "Cache"
    cache.mkdir(parents=True)
    (cache / "a.txt").write_bytes(b"abc")
    findings = classify_hits(collect_hits([_cursor()], home=tmp_path, os_name="darwin", use_env=False))
    past = datetime.now(timezone.utc) - timedelta(days=10)
    moved = isolate(
        [_cursor()],
        findings,
        home=tmp_path,
        os_name="darwin",
        keep_days=1,
        include_uninstall=False,
        now=past,
    )
    assert moved.moved
    assert not cache.exists()
    assert purge(tmp_path, "darwin", everything=False, now=past + timedelta(hours=1)) == []
    assert list_trash(tmp_path, "darwin")
    removed = purge(tmp_path, "darwin", everything=False)
    assert [item.original_path for item in removed] == [str(cache)]
    assert list_trash(tmp_path, "darwin") == []


def test_symlink_is_not_quarantined(tmp_path: Path):
    root = tmp_path / "Library" / "Application Support" / "Cursor"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.txt").write_text("x", encoding="utf-8")
    root.mkdir(parents=True)
    cache = root / "Cache"
    cache.symlink_to(outside, target_is_directory=True)
    findings = classify_hits(collect_hits([_cursor()], home=tmp_path, os_name="darwin", use_env=False))
    result = isolate(
        [_cursor()],
        findings,
        home=tmp_path,
        os_name="darwin",
        keep_days=7,
        include_uninstall=False,
    )
    assert result.moved == []
    with pytest.raises(QuarantineError):
        quarantine_path(
            cache,
            home=tmp_path,
            os_name="darwin",
            allowed_roots=[root],
            agent_id="cursor",
            agent_name="Cursor",
            category="cache",
            kind="temp",
            keep_days=7,
        )
    assert cache.is_symlink()
    assert (outside / "a.txt").read_text(encoding="utf-8") == "x"


def test_app_installed_uses_markers_not_data_dirs():
    home = Path("/tmp/agentclear-marker-home")

    def exists(path: Path) -> bool:
        return path.name == "Cursor.app"

    assert app_installed("cursor", home, "darwin", exists=exists, which=lambda _name: None, glob_hit=lambda _pattern: False)
    assert app_installed("kiro", home, "darwin", exists=lambda _path: False, which=lambda _name: None, glob_hit=lambda _pattern: False) is False
    assert app_installed("not-a-product", home, "darwin") is None
