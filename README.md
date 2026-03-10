# literature-topic-agent

Local topic-driven literature collection, ranking, downloading, summarization, and reporting for CS papers.

## uv setup

Create and sync the project environment:

```bash
uv sync --dev
```

Run the CLI with the managed environment:

```bash
uv run literature-topic-agent config/example_topic.yaml --workspace-root ./workspace
```

Or run the module form directly:

```bash
uv run python -m apps.cli config/example_topic.yaml --workspace-root ./workspace
```

Run tests:

```bash
uv run pytest -q
```

Use a different Python version if needed:

```bash
uv python install 3.11
uv sync --python 3.11 --dev
```
