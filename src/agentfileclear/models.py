from enum import Enum
from pydantic import BaseModel, Field, field_validator


class Category(str, Enum):
    cache = "cache"
    log = "log"
    session = "session"
    backup = "backup"
    telemetry = "telemetry"
    extension_cache = "extension_cache"
    config = "config"
    secret = "secret"
    user_data = "user_data"
    unknown = "unknown"


CATEGORY_LABELS: dict[Category, str] = {
    Category.cache: "缓存",
    Category.log: "日志",
    Category.session: "会话",
    Category.backup: "备份",
    Category.telemetry: "遥测",
    Category.extension_cache: "扩展缓存",
    Category.config: "配置",
    Category.secret: "密钥",
    Category.user_data: "用户内容",
    Category.unknown: "未识别",
}

# 前六类是残留候选，其余默认保留。未识别需要人工看，不当成可删缓存。
RESIDUE_CATEGORIES: frozenset[Category] = frozenset(
    {
        Category.cache,
        Category.log,
        Category.session,
        Category.backup,
        Category.telemetry,
        Category.extension_cache,
    }
)

ALLOWED_OS = frozenset({"darwin", "linux", "win32"})


def category_keep(category: Category) -> bool:
    return category not in RESIDUE_CATEGORIES


class PathRule(BaseModel):
    glob: str
    category: Category
    aggregate: bool = True
    # safe：可清理。optional：列出来但默认保留。protected：不清理。
    risk: str = "safe"
    source_id: str = ""
    description: str = ""
    # path：匹配 glob 本身。stale_versions：目录下只把旧版本标为可清理，最新一份保留。
    match: str = "path"

    @field_validator("risk")
    @classmethod
    def known_risk(cls, value: str) -> str:
        if value not in {"safe", "optional", "protected"}:
            raise ValueError(f"未知风险级别: {value}")
        return value

    @field_validator("match")
    @classmethod
    def known_match(cls, value: str) -> str:
        if value not in {"path", "stale_versions"}:
            raise ValueError(f"未知匹配方式: {value}")
        return value

    @field_validator("glob")
    @classmethod
    def glob_stays_inside_root(cls, value: str) -> str:
        if not value or value == "**" or value.startswith("**/"):
            raise ValueError(f"非法规则: {value}")
        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError(f"非法规则: {value}")
        return value


class RootSpec(BaseModel):
    os: list[str]
    path: str
    emit_unmatched: bool = False
    preset: str | None = None
    rules: list[PathRule] = Field(default_factory=list)

    @field_validator("os")
    @classmethod
    def known_os(cls, value: list[str]) -> list[str]:
        unknown = set(value) - ALLOWED_OS
        if unknown or not value:
            raise ValueError(f"未知系统: {unknown or value}")
        return value

    @field_validator("path")
    @classmethod
    def path_is_template(cls, value: str) -> str:
        if not value or value.startswith("/") or ".." in value.split("/"):
            raise ValueError(f"非法路径模板: {value}")
        return value


class AgentSpec(BaseModel):
    id: str
    name: str
    roots: list[RootSpec]

    @field_validator("id")
    @classmethod
    def id_shape(cls, value: str) -> str:
        allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-")
        if not value or any(char not in allowed for char in value):
            raise ValueError(f"非法产品 id: {value}")
        return value


class RawHit(BaseModel):
    agent_id: str
    agent_name: str
    path: str
    relative_path: str
    is_dir: bool
    size_bytes: int = 0
    mtime: float | None = None
    rule_glob: str | None = None
    rule_category: Category | None = None
    rule_risk: str | None = None
    rule_source: str = ""
    rule_description: str = ""


class Finding(BaseModel):
    agent_id: str
    agent_name: str
    path: str
    relative_path: str
    category: Category
    keep: bool
    size_bytes: int
    mtime: float | None = None
    is_dir: bool
    reason: str
    confidence: float = 1.0
    source: str = "rule"
    # 程序本体已不在，但这条数据还在。
    uninstall_residue: bool = False


class CategorySummary(BaseModel):
    category: Category
    category_label: str
    count: int
    size_bytes: int
    keep: bool


class AgentSummary(BaseModel):
    agent_id: str
    agent_name: str
    categories: list[CategorySummary]
    count: int
    size_bytes: int


class ScanReport(BaseModel):
    findings: list[Finding]
    summary: list[AgentSummary]
    total_count: int
    total_size_bytes: int
