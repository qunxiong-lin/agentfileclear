from agentfileclear.catalog import CatalogError, load_catalog

REQUIRED_IDS = {
    "cursor",
    "copilot",
    "claude-code",
    "claude-desktop",
    "codex",
    "chatgpt",
    "windsurf",
    "gemini-cli",
    "cline",
    "roo-code",
    "continue",
    "aider",
    "amazon-q",
    "jetbrains-ai",
    "zed",
    "trae",
    "lingma",
    "comate",
    "codegeex",
    "augment",
    "cody",
    "amp",
    "tabnine",
    "warp",
    "opencode",
    "kiro",
}


def test_catalog_covers_major_agents():
    agents = load_catalog()
    ids = [agent.id for agent in agents]
    assert len(ids) == len(set(ids))
    assert REQUIRED_IDS <= set(ids)


def test_each_agent_has_roots_on_every_os():
    placeholders = ("{home}", "{app_support}", "{data_home}", "{cache_home}")
    for agent in load_catalog():
        assert any(root.rules for root in agent.roots), agent.id
        for os_name in ("darwin", "linux", "win32"):
            assert any(os_name in root.os for root in agent.roots), (agent.id, os_name)
        for root in agent.roots:
            assert root.os
            assert any(token in root.path for token in placeholders), root.path


def test_catalog_rejects_nothing_on_reload():
    assert load_catalog()[0].id
    try:
        load_catalog()
    except CatalogError as exc:
        raise AssertionError(exc) from exc
