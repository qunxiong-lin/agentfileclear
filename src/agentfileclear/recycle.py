"""回收站：先隔离，再按原来的路径放回去。到期项要单独清除，不会自动删。"""

import os
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, ValidationError

from agentfileclear.classify import part_is_secret
from agentfileclear.installed import app_installed, data_roots
from agentfileclear.models import AgentSpec, Category, Finding
from agentfileclear.paths import expand_path
from agentfileclear.scan import directory_size


class TrashMeta(BaseModel):
    id: str
    original_path: str
    agent_id: str
    agent_name: str
    category: str
    kind: str
    quarantined_at: str
    keep_days: int | None = None
    expires_at: str | None = None
    size_bytes: int = 0
    kept_secrets: list[str] = []


class IsolateResult(BaseModel):
    moved: list[TrashMeta] = []
    kept_secrets: list[str] = []
    skipped: list[str] = []


class QuarantineError(RuntimeError):
    pass


def trash_root(home: Path, os_name: str) -> Path:
    return expand_path("{data_home}/agentfileclear/Trash", home, os_name)


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now


def _within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


def _symlink_between(path: Path, stop: Path) -> bool:
    current = path
    stop_resolved = stop.resolve()
    while True:
        if current.is_symlink():
            return True
        if current.resolve() == stop_resolved or current == current.parent:
            return False
        current = current.parent


def _secret_nodes(root: Path) -> list[Path]:
    found: list[Path] = []
    if root.is_symlink() or not root.exists():
        return found
    if root.is_file():
        return found
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(current)
        kept: list[str] = []
        for name in dirnames:
            path = base / name
            if part_is_secret(name):
                found.append(path)
                continue
            if path.is_symlink():
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            path = base / name
            if part_is_secret(name):
                found.append(path)
    return found


def _move_keeping_secrets(src: Path, payload: Path) -> list[str]:
    """把目录移入回收站，密钥文件留在原来的路径。"""
    secrets = _secret_nodes(src)
    if not secrets:
        shutil.move(str(src), str(payload))
        return []
    hold = Path(tempfile.mkdtemp(prefix=".agentclear-keep-", dir=src.parent))
    parked: list[tuple[Path, Path]] = []
    try:
        for secret in secrets:
            relative = secret.relative_to(src)
            dest = hold / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(secret), str(dest))
            parked.append((secret, dest))
        shutil.move(str(src), str(payload))
        kept: list[str] = []
        while parked:
            original, dest = parked[0]
            original.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(original))
            parked.pop(0)
            kept.append(str(original))
        return kept
    finally:
        for original, dest in parked:
            if dest.exists() and not original.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dest), str(original))
        shutil.rmtree(hold, ignore_errors=True)


def _item_dir(root: Path, item_id: str) -> Path:
    return root / item_id


def quarantine_path(
    src: Path,
    *,
    home: Path,
    os_name: str,
    allowed_roots: list[Path],
    agent_id: str,
    agent_name: str,
    category: str,
    kind: str,
    keep_days: int | None,
    now: datetime | None = None,
    size_bytes: int = 0,
) -> TrashMeta:
    if not src.exists():
        raise QuarantineError(f"路径不存在: {src}")
    if src.is_symlink() or _symlink_between(src, home):
        raise QuarantineError(f"跳过符号链接: {src}")
    if not any(_within(src, root) or src.resolve() == root.resolve() for root in allowed_roots):
        raise QuarantineError(f"路径不在该产品的数据目录内: {src}")
    if src.resolve() == home.resolve():
        raise QuarantineError("拒绝隔离用户主目录")
    store = trash_root(home, os_name)
    if _within(store, src) or src.resolve() == store.resolve():
        raise QuarantineError("拒绝隔离回收站自身")
    moment = _now(now)
    expires = None if keep_days is None else (moment + timedelta(days=keep_days)).isoformat()
    store.mkdir(parents=True, exist_ok=True)
    item_id = uuid.uuid4().hex[:8]
    while _item_dir(store, item_id).exists():
        item_id = uuid.uuid4().hex[:8]
    folder = _item_dir(store, item_id)
    folder.mkdir()
    payload = folder / "payload"
    meta = TrashMeta(
        id=item_id,
        original_path=str(src),
        agent_id=agent_id,
        agent_name=agent_name,
        category=category,
        kind=kind,
        quarantined_at=moment.isoformat(),
        keep_days=keep_days,
        expires_at=expires,
        size_bytes=size_bytes,
    )
    try:
        meta.kept_secrets = _move_keeping_secrets(src, payload)
        (folder / "meta.json").write_text(meta.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except Exception:
        _return_payload(payload, src)
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return meta


def _return_payload(payload: Path, src: Path) -> None:
    if not payload.exists():
        return
    if not src.exists():
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(payload), str(src))
        return
    if payload.is_dir() and src.is_dir():
        for child in list(payload.iterdir()):
            target = src / child.name
            if not target.exists():
                shutil.move(str(child), str(target))


