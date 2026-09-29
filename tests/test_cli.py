import json
from pathlib import Path

import pytest

from agentfileclear.cli import main
from agentfileclear.llm import LlmVerdict
from agentfileclear.models import Category


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("agentfileclear.cli.resolve_home", lambda: tmp_path)
    monkeypatch.setattr("agentfileclear.cli.current_os", lambda: "darwin")
    monkeypatch.delenv("AGENTCLEAR_MODEL", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    return tmp_path


def _cursor_fixture(home: Path) -> None:
    cache = home / "Library" / "Application Support" / "Cursor" / "Cache"
    cache.mkdir(parents=True)
    (cache / "a.txt").write_bytes(b"abc")
    (home / ".cursor").mkdir()
    (home / ".cursor" / "notes.txt").write_text("note", encoding="utf-8")


def test_agents_marks_installed_roots(home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr("agentfileclear.cli.app_installed", lambda *args, **kwargs: None)
    _cursor_fixture(home)
    assert main(["agents"]) == 0
    text = capsys.readouterr().out
    assert "已安装  Cursor (cursor)" in text
    assert "未安装  Windsurf (windsurf)" in text
    assert "[存在]" in text
    assert "[缺失]" in text


def test_scan_json_and_unknown_agent(home: Path, capsys: pytest.CaptureFixture[str]):
    _cursor_fixture(home)
    target = home / "report.json"
    assert main(["scan", "--agent", "cursor", "--json", str(target)]) == 0
    text = capsys.readouterr().out
    assert "缓存" in text
    assert "未识别" not in text
    assert "只读扫描，未修改任何文件" in text
    data = json.loads(target.read_text(encoding="utf-8"))
    categories = {item["category"] for item in data["findings"]}
    assert categories == {"cache"}
    assert all(item["category_label"] for item in data["findings"])
    assert data["summary"][0]["agent_id"] == "cursor"

    code = main(["scan", "--agent", "not-a-product"])
    captured = capsys.readouterr()
    assert code == 2
    assert "未知产品" in captured.err


def test_scan_llm_without_model_keeps_rule_report(home: Path, capsys: pytest.CaptureFixture[str]):
    _cursor_fixture(home)
    assert main(["scan", "--agent", "cursor", "--llm"]) == 2
    captured = capsys.readouterr()
    assert "缓存" in captured.out
    assert "AGENTCLEAR_MODEL" in captured.err


def test_scan_llm_uses_runner_for_unknown_only(home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    codex = home / ".codex"
    (codex / "sessions").mkdir(parents=True)
    (codex / "notes.txt").write_text("note", encoding="utf-8")
    (codex / "auth.json").write_text("secret", encoding="utf-8")
    seen: list[dict] = []

    def runner(model: str, payload: list[dict]) -> list[LlmVerdict]:
        assert model == "test:model"
        seen.extend(payload)
        return [
            LlmVerdict(
                path=item["path"],
                agent_id=item["agent_id"],
                category=Category.log,
                keep=False,
                confidence=0.8,
                reason="像是日志",
            )
            for item in payload
        ]

    def fake(findings, model=None, runner=None):
        from agentfileclear.llm import refine_with_llm as real

        return real(findings, model="test:model", runner=runner_impl)

    runner_impl = runner
    monkeypatch.setattr("agentfileclear.cli.refine_with_llm", fake)
    assert main(["scan", "--agent", "codex", "--llm"]) == 0
    text = capsys.readouterr().out
    assert "日志" in text
    assert [item["path"] for item in seen] == ["notes.txt"]


def test_agents_marks_uninstall_when_app_is_gone(home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr("agentfileclear.cli.app_installed", lambda *args, **kwargs: False)
    _cursor_fixture(home)
    assert main(["agents"]) == 0
    text = capsys.readouterr().out
    assert "卸载残留  Cursor (cursor)" in text
    assert "未安装  Windsurf (windsurf)" in text


def test_clean_quarantines_cache_and_restores_original_path(home: Path, capsys: pytest.CaptureFixture[str]):
    _cursor_fixture(home)
    settings = home / "Library" / "Application Support" / "Cursor" / "User" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"a": 1}', encoding="utf-8")
    assert main(["clean", "--agent", "cursor", "--days", "7"]) == 0
    cache = home / "Library" / "Application Support" / "Cursor" / "Cache"
    assert not cache.exists()
    assert settings.read_text(encoding="utf-8") == '{"a": 1}'
    assert "已隔离" in capsys.readouterr().out

    assert main(["trash"]) == 0
    assert "还剩" in capsys.readouterr().out
    assert main(["restore", "--all"]) == 0
    assert (cache / "a.txt").read_bytes() == b"abc"
    assert "已放回原位置" in capsys.readouterr().out
    assert main(["trash"]) == 0
    assert "回收站是空的" in capsys.readouterr().out


def test_restore_does_not_overwrite_existing_file(home: Path, capsys: pytest.CaptureFixture[str]):
    _cursor_fixture(home)
    assert main(["clean", "--agent", "cursor", "--days", "3"]) == 0
    cache = home / "Library" / "Application Support" / "Cursor" / "Cache"
    cache.mkdir()
    (cache / "a.txt").write_bytes(b"new")
    assert main(["restore", "--all"]) == 1
    assert (cache / "a.txt").read_bytes() == b"new"
    text = capsys.readouterr().out
    assert "未覆盖" in text


def test_clean_requires_a_retention_choice(home: Path, capsys: pytest.CaptureFixture[str]):
    _cursor_fixture(home)
    with pytest.raises(SystemExit) as missing:
        main(["clean", "--agent", "cursor"])
    assert missing.value.code == 2
    assert main(["clean", "--agent", "cursor", "--days", "0"]) == 2
    cache = home / "Library" / "Application Support" / "Cursor" / "Cache"
    assert cache.is_dir()


def test_purge_keeps_unexpired_items(home: Path, capsys: pytest.CaptureFixture[str]):
    _cursor_fixture(home)
    assert main(["clean", "--agent", "cursor", "--keep"]) == 0
    assert main(["purge"]) == 0
    text = capsys.readouterr().out
    assert "没有到期项" in text
    cache = home / "Library" / "Application Support" / "Cursor" / "Cache"
    assert not cache.exists()
    assert main(["purge", "--all"]) == 0
    assert "已清空" in capsys.readouterr().out
    assert not cache.exists()


def test_uninstall_residue_keeps_secrets_and_restores(home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    monkeypatch.setattr("agentfileclear.recycle.app_installed", lambda *args, **kwargs: False)
    root = home / "Library" / "Application Support" / "Cursor"
    (root / "Cache").mkdir(parents=True)
    (root / "Cache" / "a.txt").write_bytes(b"abc")
    (root / "User").mkdir(parents=True)
    (root / "User" / "settings.json").write_text("{}", encoding="utf-8")
    dot = home / ".cursor"
    (dot / "plans").mkdir(parents=True)
    (dot / "plans" / "a.md").write_text("plan", encoding="utf-8")
    (dot / "mcp.json").write_text("secret", encoding="utf-8")

    assert main(["clean", "--agent", "cursor", "--days", "14", "--uninstall"]) == 0
    assert not (root / "User" / "settings.json").exists()
    assert not (dot / "plans" / "a.md").exists()
    assert (dot / "mcp.json").read_text(encoding="utf-8") == "secret"
    assert "密钥文件留在原处" in capsys.readouterr().out

    assert main(["restore", "--all"]) == 0
    assert (root / "Cache" / "a.txt").read_bytes() == b"abc"
    assert (root / "User" / "settings.json").read_text(encoding="utf-8") == "{}"
    assert (dot / "plans" / "a.md").read_text(encoding="utf-8") == "plan"
    assert (dot / "mcp.json").read_text(encoding="utf-8") == "secret"
