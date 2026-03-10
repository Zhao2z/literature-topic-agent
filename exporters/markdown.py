"""Markdown exporter."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from domain.models import PaperRecord, TopicConfig


class MarkdownReportExporter:
    """Render a topic summary Markdown report."""

    def __init__(self, templates_dir: str | Path) -> None:
        self._environment = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(enabled_extensions=(), default=False),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, topic_config: TopicConfig, papers: list[PaperRecord]) -> str:
        """Render the Markdown summary content."""

        template = self._environment.get_template("topic_summary.md.j2")
        return template.render(topic=topic_config, papers=papers)