def _covered(path: Path, parents: list[Path]) -> bool:
    resolved = path.resolve()
    for parent in parents:
        parent_resolved = parent.resolve()
        if resolved == parent_resolved or parent_resolved in resolved.parents:
            return True
    return False


def isolate(
    agents: list[AgentSpec],
    findings: list[Finding],
    *,
    home: Path,
    os_name: str,
    keep_days: int | None,
    include_uninstall: bool,
    now: datetime | None = None,
    installed=None,
) -> IsolateResult:
    """keep 为 false 的临时项目直接隔离。卸载残留要 include_uninstall 才整目录隔离。"""
    installed = installed or app_installed
    result = IsolateResult()
    chosen: list[tuple[Path, AgentSpec, str, str, int]] = []
    by_id = {agent.id: agent for agent in agents}

    if include_uninstall:
        for agent in agents:
            roots = data_roots(agent, home, os_name)
            if not roots:
                continue
            state = installed(agent.id, home, os_name)
            if state is None:
                result.skipped.append(f"{agent.name} 没有安装位置检查，未按卸载残留处理")
                continue
            if state is not False:
                continue
            for root in roots:
                if _covered(root, [item[0] for item in chosen]):
                    continue
                try:
                    size = directory_size(root, root)
                except OSError:
                    size = 0
                chosen.append((root, agent, "uninstall", Category.user_data.value, size))

    for finding in sorted(findings, key=lambda item: len(Path(item.path).parts)):
        if finding.keep or finding.category == Category.secret:
            continue
        agent = by_id.get(finding.agent_id)
        if agent is None:
            result.skipped.append(f"找不到产品，跳过 {finding.path}")
            continue
        path = Path(finding.path)
        if _covered(path, [item[0] for item in chosen]):
            continue
        chosen.append((path, agent, "temp", finding.category.value, finding.size_bytes))

    for path, agent, kind, category, size in chosen:
        try:
            meta = quarantine_path(
                path,
                home=home,
                os_name=os_name,
                allowed_roots=data_roots(agent, home, os_name) or [path],
                agent_id=agent.id,
                agent_name=agent.name,
                category=category,
                kind=kind,
                keep_days=keep_days,
                now=now,
                size_bytes=size,
            )
        except (OSError, QuarantineError) as exc:
            result.skipped.append(str(exc))
            continue
        result.moved.append(meta)
        result.kept_secrets.extend(meta.kept_secrets)
    return result


def list_trash(home: Path, os_name: str) -> list[TrashMeta]:
    root = trash_root(home, os_name)
    if not root.is_dir():
        return []
    items: list[TrashMeta] = []
    for folder in sorted(root.iterdir()):
        meta_path = folder / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            items.append(TrashMeta.model_validate_json(meta_path.read_text(encoding="utf-8")))
        except (OSError, ValidationError):
            continue
    items.sort(key=lambda item: item.quarantined_at)
    return items


def _load_item(home: Path, os_name: str, item_id: str) -> tuple[Path, TrashMeta]:
    folder = _item_dir(trash_root(home, os_name), item_id)
    meta_path = folder / "meta.json"
    if not meta_path.is_file():
        raise QuarantineError(f"回收站里没有 {item_id}")
    meta = TrashMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
    return folder, meta


