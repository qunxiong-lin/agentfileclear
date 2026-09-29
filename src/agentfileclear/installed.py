"""判断智能体程序是否还在。数据目录还在、程序已经不在，就是卸载残留。"""

import shutil
from dataclasses import dataclass
from pathlib import Path

from agentfileclear.models import AgentSpec
from agentfileclear.paths import expand_path

_ALL = frozenset({"darwin", "linux", "win32"})


@dataclass(frozen=True)
class InstallMarker:
    systems: frozenset[str]
    path: str = ""
    command: str = ""
    glob: str = ""


def _ext(*names: str) -> tuple[InstallMarker, ...]:
    hosts = (".vscode", ".cursor", ".vscode-oss")
    return tuple(
        InstallMarker(_ALL, glob=f"{{home}}/{host}/extensions/{name}-*")
        for name in names
        for host in hosts
    )


def _paths(*items: tuple[str, str]) -> tuple[InstallMarker, ...]:
    return tuple(InstallMarker(frozenset({system}), path=path) for system, path in items)


# 只认程序本体或扩展目录。数据目录不算已安装，否则卸载残留永远判断不出来。
# cursor 的命令行垫片会在卸载后留下，所以不把 cursor 命令当成还装着。
_MARKERS: dict[str, tuple[InstallMarker, ...]] = {
    "cursor": _paths(
        ("darwin", "/Applications/Cursor.app"),
        ("darwin", "{home}/Applications/Cursor.app"),
        ("win32", "{data_home}/Programs/cursor/Cursor.exe"),
        ("win32", "{data_home}/Programs/Cursor/Cursor.exe"),
        ("linux", "/usr/share/cursor"),
        ("linux", "/opt/Cursor"),
        ("linux", "{home}/.local/share/cursor"),
    ),
    "claude-desktop": _paths(
        ("darwin", "/Applications/Claude.app"),
        ("darwin", "{home}/Applications/Claude.app"),
        ("win32", "{data_home}/AnthropicClaude/claude.exe"),
        ("linux", "/usr/share/claude-desktop"),
        ("linux", "{home}/.local/share/claude-desktop"),
    ),
    "claude-code": (InstallMarker(_ALL, command="claude"),),
    "codex": _paths(
        ("darwin", "/Applications/Codex.app"),
        ("darwin", "{home}/Applications/Codex.app"),
        ("win32", "{data_home}/Programs/Codex/Codex.exe"),
        ("linux", "/usr/share/codex"),
    )
    + (InstallMarker(_ALL, command="codex"),),
    "chatgpt": _paths(
        ("darwin", "/Applications/ChatGPT.app"),
        ("darwin", "{home}/Applications/ChatGPT.app"),
        ("win32", "{data_home}/Programs/ChatGPT/ChatGPT.exe"),
        ("linux", "/usr/share/chatgpt"),
    ),
    "windsurf": _paths(
        ("darwin", "/Applications/Windsurf.app"),
        ("darwin", "{home}/Applications/Windsurf.app"),
        ("win32", "{data_home}/Programs/Windsurf/Windsurf.exe"),
        ("linux", "/usr/share/windsurf"),
        ("linux", "{home}/.local/share/windsurf"),
    )
    + (InstallMarker(_ALL, command="windsurf"),),
    "zed": _paths(
        ("darwin", "/Applications/Zed.app"),
        ("darwin", "{home}/Applications/Zed.app"),
        ("win32", "{data_home}/Programs/Zed/Zed.exe"),
        ("linux", "/usr/bin/zed"),
    )
    + (InstallMarker(_ALL, command="zed"),),
    "trae": _paths(
        ("darwin", "/Applications/Trae.app"),
        ("darwin", "{home}/Applications/Trae.app"),
        ("win32", "{data_home}/Programs/Trae/Trae.exe"),
        ("linux", "/usr/share/trae"),
    )
    + (InstallMarker(_ALL, command="trae"),),
    "kiro": _paths(
        ("darwin", "/Applications/Kiro.app"),
        ("darwin", "{home}/Applications/Kiro.app"),
        ("win32", "{data_home}/Programs/Kiro/Kiro.exe"),
        ("linux", "/usr/share/kiro"),
    )
    + (InstallMarker(_ALL, command="kiro"),),
    "warp": _paths(
        ("darwin", "/Applications/Warp.app"),
        ("darwin", "{home}/Applications/Warp.app"),
        ("win32", "{data_home}/Programs/Warp/Warp.exe"),
        ("linux", "/usr/share/warp"),
    )
    + (InstallMarker(_ALL, command="warp"),),
    "aider": (InstallMarker(_ALL, command="aider"),),
    "gemini-cli": (InstallMarker(_ALL, command="gemini"),),
    "opencode": (InstallMarker(_ALL, command="opencode"),),
    "amazon-q": (
        InstallMarker(_ALL, command="q"),
        InstallMarker(_ALL, command="amazon-q"),
        *_ext("amazonwebservices.amazon-q-vscode"),
    ),
    "amp": (InstallMarker(_ALL, command="amp"),),
    "tabnine": _paths(
        ("darwin", "/Applications/Tabnine.app"),
        ("win32", "{data_home}/Programs/Tabnine/Tabnine.exe"),
    )
    + (InstallMarker(_ALL, command="tabnine"),)
    + _ext("TabNine.tabnine-vscode", "tabnine.tabnine-vscode"),
    "jetbrains-ai": _paths(
        ("darwin", "/Applications/IntelliJ IDEA.app"),
        ("darwin", "/Applications/IntelliJ IDEA CE.app"),
        ("darwin", "/Applications/PyCharm.app"),
        ("darwin", "/Applications/PyCharm CE.app"),
        ("darwin", "/Applications/WebStorm.app"),
        ("darwin", "/Applications/GoLand.app"),
        ("darwin", "/Applications/CLion.app"),
        ("darwin", "/Applications/PhpStorm.app"),
        ("darwin", "/Applications/RubyMine.app"),
        ("darwin", "/Applications/Rider.app"),
        ("darwin", "/Applications/DataGrip.app"),
        ("darwin", "/Applications/RustRover.app"),
        ("darwin", "/Applications/DataSpell.app"),
        ("darwin", "/Applications/Fleet.app"),
        ("darwin", "/Applications/Android Studio.app"),
        ("darwin", "/Applications/JetBrains Toolbox.app"),
        ("win32", "{data_home}/JetBrains/Toolbox"),
        ("linux", "{home}/.local/share/JetBrains/Toolbox"),
    )
    + (
        InstallMarker(_ALL, command="idea"),
        InstallMarker(_ALL, command="pycharm"),
    ),
    "lingma": _paths(("darwin", "/Applications/Lingma.app"), ("win32", "{data_home}/Programs/Lingma/Lingma.exe"))
    + (InstallMarker(_ALL, command="lingma"),)
    + _ext("Alibaba-Cloud.tongyi-lingma"),
    "comate": _ext("BaiduComate.comate"),
    "codegeex": _ext("aminer.codegeex"),
    "continue": _ext("continue.continue"),
    "cline": _ext("saoudrizwan.claude-dev"),
    "roo-code": _ext("rooveterinaryinc.roo-cline"),
    "cody": _ext("sourcegraph.cody-ai"),
    "augment": _ext("augment.vscode-augment"),
    "copilot": (InstallMarker(_ALL, command="copilot"),) + _ext("github.copilot", "github.copilot-chat"),
}


