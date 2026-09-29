from pathlib import Path

import pytest

from agentfileclear.llm import (
    LlmConfigError,
    LlmVerdict,
    _build_agent,
    apply_verdicts,
    findings_for_llm,
    load_skill_instructions,
    payload_for_llm,
    refine_with_llm,
)
from agentfileclear.models import Category, Finding


def _finding(relative: str, category: Category, *, agent_id: str = "cursor", path: str | None = None) -> Finding:
    return Finding(
        agent_id=agent_id,
        agent_name="Cursor",
        path=path or f"/tmp/demo/{relative}",
        relative_path=relative,
        category=category,
        keep=category != Category.cache,
        size_bytes=4,
        is_dir=False,
        reason="测试",
    )


def test_llm_payload_skips_secrets_and_known_rules(tmp_path: Path):
    secret = _finding(
        "auth.json",
        Category.unknown,
        path=str(tmp_path / "auth.json"),
    )
    cookies = _finding("Cookies", Category.secret, path=str(tmp_path / "Cookies"))
    cache = _finding("Cache", Category.cache)
    notes = _finding("notes.txt", Category.unknown, path=str(tmp_path / "notes.txt"))
    payload = payload_for_llm([secret, cookies, cache, notes])
    assert payload == [
        {
            "path": "notes.txt",
            "agent_id": "cursor",
            "size_bytes": 4,
            "is_dir": False,
        }
    ]
    encoded = str(payload)
    assert "auth.json" not in encoded
    assert str(tmp_path) not in encoded
    assert [item.relative_path for item in findings_for_llm([secret, cookies, cache, notes])] == ["notes.txt"]


def test_verdict_does_not_change_secret_or_other_agent(tmp_path: Path):
    notes = _finding("notes.txt", Category.unknown, path=str(tmp_path / "notes.txt"))
    other = _finding("notes.txt", Category.unknown, agent_id="codex", path=str(tmp_path / "other" / "notes.txt"))
    secret = _finding("mcp.json", Category.secret, path=str(tmp_path / "mcp.json"))
    updated = apply_verdicts(
        [notes, other, secret],
        [
            LlmVerdict(
                path="notes.txt",
                agent_id="cursor",
                category=Category.cache,
                keep=False,
                confidence=1.4,
                reason="像是缓存",
            ),
            LlmVerdict(
                path="mcp.json",
                agent_id="cursor",
                category=Category.cache,
                keep=False,
                confidence=0.2,
                reason="不该生效",
            ),
        ],
    )
    assert updated[0].category == Category.cache
    assert updated[0].keep is False
    assert updated[0].source == "llm"
    assert updated[0].confidence == 1.0
    assert updated[1].category == Category.unknown
    assert updated[1].source == "rule"
    assert updated[2].category == Category.secret
    assert updated[2].source == "rule"


def test_refine_does_not_call_model_without_candidates():
    secret = _finding("auth.json", Category.secret, path="/tmp/auth.json")

    def runner(model: str, payload: list[dict]) -> list[LlmVerdict]:
        raise AssertionError((model, payload))

    assert refine_with_llm([secret], model="test:model", runner=runner) == [secret]


def test_model_receives_skill_not_a_bare_prompt():
    instructions = load_skill_instructions()
    assert "未识别路径分类" in instructions
    assert "name: classify-residue" not in instructions
    assert "不要打开文件" in instructions

    seen: dict[str, str] = {}

    class FakeAgent:
        def __init__(self, model, output_type=None, instructions=None, result_type=None, system_prompt=None):
            seen["text"] = instructions or system_prompt or ""

    _build_agent(FakeAgent, "test:model")
    assert seen["text"] == instructions


def test_skill_forces_session_and_user_data_to_stay(tmp_path: Path):
    session = _finding("history.jsonl", Category.unknown, path=str(tmp_path / "history.jsonl"))
    updated = apply_verdicts(
        [session],
        [
            LlmVerdict(
                path="history.jsonl",
                agent_id="cursor",
                category=Category.session,
                keep=False,
                confidence=0.9,
                reason="像是历史",
            )
        ],
    )
    assert updated[0].category == Category.session
    assert updated[0].keep is True
    assert updated[0].source == "llm"


def test_refine_requires_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AGENTCLEAR_MODEL", raising=False)
    notes = _finding("notes.txt", Category.unknown)
    with pytest.raises(LlmConfigError):
        refine_with_llm([notes], runner=lambda model, payload: [])
