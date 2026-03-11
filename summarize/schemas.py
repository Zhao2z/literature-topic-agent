"""Strict schemas for LLM-based paper analysis."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

MethodParadigm = Literal[
    "llm_based",
    "search_based",
    "symbolic_execution_based",
    "constraint_solving_based",
    "mutation_based",
    "retrieval_augmented",
    "hybrid",
    "not_explicitly_mentioned",
]
TargetLanguage = Literal[
    "java",
    "python",
    "rust",
    "javascript",
    "c_cpp",
    "go",
    "multi_language",
    "language_unspecified",
]
TestTaskType = Literal[
    "unit_test_generation",
    "regression_test_generation",
    "property_based_test_generation",
    "api_test_generation",
    "integration_test_generation",
    "system_test_generation",
    "fuzzing_assistance",
    "test_repair",
    "test_completion",
]
InputContext = Literal[
    "source_code_only",
    "source_code_and_ast",
    "static_analysis_enhanced",
    "dynamic_execution_enhanced",
    "specification_driven",
    "historical_tests",
    "retrieval_augmented_context",
]
OutputArtifact = Literal[
    "test_method",
    "test_class",
    "test_suite",
    "assertion_generation",
    "input_generation",
    "fixture_generation",
]
ValidationRepair = Literal[
    "syntax_validation",
    "compile_validation",
    "runtime_validation",
    "rule_based_repair",
    "llm_based_repair",
    "iterative_feedback",
]
EvaluationScope = Literal[
    "toy_examples",
    "benchmark_datasets",
    "open_source_projects",
    "industrial_projects",
    "cross_project_evaluation",
]
ContributionType = Literal[
    "framework",
    "tool",
    "benchmark",
    "empirical_study",
    "dataset",
    "prompting_strategy",
    "repair_pipeline",
]


class ResearchBackgroundAndCoreChallenge(BaseModel):
    """Research problem framing."""

    core_problem: str
    motivation_gap: str
    significance: str


class ResearchMethodologyAndDesign(BaseModel):
    """Methodological description."""

    methodology_type: str
    execution_process: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    tools_techniques: list[str] = Field(default_factory=list)
    evaluation_metrics: list[str] = Field(default_factory=list)


class KeyFindingsAndConclusions(BaseModel):
    """Findings summary."""

    major_findings: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    unexpected_insights: list[str] = Field(default_factory=list)


class ContributionsLimitationsAndImplications(BaseModel):
    """Contributions and limitations."""

    academic_contributions: list[str] = Field(default_factory=list)
    limitations_threats: list[str] = Field(default_factory=list)
    practical_implications: list[str] = Field(default_factory=list)


class AnalysisBody(BaseModel):
    """Full analysis body."""

    research_background_and_core_challenge: ResearchBackgroundAndCoreChallenge
    research_methodology_and_design: ResearchMethodologyAndDesign
    key_findings_and_conclusions: KeyFindingsAndConclusions
    contributions_limitations_and_implications: ContributionsLimitationsAndImplications
    concise_summary: str


class ClassificationResult(BaseModel):
    """Taxonomy classification for survey building."""

    method_paradigm: MethodParadigm
    target_languages: list[TargetLanguage] = Field(default_factory=list)
    test_task_types: list[TestTaskType] = Field(default_factory=list)
    input_context: list[InputContext] = Field(default_factory=list)
    output_artifact: list[OutputArtifact] = Field(default_factory=list)
    validation_repair: list[ValidationRepair] = Field(default_factory=list)
    evaluation_scope: list[EvaluationScope] = Field(default_factory=list)
    contribution_type: list[ContributionType] = Field(default_factory=list)

    @field_validator(
        "target_languages",
        "test_task_types",
        "input_context",
        "output_artifact",
        "validation_repair",
        "evaluation_scope",
        "contribution_type",
    )
    @classmethod
    def deduplicate_items(cls, values: list[str]) -> list[str]:
        """Keep stable deduplicated values."""

        return list(dict.fromkeys(values))


class LatexFields(BaseModel):
    """Fields used to render per-paper LaTeX entries."""

    short_citation_key: str
    paper_label: str
    one_paragraph_summary: str
    method_steps: list[str] = Field(default_factory=list)
    experimental_setup: list[str] = Field(default_factory=list)
    main_results: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    tags_for_survey: list[str] = Field(default_factory=list)


class PaperAnalysisSchema(BaseModel):
    """Machine-readable source of truth for paper analysis."""

    paper_id: str
    title: str
    venue: str
    year: int
    analysis: AnalysisBody
    classification: ClassificationResult
    latex_fields: LatexFields


class AnalysisArtifactBundle(BaseModel):
    """Persisted metadata for LLM analysis output."""

    analysis: PaperAnalysisSchema
    model: str
    provider: str
    prompt_version: str
    raw_response: str | None = None
