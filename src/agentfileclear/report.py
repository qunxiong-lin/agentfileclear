from agentfileclear.models import (
    CATEGORY_LABELS,
    AgentSummary,
    Category,
    CategorySummary,
    Finding,
    ScanReport,
    category_keep,
)


def human_size(size: int) -> str:
    value = float(max(size, 0))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _display_width(text: str) -> int:
    return sum(2 if ord(char) > 127 else 1 for char in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(width - _display_width(text), 0)


def build_report(findings: list[Finding]) -> ScanReport:
    ordered = sorted(
        findings,
        key=lambda finding: (
            finding.agent_id,
            list(Category).index(finding.category),
            finding.relative_path,
            finding.path,
        ),
    )
    grouped: dict[str, list[Finding]] = {}
    names: dict[str, str] = {}
    for finding in ordered:
        grouped.setdefault(finding.agent_id, []).append(finding)
        names[finding.agent_id] = finding.agent_name

    summary: list[AgentSummary] = []
    for agent_id, items in grouped.items():
        buckets: dict[Category, list[Finding]] = {}
        for item in items:
            buckets.setdefault(item.category, []).append(item)
        categories: list[CategorySummary] = []
        for category in Category:
            bucket = buckets.get(category)
            if not bucket:
                continue
            categories.append(
                CategorySummary(
                    category=category,
                    category_label=CATEGORY_LABELS[category],
                    count=len(bucket),
                    size_bytes=sum(item.size_bytes for item in bucket),
                    keep=all(item.keep for item in bucket),
                )
            )
        summary.append(
            AgentSummary(
                agent_id=agent_id,
                agent_name=names[agent_id],
                categories=categories,
                count=len(items),
                size_bytes=sum(item.size_bytes for item in items),
            )
        )
    return ScanReport(
        findings=ordered,
        summary=summary,
        total_count=len(ordered),
        total_size_bytes=sum(item.size_bytes for item in ordered),
    )


def report_dict(report: ScanReport) -> dict:
    data = report.model_dump(mode="json")
    for item in data["findings"]:
        item["category_label"] = CATEGORY_LABELS[Category(item["category"])]
    return data


def format_report(report: ScanReport) -> str:
    lines = ["只读扫描，未修改任何文件", ""]
    if not report.findings:
        lines.append("没有发现已安装产品的匹配项。")
        return "\n".join(lines) + "\n"

    by_agent: dict[str, list[Finding]] = {}
    for finding in report.findings:
        by_agent.setdefault(finding.agent_id, []).append(finding)

    for agent in report.summary:
        items = by_agent[agent.agent_id]
        residue = any(item.uninstall_residue for item in items)
        suffix = "  卸载残留" if residue else ""
        lines.append(f"{agent.agent_name} ({agent.agent_id}){suffix}")
        for category in agent.categories:
            keep = "  保留" if category.keep else ""
            lines.append(
                f"  {_pad(category.category_label, 8)}  {category.count:4d} 项  "
                f"{human_size(category.size_bytes):>10}{keep}"
            )
            for finding in items:
                if finding.category == category.category:
                    lines.append(f"    {finding.relative_path}")
        lines.append(
            f"  {_pad('合计', 8)}  {agent.count:4d} 项  {human_size(agent.size_bytes):>10}"
        )
        lines.append("")
    lines.append(f"全部合计  {report.total_count} 项  {human_size(report.total_size_bytes)}")
    return "\n".join(lines) + "\n"


def format_agents(rows: list[dict]) -> str:
    lines: list[str] = []
    for row in rows:
        state = row.get("state") or ("已安装" if row["installed"] else "未安装")
        lines.append(f"{state}  {row['name']} ({row['id']})")
        for root in row["roots"]:
            mark = "存在" if root["exists"] else "缺失"
            lines.append(f"  [{mark}] {root['path']}")
    return "\n".join(lines) + ("\n" if lines else "")


def format_uninstall(rows: list[dict]) -> str:
    if not rows:
        return ""
    lines = ["", "卸载残留（程序已不在，数据目录还在。隔离请用 clean --uninstall）"]
    for row in rows:
        lines.append(f"  {row['name']} ({row['id']})")
        lines.append(f"    {row['path']}")
    return "\n".join(lines) + "\n"
