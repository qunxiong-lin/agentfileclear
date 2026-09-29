import fnmatch
import os
from pathlib import Path

from agentfileclear.models import AgentSpec, Category, PathRule, RawHit, RootSpec
from agentfileclear.paths import expand_path

# 这些是操作系统自己的文件，不是智能体残留。
OS_JUNK = {".DS_Store", "desktop.ini", "Thumbs.db"}


def _within(root: Path, path: Path) -> bool:
    try:
        root_real = root.resolve()
        path_real = path.resolve()
    except OSError:
        return False
    return path_real == root_real or root_real in path_real.parents


def _children(directory: Path) -> list[Path]:
    try:
        entries = list(directory.iterdir())
    except OSError:
        return []
    # 不跟随符号链接，避免把根目录外面的文件算进来。
    return sorted((entry for entry in entries if not entry.is_symlink()), key=lambda entry: entry.name)


def directory_size(path: Path, root: Path) -> int:
    if path.is_symlink() or not _within(root, path):
        return 0
    total = 0
    seen: set[Path] = set()
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            current_real = current.resolve()
        except OSError:
            continue
        if current_real in seen or not _within(root, current):
            continue
        seen.add(current_real)
        try:
            scanned = list(os.scandir(current))
        except OSError:
            continue
        for entry in scanned:
            if entry.is_symlink():
                continue
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return total


def _entry_size(path: Path, root: Path) -> int:
    try:
        if path.is_symlink():
            return 0
        if path.is_dir():
            return directory_size(path, root)
        return path.stat().st_size
    except OSError:
        return 0


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def iter_matches(root: Path, pattern: str) -> list[Path]:
    return _walk(root, [part for part in pattern.split("/") if part], root)


def _walk(current: Path, parts: list[str], root: Path) -> list[Path]:
    if not parts:
        return [current]
    head, *rest = parts
    found: list[Path] = []
    if head == "**":
        if rest:
            found.extend(_walk(current, rest, root))
        if current.is_dir() and not current.is_symlink():
            for child in _children(current):
                if child.is_dir():
                    found.extend(_walk(child, parts, root))
        return found
    for child in _children(current):
        if not fnmatch.fnmatch(child.name, head) or not _within(root, child):
            continue
        if not rest:
            found.append(child)
        elif child.is_dir():
            found.extend(_walk(child, rest, root))
    return found


def _rule_rank(rule: PathRule, index: int) -> tuple[int, int, int]:
    secret = 1 if rule.category == Category.secret else 0
    return (secret, len(rule.glob), -index)


def _claims(rule: PathRule, name: str) -> bool:
    first = rule.glob.split("/")[0]
    return fnmatch.fnmatch(name, first)


def _hit(
    agent: AgentSpec,
    boundary: Path,
    path: Path,
    *,
    rule: PathRule | None,
    category: Category | None = None,
    risk: str | None = None,
    description: str | None = None,
) -> RawHit | None:
    try:
        relative = path.resolve().relative_to(boundary).as_posix()
    except (OSError, ValueError):
        return None
    if not relative:
        return None
    return RawHit(
        agent_id=agent.id,
        agent_name=agent.name,
        path=str(path),
        relative_path=relative,
        is_dir=path.is_dir(),
        size_bytes=_entry_size(path, boundary),
        mtime=_mtime(path),
        rule_glob=None if rule is None else rule.glob,
        rule_category=category if category is not None else (None if rule is None else rule.category),
        rule_risk=risk if risk is not None else (None if rule is None else rule.risk),
        rule_source="" if rule is None else rule.source_id,
        rule_description=description if description is not None else ("" if rule is None else rule.description),
    )


def _stale_version_hits(agent: AgentSpec, boundary: Path, rule: PathRule) -> list[tuple[Path, RawHit]]:
    """目录里只把旧版本标为可清理，修改时间最新的一份保留。"""
    found: list[tuple[Path, RawHit]] = []
    for directory in iter_matches(boundary, rule.glob):
        if not directory.is_dir() or directory.is_symlink():
            continue
        versions = [child for child in _children(directory) if child.is_dir()]
        if not versions:
            continue
        newest = max(versions, key=lambda child: (_mtime(child) or 0, child.name))
        for child in versions:
            if child == newest:
                hit = _hit(
                    agent,
                    boundary,
                    child,
                    rule=rule,
                    category=Category.user_data,
                    risk="protected",
                    description="保留最新一份，不清理",
                )
            else:
                hit = _hit(agent, boundary, child, rule=rule, risk="safe")
            if hit is not None:
                found.append((child, hit))
    return found


def scan_root(agent: AgentSpec, spec: RootSpec, root: Path) -> list[RawHit]:
    try:
        boundary = root.resolve()
    except OSError:
        return []
    if not boundary.is_dir():
        return []

    found: dict[str, tuple[tuple[int, int, int], RawHit]] = {}

    def put(path: Path, hit: RawHit, rank: tuple[int, int, int]) -> None:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        previous = found.get(key)
        if previous is None or rank > previous[0]:
            found[key] = (rank, hit)

    for index, rule in enumerate(spec.rules):
        if rule.match == "stale_versions":
            for path, hit in _stale_version_hits(agent, boundary, rule):
                put(path, hit, _rule_rank(rule, index))
            continue
        for path in iter_matches(boundary, rule.glob):
            hit = _hit(agent, boundary, path, rule=rule)
            if hit is not None:
                put(path, hit, _rule_rank(rule, index))

    if spec.emit_unmatched:
        for child in _children(boundary):
            if child.name in OS_JUNK or any(_claims(rule, child.name) for rule in spec.rules):
                continue
            hit = _hit(agent, boundary, child, rule=None)
            if hit is not None:
                put(child, hit, (-1, 0, 0))

    return [item[1] for item in found.values()]


def collect_hits(
    agents: list[AgentSpec],
    *,
    home: Path,
    os_name: str,
    use_env: bool = True,
) -> list[RawHit]:
    hits: list[RawHit] = []
    for agent in agents:
        for spec in agent.roots:
            if os_name not in spec.os:
                continue
            root = expand_path(spec.path, home, os_name, use_env=use_env)
            if not root.is_dir():
                continue
            hits.extend(scan_root(agent, spec, root))
    hits.sort(key=lambda hit: (hit.agent_id, hit.relative_path, hit.path))
    return hits
