import json
import os
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from agentfileclear.classify import is_secret_path
from agentfileclear.models import Category, Finding

SKILL_PATH = Path(__file__).resolve().parent / "skills" / "classify-residue" / "SKILL.md"
# 这些类别即使用模型判成可清理，也强制保留。
ALWAYS_KEEP = frozenset(
    {
        Category.session,
        Category.backup,
        Category.config,
        Category.secret,
        Category.user_data,
        Category.unknown,
    }
)


class LlmConfigError(RuntimeError):
    pass


class LlmVerdict(BaseModel):
    path: str
    agent_id: str
    category: Category
    keep: bool
    confidence: float = 0.5
    reason: str


Runner = Callable[[str, list[dict]], list[LlmVerdict]]


class LlmBatch(BaseModel):
    verdicts: list[LlmVerdict]


def findings_for_llm(findings: list[Finding]) -> list[Finding]:
    selected: list[Finding] = []
    for finding in findings:
        if finding.category != Category.unknown:
            continue
        if is_secret_path(Path(finding.relative_path)):
            continue
        selected.append(finding)
    return selected


def payload_for_llm(findings: list[Finding]) -> list[dict]:
    return [
        {
            "path": finding.relative_path,
            "agent_id": finding.agent_id,
            "size_bytes": finding.size_bytes,
            "is_dir": finding.is_dir,
        }
        for finding in findings_for_llm(findings)
    ]


def apply_verdicts(findings: list[Finding], verdicts: list[LlmVerdict]) -> list[Finding]:
    allowed = {(item["agent_id"], item["path"]) for item in payload_for_llm(findings)}
    chosen: dict[tuple[str, str], LlmVerdict] = {}
    for verdict in verdicts:
        key = (verdict.agent_id, verdict.path)
        if key in allowed and key not in chosen:
            chosen[key] = verdict
    updated: list[Finding] = []
    for finding in findings:
        verdict = chosen.get((finding.agent_id, finding.relative_path))
        if verdict is None:
            updated.append(finding)
            continue
        category = verdict.category
        keep = True if category in ALWAYS_KEEP else verdict.keep
        confidence = min(1.0, max(0.0, float(verdict.confidence)))
        updated.append(
            finding.model_copy(
                update={
                    "category": category,
                    "keep": keep,
                    "confidence": confidence,
                    "reason": verdict.reason,
                    "source": "llm",
                }
            )
        )
    return updated


def load_skill_instructions() -> str:
    """读取分类 skill 正文。没有这份说明时，不把路径交给模型。"""
    try:
        text = SKILL_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise LlmConfigError(f"无法读取分类 skill: {SKILL_PATH}") from exc
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4 :]
    text = text.strip()
    if not text:
        raise LlmConfigError(f"分类 skill 是空的: {SKILL_PATH}")
    return text


def _build_agent(agent_cls, model: str):
    instructions = load_skill_instructions()
    try:
        return agent_cls(model, output_type=LlmBatch, instructions=instructions)
    except TypeError:
        return agent_cls(model, result_type=LlmBatch, system_prompt=instructions)


def _read_output(result):
    if hasattr(result, "output"):
        return result.output
    return result.data


def default_runner(model: str, payload: list[dict]) -> list[LlmVerdict]:
    from pydantic_ai import Agent

    agent = _build_agent(Agent, model)
    result = agent.run_sync("请分类以下条目。\n" + json.dumps(payload, ensure_ascii=False))
    output = _read_output(result)
    if isinstance(output, LlmBatch):
        return output.verdicts
    return LlmBatch.model_validate(output).verdicts


def refine_with_llm(
    findings: list[Finding],
    *,
    model: str | None = None,
    runner: Runner | None = None,
) -> list[Finding]:
    chosen = model or os.environ.get("AGENTCLEAR_MODEL")
    if not chosen:
        raise LlmConfigError("未设置环境变量 AGENTCLEAR_MODEL，例如 openai:gpt-4.1-mini")
    payload = payload_for_llm(findings)
    if not payload:
        return findings
    run = runner or default_runner
    verdicts: list[LlmVerdict] = []
    for offset in range(0, len(payload), 40):
        verdicts.extend(run(chosen, payload[offset : offset + 40]))
    return apply_verdicts(findings, verdicts)
