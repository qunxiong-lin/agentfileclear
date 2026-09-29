import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from agentfileclear.models import AgentSpec, PathRule

CATALOG_DIR = Path(__file__).resolve().parent
AGENTS_DIR = CATALOG_DIR / "agents"
PRESETS_PATH = CATALOG_DIR / "presets.json"

_RULES = TypeAdapter(list[PathRule])


class CatalogError(ValueError):
    pass


def load_presets() -> dict[str, list[PathRule]]:
    try:
        raw = json.loads(PRESETS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f"无法读取规则预设: {exc}") from exc
    presets: dict[str, list[PathRule]] = {}
    for name, rules in raw.items():
        try:
            presets[name] = _RULES.validate_python(rules)
        except ValidationError as exc:
            raise CatalogError(f"预设 {name} 无效: {exc}") from exc
    return presets


def load_catalog() -> list[AgentSpec]:
    presets = load_presets()
    agents: list[AgentSpec] = []
    seen: set[str] = set()
    paths = sorted(AGENTS_DIR.glob("*.json"))
    if not paths:
        raise CatalogError(f"产品目录为空: {AGENTS_DIR}")
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogError(f"无法读取 {path.name}: {exc}") from exc
        for root in raw.get("roots", []):
            preset_name = root.get("preset")
            if not preset_name:
                continue
            preset = presets.get(preset_name)
            if preset is None:
                raise CatalogError(f"{path.name} 使用了未知预设 {preset_name}")
            extra = root.get("rules", [])
            root["rules"] = [rule.model_dump() for rule in preset] + extra
        try:
            agent = AgentSpec.model_validate(raw)
        except ValidationError as exc:
            raise CatalogError(f"{path.name} 无效: {exc}") from exc
        if agent.id in seen:
            raise CatalogError(f"重复的产品 id: {agent.id}")
        seen.add(agent.id)
        agents.append(agent)
    return agents


def catalog_by_id() -> dict[str, AgentSpec]:
    return {agent.id: agent for agent in load_catalog()}
