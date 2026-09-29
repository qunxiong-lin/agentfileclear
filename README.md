# agentfileclear

扫描 macOS、Linux 和 Windows 上主流本地智能体的残留文件，按类别汇总。清理时先隔离到回收站，可以恢复到原来的路径。

命令行程序名是 `agentclear`。`scan` 只读，不会移动或删除文件。

## 下载

需要 Python 3.11 或更高版本。最新版本在 [Releases](https://github.com/qunxiong-lin/agentfileclear/releases/latest)。

**[下载 v0.1.0 安装包](https://github.com/qunxiong-lin/agentfileclear/releases/download/v0.1.0/agentfileclear-0.1.0-py3-none-any.whl)**

```bash
pip install https://github.com/qunxiong-lin/agentfileclear/releases/download/v0.1.0/agentfileclear-0.1.0-py3-none-any.whl
agentclear --help
```

也可以下载 [源码 zip](https://github.com/qunxiong-lin/agentfileclear/archive/refs/tags/v0.1.0.zip)。

## 安装

```bash
pip install git+https://github.com/qunxiong-lin/agentfileclear.git
```

也可以克隆后本地安装：

```bash
git clone https://github.com/qunxiong-lin/agentfileclear.git
cd agentfileclear
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 用法

```bash
agentclear agents
agentclear scan
agentclear scan --agent cursor,claude-code
agentclear scan --json report.json

agentclear clean --days 7
agentclear clean --keep
agentclear clean --days 7 --uninstall

agentclear trash
agentclear restore <编号>
agentclear restore --all
agentclear purge
agentclear purge --all
```

| 命令 | 作用 |
| --- | --- |
| `agents` | 列出产品和数据目录，并标出程序是否已卸载 |
| `scan` | 扫描并分类，不修改文件 |
| `clean --days N` | 把可清理项移入回收站，保留 N 天 |
| `clean --keep` | 一直留在回收站，直到恢复或 `purge --all` |
| `clean --uninstall` | 同时隔离已卸载智能体留下的整个数据目录 |
| `trash` | 查看回收站 |
| `restore` | 放回原来的路径。原位置已有的文件不会被覆盖 |
| `purge` | 清除已经到期的项。到期后不会自动删除 |
| `purge --all` | 清空整个回收站，包括还没到期的项 |

回收站位置：

- macOS：`~/Library/Application Support/agentfileclear/Trash`
- Linux：`~/.local/share/agentfileclear/Trash`
- Windows：`%LOCALAPPDATA%\agentfileclear\Trash`

## 清理边界

可隔离的是规则标成缓存、日志、遥测、扩展缓存和备份的项。

这些默认留在原地：

- 密钥，例如 `mcp.json`、`auth.json`、`.env`
- 配置、技能、对话记录
- 保护路径，例如编辑器主状态库

正在使用的产品不会被整目录移走。只有程序已经不在、数据目录还在时，`clean --uninstall` 才会隔离该目录，并仍把密钥文件留在原处。

## 支持的产品

Aider、Amazon Q、Amp、Augment、ChatGPT 桌面端、Claude Code、Claude 桌面端、Cline、CodeGeeX、Codex、Sourcegraph Cody、文心 Comate、Continue、GitHub Copilot、Cursor、Gemini CLI、JetBrains AI / Junie、Kiro、通义灵码、OpenCode、Roo Code、Tabnine、Trae、Warp、Windsurf、Zed。

没装的产品会跳过。新产品加一份 `src/agentfileclear/catalog/agents/<id>.json` 即可。

## 可选的模型分类

规则能判定的项不调用模型。加上 `--llm` 时，只把未识别、且不是密钥的相对路径交给模型，并让模型按 [`classify-residue`](src/agentfileclear/skills/classify-residue/SKILL.md) 这份 skill 判断。不会把文件内容，或已经标成可清理的目录直接丢给模型。

模型名是 `提供商:模型`，并要带上该提供商的 API 密钥。例如：

```bash
# OpenAI
export OPENAI_API_KEY=sk-...
export AGENTCLEAR_MODEL=openai:gpt-4.1-mini
agentclear scan --llm

# Anthropic
export ANTHROPIC_API_KEY=sk-ant-...
export AGENTCLEAR_MODEL=anthropic:claude-sonnet-4-5
agentclear scan --llm

# Google
export GOOGLE_API_KEY=...
export AGENTCLEAR_MODEL=google-gla:gemini-2.5-flash
agentclear scan --llm
```

格式说明见 [Pydantic AI 模型名](https://ai.pydantic.dev/models/overview/)。

## 开发

```bash
pip install -e ".[dev]"
pytest
```

## 许可证

[MIT License](LICENSE)。