def _default_glob(pattern: str) -> bool:
    path = Path(pattern)
    try:
        if "*" not in path.name:
            return path.exists()
        return any(path.parent.glob(path.name))
    except OSError:
        return False


def app_installed(
    agent_id: str,
    home: Path,
    os_name: str,
    *,
    exists=None,
    which=None,
    glob_hit=None,
) -> bool | None:
    """True 程序还在，False 程序已不在，None 这个产品没有安装位置规则。"""
    markers = [item for item in _MARKERS.get(agent_id, ()) if os_name in item.systems]
    if not markers:
        return None
    exists = exists or Path.exists
    which = which or shutil.which
    glob_hit = glob_hit or _default_glob
    for marker in markers:
        if marker.command and which(marker.command):
            return True
        if marker.path:
            raw = marker.path
            if "{" in raw:
                raw = str(expand_path(raw, home, os_name))
            if exists(Path(raw)):
                return True
        if marker.glob:
            raw = marker.glob
            if "{" in raw:
                raw = str(expand_path(raw, home, os_name))
            if glob_hit(raw):
                return True
    return False


def data_roots(agent: AgentSpec, home: Path, os_name: str) -> list[Path]:
    roots: list[Path] = []
    for root in agent.roots:
        if os_name not in root.os:
            continue
        path = expand_path(root.path, home, os_name)
        if path.exists() and not path.is_symlink():
            roots.append(path)
    return roots


def uninstall_rows(agents: list[AgentSpec], home: Path, os_name: str) -> list[dict]:
    rows: list[dict] = []
    for agent in agents:
        if app_installed(agent.id, home, os_name) is not False:
            continue
        for path in data_roots(agent, home, os_name):
            rows.append({"id": agent.id, "name": agent.name, "path": str(path)})
    return rows
