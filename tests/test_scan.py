import json
import os
from pathlib import Path

from agentfileclear.catalog import catalog_by_id
from agentfileclear.classify import classify_hits
from agentfileclear.models import Category
from agentfileclear.report import build_report, format_report, report_dict
from agentfileclear.scan import collect_hits


def _scan(home: Path, agent_ids: list[str]):
    catalog = catalog_by_id()
    hits = collect_hits(
        [catalog[agent_id] for agent_id in agent_ids],
        home=home,
        os_name="darwin",
        use_env=False,
    )
    return classify_hits(hits)


def test_claude_and_codeium_cache_rules(tmp_path: Path):
    claude = tmp_path / ".claude"
    for name in ("debug", "statsig", "telemetry", "todos", "tasks"):
        (claude / name).mkdir(parents=True)
        (claude / name / "a.txt").write_text("x", encoding="utf-8")
    codeium = tmp_path / ".codeium"
    (codeium / "code_tracker" / "active").mkdir(parents=True)
    (codeium / "code_tracker" / "active" / "a.txt").write_text("x", encoding="utf-8")
    (codeium / "context_state").mkdir()
    (codeium / "context_state" / "a.txt").write_text("x", encoding="utf-8")
    (codeium / "database").mkdir()
    (codeium / "database" / "a.txt").write_text("x", encoding="utf-8")

    findings = _scan(tmp_path, ["claude-code", "windsurf"])
    by_key = {(item.agent_id, item.relative_path): item for item in findings}

    assert by_key[("claude-code", "debug")].category == Category.log
    assert by_key[("claude-code", "debug")].keep is False
    assert by_key[("claude-code", "statsig")].category == Category.telemetry
    assert by_key[("claude-code", "telemetry")].keep is False
    assert by_key[("claude-code", "todos")].keep is True
    assert by_key[("claude-code", "tasks")].keep is True
    assert by_key[("windsurf", "code_tracker")].category == Category.cache
    assert by_key[("windsurf", "code_tracker")].keep is False
    assert by_key[("windsurf", "context_state")].keep is False
    assert by_key[("windsurf", "database")].keep is True
    assert ("windsurf", "windsurf") not in by_key


def test_project_slug_containing_token_is_not_a_secret(tmp_path: Path):
    projects = tmp_path / ".claude" / "projects"
    wallet = projects / "-Volumes-KINGSTON-TokenWallet"
    wallet.mkdir(parents=True)
    (wallet / "chat.jsonl").write_text("hello", encoding="utf-8")
    (tmp_path / ".claude" / "auth-token.json").write_text("{}", encoding="utf-8")

    findings = _scan(tmp_path, ["claude-code"])
    by_rel = {item.relative_path: item for item in findings}
    assert by_rel["projects"].category == Category.session
    assert by_rel["projects"].keep is True
    assert "密钥" not in by_rel["projects"].reason
    assert by_rel["auth-token.json"].category == Category.secret
    assert by_rel["auth-token.json"].keep is True


def test_codex_runtime_cache_is_cleanable_and_state_is_kept(tmp_path: Path):
    codex = tmp_path / ".codex"
    (codex / "plugins" / "cache").mkdir(parents=True)
    (codex / "plugins" / "cache" / "pkg").write_bytes(b"c" * 20)
    (codex / "plugins" / ".plugin-appserver").mkdir()
    (codex / "plugins" / ".plugin-appserver" / "bin").write_bytes(b"a" * 30)
    (codex / "logs_2.sqlite").write_bytes(b"l" * 10)
    (codex / "logs_2.sqlite-wal").write_bytes(b"w" * 4)
    (codex / "computer-use").mkdir()
    (codex / "computer-use" / "Codex Computer Use.app").mkdir()
    (codex / "state_5.sqlite").write_bytes(b"s" * 8)
    (codex / "skills").mkdir()

    findings = _scan(tmp_path, ["codex"])
    by_rel = {item.relative_path: item for item in findings}
    assert by_rel["plugins/cache"].category == Category.cache
    assert by_rel["plugins/cache"].keep is False
    assert by_rel["plugins/cache"].size_bytes == 20
    assert by_rel["plugins/.plugin-appserver"].keep is False
    assert by_rel["plugins/.plugin-appserver"].size_bytes == 30
    assert by_rel["logs_2.sqlite"].category == Category.log
    assert by_rel["logs_2.sqlite"].keep is False
    assert by_rel["logs_2.sqlite-wal"].category == Category.log
    assert by_rel["computer-use"].keep is True
    assert "不清理" in by_rel["computer-use"].reason
    assert by_rel["state_5.sqlite"].keep is True
    assert by_rel["skills"].keep is True
    assert "plugins" not in by_rel


