from pathlib import Path

from summarize.renderer import AnalysisRenderer
from summarize.schemas import (
    AnalysisBody,
    ClassificationResult,
    ContributionsLimitationsAndImplications,
    KeyFindingsAndConclusions,
    LatexFields,
    PaperAnalysisSchema,
    ResearchBackgroundAndCoreChallenge,
    ResearchMethodologyAndDesign,
)


def build_analysis() -> PaperAnalysisSchema:
    return PaperAnalysisSchema(
        paper_id="paper-1",
        title="Test Paper",
        venue="ICSE",
        year=2025,
        analysis=AnalysisBody(
            research_background_and_core_challenge=ResearchBackgroundAndCoreChallenge(
                core_problem="核心问题",
                motivation_gap="动机缺口",
                significance="研究意义",
            ),
            research_methodology_and_design=ResearchMethodologyAndDesign(
                methodology_type="llm_based",
                execution_process=["步骤1", "步骤2"],
                data_sources=["数据集"],
                tools_techniques=["技术"],
                evaluation_metrics=["准确率"],
            ),
            key_findings_and_conclusions=KeyFindingsAndConclusions(
                major_findings=["发现1"],
                evidence=["证据1"],
                unexpected_insights=["洞见1"],
            ),
            contributions_limitations_and_implications=ContributionsLimitationsAndImplications(
                academic_contributions=["贡献1"],
                limitations_threats=["局限1"],
                practical_implications=["启示1"],
            ),
            concise_summary="摘要",
        ),
        classification=ClassificationResult(
            method_paradigm="llm_based",
            target_languages=["java"],
            test_task_types=["unit_test_generation"],
            input_context=["source_code_only"],
            output_artifact=["test_method"],
            validation_repair=["compile_validation"],
            evaluation_scope=["benchmark_datasets"],
            contribution_type=["framework"],
        ),
        latex_fields=LatexFields(
            short_citation_key="25ICSETestPaper",
            paper_label="25 - ICSE - Test Paper",
            one_paragraph_summary="一段摘要",
            method_steps=["步骤1", "步骤2"],
            experimental_setup=["设置1"],
            main_results=["结果1"],
            limitations=["局限1"],
            tags_for_survey=["llm", "java"],
        ),
    )


def test_analysis_renderer_outputs_markdown_and_latex() -> None:
    renderer = AnalysisRenderer(Path("templates"))
    analysis = build_analysis()

    markdown = renderer.render_markdown(analysis)
    latex = renderer.render_paper_latex(analysis)

    assert "# Test Paper" in markdown
    assert "研究背景与核心挑战" in markdown
    assert "\\paragraph{综合分析}" in latex
    assert "\\begin{itemize}" not in latex
    assert "25ICSETestPaper" in latex
