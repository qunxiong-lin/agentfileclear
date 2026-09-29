import re
from pathlib import Path

from agentfileclear.models import CATEGORY_LABELS, Category, Finding, RawHit, category_keep

SECRET_NAMES = {
    ".env",
    ".netrc",
    "auth.json",
    "cookies",
    "cookies-journal",
    "credentials",
    "credentials.json",
    "google_accounts.json",
    "id_ed25519",
    "id_rsa",
    "mcp.json",
    "oauth_creds.json",
}
SECRET_SUFFIXES = {".key", ".pem"}
# 按词边界匹配，避免 TokenWallet 这类项目名被当成密钥。
SECRET_NAME_RE = re.compile(
    r"(?:^|[^a-z0-9])(?:token|secret|credential|password|passwd)s?(?:[^a-z0-9]|$)",
    re.IGNORECASE,
)


def part_is_secret(part: str) -> bool:
    name = part.lower()
    if name in SECRET_NAMES or Path(name).suffix.lower() in SECRET_SUFFIXES:
        return True
    return SECRET_NAME_RE.search(name) is not None


def is_secret_path(path: Path) -> bool:
    return any(part_is_secret(part) for part in path.parts)


def shallow_has_secret(path: Path) -> bool:
    if path.is_symlink() or not path.is_dir():
        return False
    try:
        children = list(path.iterdir())
    except OSError:
        return False
    return any(part_is_secret(child.name) for child in children)


def classify_hit(hit: RawHit) -> Finding:
    category = hit.rule_category or Category.unknown
    path = Path(hit.path)
    # 只看产品根目录内的相对路径。绝对路径里的临时目录名不算密钥。
    secret = is_secret_path(Path(hit.relative_path)) or (hit.is_dir and shallow_has_secret(path))
    overridden = secret and category != Category.secret
    if secret:
        category = Category.secret
    label = CATEGORY_LABELS[category]
    if hit.rule_risk in {"optional", "protected"}:
        keep = True
    else:
        keep = category_keep(category)
    if overridden or category == Category.secret:
        keep = True
    if overridden:
        reason = f"路径含密钥特征，标为{label}，保留"
    elif hit.rule_source:
        reason = hit.rule_description or f"规则 {hit.rule_source}，类别为{label}"
        if hit.rule_risk == "optional":
            reason += "（可选清理，默认保留）"
        elif hit.rule_risk == "protected":
            reason += "（保护路径，不清理）"
    elif hit.rule_glob:
        detail = hit.rule_description or f"类别为{label}"
        reason = f"匹配规则 {hit.rule_glob}：{detail}"
        if hit.rule_risk == "optional" and "默认保留" not in reason:
            reason += "（可选清理，默认保留）"
        elif hit.rule_risk == "protected" and "不清理" not in reason:
            reason += "（保护路径，不清理）"
    else:
        reason = "未匹配已知规则，标为未识别"
    return Finding(
        agent_id=hit.agent_id,
        agent_name=hit.agent_name,
        path=hit.path,
        relative_path=hit.relative_path,
        category=category,
        keep=keep,
        size_bytes=hit.size_bytes,
        mtime=hit.mtime,
        is_dir=hit.is_dir,
        reason=reason,
        confidence=1.0,
        source="rule",
    )


def classify_hits(hits: list[RawHit]) -> list[Finding]:
    return [classify_hit(hit) for hit in hits]