def test_missing_root_is_skipped(tmp_path: Path):
    cursor = tmp_path / ".cursor"
    cursor.mkdir()
    (cursor / "logs").mkdir()
    (cursor / "logs" / "a.txt").write_bytes(b"hello")

    findings = _scan(tmp_path, ["cursor", "windsurf"])
    assert findings
    assert {item.agent_id for item in findings} == {"cursor"}
    assert all(Path(item.path).is_relative_to(cursor) for item in findings)


def test_directory_aggregate_ignores_escaped_symlink(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.txt").write_bytes(b"x" * 5000)

    root = tmp_path / "Library" / "Application Support" / "Cursor"
    cache = root / "Cache"
    (cache / "sub").mkdir(parents=True)
    (cache / "a.txt").write_bytes(b"a" * 100)
    (cache / "sub" / "b.txt").write_bytes(b"b" * 50)
    (cache / "leak").symlink_to(outside / "big.txt")
    (root / "escape").symlink_to(outside)
    (root / "Cookies").write_bytes(b"cookie")

    findings = _scan(tmp_path, ["cursor"])
    by_rel = {item.relative_path: item for item in findings}
    cache_hit = by_rel["Cache"]
    assert cache_hit.category == Category.cache
    assert cache_hit.is_dir
    assert cache_hit.keep is False
    assert cache_hit.size_bytes == 150
    assert "Cookies" not in by_rel
    assert "HTTP 缓存" in cache_hit.reason
    assert "escape" not in by_rel
    assert all("outside" not in item.path for item in findings)
    assert all(item.size_bytes != 5000 for item in findings)


def test_nested_transcripts_are_one_directory(tmp_path: Path):
    transcripts = tmp_path / ".cursor" / "projects" / "ws" / "agent-transcripts"
    transcripts.mkdir(parents=True)
    (transcripts / "a.jsonl").write_bytes(b"1234567890")
    (tmp_path / ".cursor" / "projects" / "ws" / "other.txt").write_bytes(b"y" * 999)
    chats = tmp_path / ".cursor" / "chats"
    chats.mkdir()
    (chats / "c.txt").write_bytes(b"12345")

    findings = _scan(tmp_path, ["cursor"])
    by_rel = {item.relative_path: item for item in findings}
    transcript = by_rel["projects/ws/agent-transcripts"]
    assert transcript.category == Category.session
    assert transcript.size_bytes == 10
    assert transcript.keep is True
    assert "对话记录" in transcript.reason
    assert "chats" not in by_rel
    assert "projects" not in by_rel
    assert "projects/ws/other.txt" not in by_rel


def test_shared_root_does_not_emit_unmatched(tmp_path: Path):
    idea = tmp_path / "Library" / "Application Support" / "JetBrains" / "IntelliJIdea2026.1"
    (idea / "junie").mkdir(parents=True)
    (idea / "junie" / "a.txt").write_bytes(b"z" * 20)
    (idea / "system").mkdir()
    (idea / "system" / "huge.txt").write_bytes(b"q" * 8000)

    findings = _scan(tmp_path, ["jetbrains-ai"])
    assert [item.relative_path for item in findings] == ["IntelliJIdea2026.1/junie"]
    assert findings[0].category == Category.user_data
    assert findings[0].keep is True
    assert findings[0].size_bytes == 20


def test_secret_child_is_kept_and_report_json_is_stable(tmp_path: Path):
    mystery = tmp_path / ".codex" / "mystery"
    mystery.mkdir(parents=True)
    (mystery / "auth.json").write_text("TOPSECRET-TOKEN", encoding="utf-8")
    (tmp_path / ".codex" / "notes.txt").write_text("hello", encoding="utf-8")
    (tmp_path / ".codex" / "sessions").mkdir()
    (tmp_path / ".codex" / "sessions" / "s.txt").write_bytes(b"abcd")

    findings = _scan(tmp_path, ["codex"])
    by_rel = {item.relative_path: item for item in findings}
    assert by_rel["mystery"].category == Category.secret
    assert by_rel["mystery"].keep is True
    assert by_rel["notes.txt"].category == Category.unknown
    assert by_rel["notes.txt"].keep is True
    assert by_rel["sessions"].category == Category.session
    assert "TOPSECRET-TOKEN" not in by_rel["mystery"].reason

    report = build_report(findings)
    text = format_report(report)
    assert "密钥" in text
    assert "保留" in text
    assert "会话" in text
    payload = report_dict(report)
    assert set(payload) == {"findings", "summary", "total_count", "total_size_bytes"}
    finding = next(item for item in payload["findings"] if item["relative_path"] == "sessions")
    assert finding["category"] == "session"
    assert finding["category_label"] == "会话"
    assert set(finding) == {
        "agent_id",
        "agent_name",
        "path",
        "relative_path",
        "category",
        "category_label",
        "keep",
        "size_bytes",
        "mtime",
        "is_dir",
            "reason",
            "confidence",
            "source",
            "uninstall_residue",
        }
    assert payload["total_count"] == len(payload["findings"])
    assert "TOPSECRET-TOKEN" not in json.dumps(payload)


def test_cursor_keeps_newest_cached_data_and_state_db(tmp_path: Path):
    app = tmp_path / "Library" / "Application Support" / "Cursor"
    cached = app / "CachedData"
    old = cached / "old-hash"
    new = cached / "new-hash"
    old.mkdir(parents=True)
    new.mkdir()
    (old / "a.bin").write_bytes(b"1234")
    (new / "b.bin").write_bytes(b"12")
    os.utime(old, (1, 1_000))
    os.utime(new, (1, 2_000_000_000))
    (app / "Local Storage").mkdir()
    (app / "Local Storage" / "big.bin").write_bytes(b"z" * 8000)
    state = app / "User" / "globalStorage"
    state.mkdir(parents=True)
    (state / "state.vscdb").write_bytes(b"db")

    home_cursor = tmp_path / ".cursor"
    (home_cursor / "mcp.json").parent.mkdir(parents=True)
    (home_cursor / "mcp.json").write_text("{}", encoding="utf-8")

    findings = _scan(tmp_path, ["cursor"])
    by_rel = {item.relative_path: item for item in findings}
    assert by_rel["CachedData/old-hash"].category == Category.cache
    assert by_rel["CachedData/old-hash"].keep is False
    assert by_rel["CachedData/old-hash"].size_bytes == 4
    assert by_rel["CachedData/new-hash"].category == Category.user_data
    assert by_rel["CachedData/new-hash"].keep is True
    assert "CachedData" not in by_rel
    assert "Local Storage" not in by_rel
    assert by_rel["User/globalStorage/state.vscdb"].keep is True
    assert "保护路径" in by_rel["User/globalStorage/state.vscdb"].reason
    assert by_rel["mcp.json"].category == Category.secret
    assert by_rel["mcp.json"].keep is True
