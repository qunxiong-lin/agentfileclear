---
name: classify-residue
description: >-
  Classifies an unmatched local agent path as cache, log, session, backup,
  telemetry, extension cache, config, secret, user data, or unknown, and
  decides whether it may be quarantined. Use only for paths that rules did
  not match. Do not read file contents.
---

# 未识别路径分类

只判断规则没有命中的路径。已经由规则分类的项不要改。密钥路径不要判成可清理。

不要打开文件，也不要根据文件内容猜测。只使用给出的产品、相对路径、是否为目录、大小。

## 类别

| 类别 | 含义 | 默认可隔离 |
| --- | --- | --- |
| cache | 删掉后产品会自己重建的缓存、临时文件、索引 | 是 |
| log | 运行日志、崩溃转储 | 是 |
| session | 对话、命令历史、会话索引 | 否 |
| backup | 备份副本 | 否 |
| telemetry | 本地遥测、统计缓存 | 是 |
| extension_cache | 扩展或插件的可重建副本 | 是 |
| config | 设置、状态、启动参数 | 否 |
| secret | 登录信息、令牌、密钥、MCP 配置 | 否 |
| user_data | 技能、计划、记忆、用户写出的内容、辅助程序 | 否 |
| unknown | 以上都无法确定 | 否 |

`session`、`backup`、`config`、`secret`、`user_data`、`unknown` 的 `keep` 必须是 `true`。其余类别在能确定可重建时 `keep` 为 `false`，拿不准就 `keep` 为 `true`，类别改为 `unknown`。

## 判断顺序

1. 路径任一段像密钥文件名（`auth.json`、`.env`、`mcp.json`、`*.pem`、`*.key`，或独立的 token、secret、credential、password）时，类别是 `secret`，`keep` 为 `true`。项目名里含有 Token 不算。
2. 名字是日志、缓存、临时目录，或明确会重建的插件运行时副本时，标成对应可隔离类别。
3. 名字是会话、技能、配置、数据库主文件、已安装程序时，标成保留类别。
4. 其余标 `unknown`，`keep` 为 `true`。

一次只返回和输入条数相同的结论。`path` 与 `agent_id` 必须和输入一致。`reason` 用一句中文，不引用文件内容。

## 示例

输入：

```json
[
  {"path": "tmp", "agent_id": "codex", "size_bytes": 4096, "is_dir": true},
  {"path": "skills", "agent_id": "codex", "size_bytes": 12000, "is_dir": true},
  {"path": "computer-use", "agent_id": "codex", "size_bytes": 66000000, "is_dir": true}
]
```

输出：

```json
{
  "verdicts": [
    {
      "path": "tmp",
      "agent_id": "codex",
      "category": "cache",
      "keep": false,
      "confidence": 0.8,
      "reason": "临时目录，下次运行会重建"
    },
    {
      "path": "skills",
      "agent_id": "codex",
      "category": "user_data",
      "keep": true,
      "confidence": 0.9,
      "reason": "技能目录，属于用户内容"
    },
    {
      "path": "computer-use",
      "agent_id": "codex",
      "category": "user_data",
      "keep": true,
      "confidence": 0.7,
      "reason": "像是辅助程序目录，不能当作缓存删除"
    }
  ]
}
```
