# literature-topic-agent

面向计算机科学论文的本地化 Topic 工作流：检索、去重、排序、下载 PDF、产出 Markdown 摘要与结构化产物。

## 1. 环境准备

要求：

- Python `>=3.11`
- [uv](https://docs.astral.sh/uv/)

进入项目目录后执行：

```bash
uv sync --dev
```

如需强制指定 Python 版本：

```bash
uv python install 3.11
uv sync --python 3.11 --dev
```

## 2. 查看 CLI 帮助

```bash
uv run literature-topic-agent --help
```

或：

```bash
uv run python -m apps.cli --help
```

## 3. 一条命令跑通（推荐先用示例配置）

```bash
uv run literature-topic-agent \
  config/example_topic.yaml \
  --workspace-root ./workspace
```

等价模块方式：

```bash
uv run python -m apps.cli \
  config/example_topic.yaml \
  --workspace-root ./workspace
```

## 4. 自定义主题配置并运行

1. 复制示例配置：

```bash
cp config/example_topic.yaml config/my_topic.yaml
```

2. 编辑 `config/my_topic.yaml`（至少建议改 `topic_name`、`slug`、`keyword_groups`）。

3. 运行：

```bash
uv run literature-topic-agent \
  config/my_topic.yaml \
  --workspace-root ./workspace
```

## 5. 常用运行命令

渲染 Markdown 摘要（默认开启）：

```bash
uv run literature-topic-agent config/example_topic.yaml \
  --workspace-root ./workspace \
  --render-markdown
```

关闭 Markdown 渲染（仅写数据库和 JSON）：

```bash
uv run literature-topic-agent config/example_topic.yaml \
  --workspace-root ./workspace \
  --no-render-markdown
```

将结果写入指定目录：

```bash
uv run literature-topic-agent config/example_topic.yaml \
  --workspace-root /tmp/literature-workspace
```

## 6. 运行后目录与产物

假设 `slug: test-case-generation`，典型目录如下：

```text
workspace/test-case-generation/
├── artifacts/
│   ├── papers.json
│   └── job.json
├── index.sqlite3
├── logs/
├── papers/
│   ├── CCF-A/
│   ├── CCF-B/
│   ├── CCF-C/
│   └── Unranked/
├── summary.md
└── topic.json
```

常用检查命令：

```bash
# 查看报告
sed -n '1,120p' workspace/test-case-generation/summary.md

# 查看论文数量（JSON）
uv run python - <<'PY'
import json
from pathlib import Path
p = Path("workspace/test-case-generation/artifacts/papers.json")
print(len(json.loads(p.read_text(encoding="utf-8"))))
PY

# 查看 SQLite 中前 20 条论文
sqlite3 workspace/test-case-generation/index.sqlite3 \
  "select title, year, ccf_rank, status from papers order by processing_priority asc limit 20;"
```

## 7. 测试命令

运行全部测试：

```bash
uv run pytest -q
```

只跑某个测试文件：

```bash
uv run pytest -q tests/test_dblp_provider.py
```

按关键字过滤：

```bash
uv run pytest -q -k "ranking or deduplication"
```

## 8. 常见问题与排查命令

检索/下载失败时，先确认网络与日志输出，再看失败码：

```bash
uv run python - <<'PY'
import json
from pathlib import Path
p = Path("workspace/test-case-generation/artifacts/papers.json")
rows = json.loads(p.read_text(encoding="utf-8"))
failed = [x for x in rows if x.get("download_failure_code")]
print(f"failed={len(failed)}")
for item in failed[:20]:
    print(item.get("download_failure_code"), "|", item.get("title", "")[:90])
PY
```

## 9. CCF 映射来源

默认使用 `config/ccf_venues.json` 作为 CCF 会议信息映射文件。

如需使用你自己的映射文件，可在运行时覆盖：

```bash
uv run literature-topic-agent config/example_topic.yaml \
  --workspace-root ./workspace \
  --ccf-mapping-path /path/to/your/ccf_mapping.json
```

`temp/` 目录用于本地外部资源缓存，不纳入版本管理。

## Acknowledgements

CCF 排名相关数据整理与思路参考了 [CCFrank4dblp](https://github.com/WenyanLiu/CCFrank4dblp) 项目，感谢原作者。