def restore_item(home: Path, os_name: str, item_id: str) -> tuple[TrashMeta, list[str]]:
    """放回原来的路径。原位置已有的文件不覆盖，对应内容留在回收站。"""
    folder, meta = _load_item(home, os_name, item_id)
    payload = folder / "payload"
    original = Path(meta.original_path)
    if not _within(original, home):
        raise QuarantineError(f"原路径不在用户目录内，拒绝恢复: {original}")
    if original.is_symlink():
        raise QuarantineError(f"原位置是符号链接，拒绝恢复: {original}")
    parent = original.parent
    if parent.exists() and not _within(parent, home):
        raise QuarantineError(f"原位置的上级目录越界，拒绝恢复: {original}")
    if not payload.exists():
        raise QuarantineError(f"回收站内容缺失: {item_id}")
    conflicts = _put_back(payload, original)
    if conflicts or (payload.exists() and (payload.is_file() or any(payload.iterdir()))):
        return meta, conflicts
    shutil.rmtree(folder)
    return meta, conflicts


def _put_back(payload: Path, original: Path) -> list[str]:
    if not original.exists():
        original.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(payload), str(original))
        return []
    if payload.is_dir() and original.is_dir() and not original.is_symlink():
        conflicts: list[str] = []
        for child in list(payload.iterdir()):
            target = original / child.name
            if target.exists() or target.is_symlink():
                conflicts.append(str(target))
                continue
            shutil.move(str(child), str(target))
        return conflicts
    return [str(original)]


def purge(home: Path, os_name: str, *, everything: bool, now: datetime | None = None) -> list[TrashMeta]:
    moment = _now(now)
    removed: list[TrashMeta] = []
    for meta in list_trash(home, os_name):
        if not everything:
            if meta.expires_at is None:
                continue
            expires = datetime.fromisoformat(meta.expires_at)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires > moment:
                continue
        folder = _item_dir(trash_root(home, os_name), meta.id)
        shutil.rmtree(folder)
        removed.append(meta)
    return removed


def _retention(meta: TrashMeta, moment: datetime) -> str:
    if meta.expires_at is None:
        return "一直保留"
    expires = datetime.fromisoformat(meta.expires_at)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= moment:
        return "已到期"
    days = (expires - moment).days
    if days <= 0:
        return "不足 1 天"
    return f"还剩 {days} 天"


def format_isolate(result: IsolateResult, keep_days: int | None) -> str:
    if not result.moved and not result.skipped and not result.kept_secrets:
        return "没有可隔离的临时文件。卸载残留需要加 --uninstall。\n"
    lines: list[str] = []
    if result.moved:
        stay = "一直留在回收站，直到恢复或 purge --all" if keep_days is None else f"保留 {keep_days} 天，到期后用 purge 清除"
        lines.append(f"已隔离 {len(result.moved)} 项，{stay}。可用 trash 查看，restore 放回原位置。")
        for item in result.moved:
            kind = "卸载残留" if item.kind == "uninstall" else "临时文件"
            lines.append(f"  {item.id}  {kind}  {item.agent_name}  {item.original_path}")
    if result.kept_secrets:
        lines.append("密钥文件留在原处，没有进回收站：")
        for path in result.kept_secrets:
            lines.append(f"  {path}")
    if result.skipped:
        lines.append("未隔离：")
        for line in result.skipped:
            lines.append(f"  {line}")
    return "\n".join(lines) + "\n"


def format_trash(items: list[TrashMeta], *, now: datetime | None = None) -> str:
    moment = _now(now)
    if not items:
        return "回收站是空的。\n"
    lines = [f"回收站  {len(items)} 项", "到期后不会自动删除，执行 purge 才会清掉到期项。"]
    for item in items:
        kind = "卸载残留" if item.kind == "uninstall" else "临时文件"
        lines.append(
            f"  {item.id}  {kind}  {_retention(item, moment)}  {item.agent_name}  {item.original_path}"
        )
    return "\n".join(lines) + "\n"


def annotate_uninstall(findings: list[Finding], rows: list[dict]) -> list[Finding]:
    residue = {row["id"] for row in rows}
    if not residue:
        return findings
    return [
        finding.model_copy(update={"uninstall_residue": finding.agent_id in residue})
        for finding in findings
    ]
