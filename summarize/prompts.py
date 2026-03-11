"""Prompt construction for structured paper analysis."""

from __future__ import annotations

import json
from typing import Any

from summarize.schemas import PaperAnalysisSchema

PROMPT_VERSION = "analysis-v1"


def build_analysis_messages(*, paper_context: dict[str, Any], model_name: str) -> list[dict[str, str]]:
    """Build chat messages requesting strict JSON output."""

    schema_hint = PaperAnalysisSchema.model_json_schema()
    system_prompt = (
        "你是学术综述分析助手。"
        "必须仅输出一个合法 JSON 对象，不得输出 Markdown、解释、代码块或额外文本。"
        "输出语言使用简体中文。"
        "重要技术术语首次出现时使用“中文术语 (English Term)”格式。"
        "语气必须正式、客观、学术化，不使用第一人称。"
        "若论文未明确提及某项内容，填入“文中未明确提及 (Not explicitly mentioned)”。"
        "分类字段必须严格从给定 taxonomy 中选择。"
    )
    user_payload = {
        "task": "基于论文已解析章节生成结构化综述分析 JSON",
        "model": model_name,
        "schema": schema_hint,
        "taxonomy": _taxonomy_hint(),
        "paper": paper_context,
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ]


def _taxonomy_hint() -> dict[str, list[str]]:
    return {
        "method_paradigm": [
            "llm_based",
            "search_based",
            "symbolic_execution_based",
            "constraint_solving_based",
            "mutation_based",
            "retrieval_augmented",
            "hybrid",
            "not_explicitly_mentioned",
        ],
        "target_languages": ["java", "python", "rust", "javascript", "c_cpp", "go", "multi_language", "language_unspecified"],
        "test_task_types": [
            "unit_test_generation",
            "regression_test_generation",
            "property_based_test_generation",
            "api_test_generation",
            "integration_test_generation",
            "system_test_generation",
            "fuzzing_assistance",
            "test_repair",
            "test_completion",
        ],
        "input_context": [
            "source_code_only",
            "source_code_and_ast",
            "static_analysis_enhanced",
            "dynamic_execution_enhanced",
            "specification_driven",
            "historical_tests",
            "retrieval_augmented_context",
        ],
        "output_artifact": ["test_method", "test_class", "test_suite", "assertion_generation", "input_generation", "fixture_generation"],
        "validation_repair": [
            "syntax_validation",
            "compile_validation",
            "runtime_validation",
            "rule_based_repair",
            "llm_based_repair",
            "iterative_feedback",
        ],
        "evaluation_scope": ["toy_examples", "benchmark_datasets", "open_source_projects", "industrial_projects", "cross_project_evaluation"],
        "contribution_type": ["framework", "tool", "benchmark", "empirical_study", "dataset", "prompting_strategy", "repair_pipeline"],
    }
