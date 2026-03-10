from pathlib import Path

from topic.loader import load_topic_config


def test_load_topic_config(tmp_path: Path) -> None:
    config_path = tmp_path / "topic.yaml"
    config_path.write_text(
        """
topic_name: 测试用例生成研究
slug: test-case-generation
keyword_groups:
  - ["Test Case Generation"]
  - ["LLM", "Test Generation"]
year_range:
  start: 2020
  end: 2025
max_candidate_count: 50
initial_parse_limit: 10
update_cron: "0 9 * * *"
        """.strip(),
        encoding="utf-8",
    )

    config = load_topic_config(config_path)

    assert config.topic_name == "测试用例生成研究"
    assert config.slug == "test-case-generation"
    assert config.keyword_groups[1] == ["LLM", "Test Generation"]
    assert config.year_range.start == 2020
    assert config.max_candidate_count == 50
