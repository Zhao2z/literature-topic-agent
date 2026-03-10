from pathlib import Path

from domain.models import PaperRecord, TopicConfig
from exporters.markdown import MarkdownReportExporter


def test_markdown_exporter_renders_table(tmp_path: Path) -> None:
    templates_dir = Path(__file__).resolve().parent.parent / "templates"
    exporter = MarkdownReportExporter(templates_dir)
    topic = TopicConfig(
        topic_name="测试用例生成研究",
        slug="test-case-generation",
        keyword_groups=[["Test Case Generation"]],
    )
    papers = [
        PaperRecord(
            paper_id="paper-1",
            topic_slug="test-case-generation",
            title="Test Case Generation with LLMs",
            authors=["Alice"],
            venue="ICSE",
            year=2024,
            dblp_url="https://dblp.org/rec/conf/icse/1",
            ccf_rank="A",
            processing_priority=1,
        )
    ]

    rendered = exporter.render(topic, papers)

    assert "# 测试用例生成研究" in rendered
    assert "| 1 | A | 2024 | ICSE | Test Case Generation with LLMs |" in rendered
