import argparse
import json
import sys
from pathlib import Path

from agentfileclear.catalog import load_catalog
from agentfileclear.classify import classify_hits
from agentfileclear.installed import app_installed, uninstall_rows
from agentfileclear.llm import LlmConfigError, refine_with_llm
from agentfileclear.models import AgentSpec, Finding
from agentfileclear.paths import current_os, expand_path, resolve_home
from agentfileclear.recycle import (
    QuarantineError,
    annotate_uninstall,
    format_isolate,
    format_trash,
    isolate,
    list_trash,
    purge,
    restore_item,
)
from agentfileclear.report import build_report, format_agents, format_report, format_uninstall, report_dict
from agentfileclear.scan import collect_hits


class UnknownAgentError(ValueError):
    pass


def select_agents(agent_arg: str | None) -> list[AgentSpec]:
    catalog = load_catalog()
    if not agent_arg:
        return catalog
    wanted = [part.strip() for part in agent_arg.split(",") if part.strip()]
    by_id = {agent.id: agent for agent in catalog}
    missing = [item for item in wanted if item not in by_id]
    if not wanted or missing:
        known = ", ".join(agent.id for agent in catalog)
        unknown = ", ".join(missing) if missing else "(空)"
        raise UnknownAgentError(f"未知产品: {unknown}。可用 id: {known}")
    return [by_id[item] for item in wanted]


def agent_status(home: Path, os_name: str) -> list[dict]:
    rows = []
    for agent in load_catalog():
        roots = []
        for root in agent.roots:
            if os_name not in root.os:
                continue
            path = expand_path(root.path, home, os_name)
            roots.append({"path": str(path), "exists": path.is_dir(), "os": list(root.os)})
        data = any(item["exists"] for item in roots)
        app = app_installed(agent.id, home, os_name)
        if data and app is False:
            state = "卸载残留"
        elif data or app is True:
            state = "已安装"
        else:
            state = "未安装"
        rows.append(
            {
                "id": agent.id,
                "name": agent.name,
                "installed": data,
                "state": state,
                "roots": roots,
            }
        )
    return rows


def _prepare(agents: list[AgentSpec], home: Path, os_name: str, *, llm: bool) -> tuple[list[Finding], str, int]:
    findings = classify_hits(collect_hits(agents, home=home, os_name=os_name))
    findings = annotate_uninstall(findings, uninstall_rows(agents, home, os_name))
    error = ""
    code = 0
    if llm:
        try:
            findings = refine_with_llm(findings)
        except LlmConfigError as exc:
            error = str(exc)
            code = 2
        except Exception as exc:
            error = f"模型分类失败: {exc}"
            code = 1
    return findings, error, code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentclear",
        description="扫描智能体残留。清理时先隔离到回收站，可以恢复到原来的路径。",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("agents", help="列出产品、数据目录，以及程序是否已卸载")
    scan = commands.add_parser("scan", help="扫描并分类，不移动文件")
    scan.add_argument("--agent", help="只处理这些产品 id，用逗号分隔")
    scan.add_argument("--json", type=Path, help="把 JSON 报告写到这个文件")
    scan.add_argument("--llm", action="store_true", help="只用模型处理规则未识别、且不是密钥的项")

    clean = commands.add_parser("clean", help="把可清理项移入回收站，不直接删除")
    clean.add_argument("--agent", help="只处理这些产品 id，用逗号分隔")
    clean.add_argument("--uninstall", action="store_true", help="同时隔离已卸载智能体留下的数据目录")
    hold = clean.add_mutually_exclusive_group(required=True)
    hold.add_argument("--days", type=int, help="隔离天数，到期后用 purge 清除")
    hold.add_argument("--keep", action="store_true", help="一直留在回收站，直到恢复或 purge --all")

    commands.add_parser("trash", help="列出回收站里的文件")
    restore = commands.add_parser("restore", help="把回收站里的项放回原来的路径")
    restore.add_argument("item_id", nargs="?", help="回收站编号")
    restore.add_argument("--all", action="store_true", help="恢复全部")
    purge_cmd = commands.add_parser("purge", help="清除回收站里已经到期的项")
    purge_cmd.add_argument("--all", action="store_true", help="清空整个回收站，包括还没到期的")
    return parser


def _cmd_clean(args: argparse.Namespace, home: Path, os_name: str) -> int:
    if args.days is not None and args.days < 1:
        sys.stderr.write("隔离天数至少为 1。若要一直保留，请用 --keep。\n")
        return 2
    try:
        agents = select_agents(args.agent)
    except UnknownAgentError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    findings, error, code = _prepare(agents, home, os_name, llm=False)
    if error:
        sys.stderr.write(f"{error}\n")
        return code
    result = isolate(
        agents,
        findings,
        home=home,
        os_name=os_name,
        keep_days=None if args.keep else args.days,
        include_uninstall=args.uninstall,
    )
    sys.stdout.write(format_isolate(result, None if args.keep else args.days))
    return 1 if result.skipped and not result.moved else 0


def _cmd_restore(args: argparse.Namespace, home: Path, os_name: str) -> int:
    if bool(args.item_id) == bool(args.all):
        sys.stderr.write("请指定一个回收站编号，或使用 --all。\n")
        return 2
    ids = [item.id for item in list_trash(home, os_name)] if args.all else [args.item_id]
    if not ids:
        sys.stdout.write("回收站是空的。\n")
        return 0
    failed = False
    for item_id in ids:
        try:
            meta, conflicts = restore_item(home, os_name, item_id)
        except QuarantineError as exc:
            sys.stderr.write(f"{exc}\n")
            failed = True
            continue
        if conflicts:
            failed = True
            sys.stdout.write(f"{item_id} 有些原位置已有文件，未覆盖，仍留在回收站：\n")
            for path in conflicts:
                sys.stdout.write(f"  {path}\n")
            continue
        sys.stdout.write(f"已放回原位置  {item_id}  {meta.original_path}\n")
    return 1 if failed else 0


def _cmd_purge(args: argparse.Namespace, home: Path, os_name: str) -> int:
    removed = purge(home, os_name, everything=args.all)
    if not removed:
        if args.all:
            sys.stdout.write("回收站是空的。\n")
        else:
            sys.stdout.write("没有到期项。还没到期的要用 purge --all 才会清除。\n")
        return 0
    title = "已清空" if args.all else "已清除到期项"
    sys.stdout.write(f"{title}  {len(removed)} 项\n")
    for item in removed:
        sys.stdout.write(f"  {item.id}  {item.original_path}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home = resolve_home()
    os_name = current_os()
    if args.command == "agents":
        sys.stdout.write(format_agents(agent_status(home, os_name)))
        return 0
    if args.command == "trash":
        sys.stdout.write(format_trash(list_trash(home, os_name)))
        return 0
    if args.command == "clean":
        return _cmd_clean(args, home, os_name)
    if args.command == "restore":
        return _cmd_restore(args, home, os_name)
    if args.command == "purge":
        return _cmd_purge(args, home, os_name)

    try:
        agents = select_agents(args.agent)
    except UnknownAgentError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    findings, error, code = _prepare(agents, home, os_name, llm=args.llm)
    report = build_report(findings)
    sys.stdout.write(format_report(report))
    sys.stdout.write(format_uninstall(uninstall_rows(agents, home, os_name)))
    if args.json:
        args.json.write_text(
            json.dumps(report_dict(report), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if error:
        sys.stderr.write(f"{error}\n")
    return code
