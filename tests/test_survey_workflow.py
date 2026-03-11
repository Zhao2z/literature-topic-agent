from pathlib import Path

from domain.models import PaperRecord, PaperStatus, TopicConfig
from storage.json_store import JsonArtifactStore
from storage.sqlite_store import SQLiteStore
from summarize.renderer import AnalysisRenderer
from summarize.workflow import AnalysisWorkflow, SurveyBuilder
from topic.workspace import TopicWorkspace


class FakeAnalyzer:
    model_name = "mimo-v2-flash"

    def __init__(self) -> None:
        self.seen: list[str] = []

    def analyze(self, *, paper_record, sections_path: Path):  # type: ignore[no-untyped-def]
        from summarize.schemas import (
            AnalysisArtifactBundle,
            AnalysisBody,
            ClassificationResult,
            ContributionsLimitationsAndImplications,
            KeyFindingsAndConclusions,
            LatexFields,
            PaperAnalysisSchema,
            ResearchBackgroundAndCoreChallenge,
            ResearchMethodologyAndDesign,
        )

        self.seen.append(paper_record["paper_id"])
        analysis = PaperAnalysisSchema(
            paper_id=paper_record["paper_id"],
            title=paper_record["title"],
            venue=paper_record["venue"],
            year=paper_record["year"],
            analysis=AnalysisBody(
                research_background_and_core_challenge=ResearchBackgroundAndCoreChallenge(
                    core_problem="问题",
                    motivation_gap="缺口",
                    significance="意义",
                ),
                research_methodology_and_design=ResearchMethodologyAndDesign(
                    methodology_type="llm_based",
                    execution_process=["步骤"],
                    data_sources=["数据"],
                    tools_techniques=["技术"],
                    evaluation_metrics=["指标"],
                ),
                key_findings_and_conclusions=KeyFindingsAndConclusions(
                    major_findings=["发现"],
                    evidence=["证据"],
                    unexpected_insights=["洞见"],
                ),
                contributions_limitations_and_implications=ContributionsLimitationsAndImplications(
                    academic_contributions=["贡献"],
                    limitations_threats=["局限"],
                    practical_implications=["启示"],
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
                short_citation_key=f"{paper_record['year']}Key{paper_record['paper_id']}",
                paper_label=paper_record["title"],
                one_paragraph_summary="摘要",
                method_steps=["步骤"],
                experimental_setup=["设置"],
                main_results=["结果"],
                limitations=["局限"],
                tags_for_survey=["tag"],
            ),
        )
        return AnalysisArtifactBundle(analysis=analysis, model="mimo-v2-flash", provider="mimo", prompt_version="v1")


def _build_paper(tmp_path: Path, *, paper_id: str, ccf_rank: str, year: int, rank_score: float, title: str) -> PaperRecord:
    pdf_path = tmp_path / f"{paper_id}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    artifact_dir = pdf_path.with_suffix("")
    artifact_dir.mkdir(parents=True, exist_ok=True)
    sections_path = artifact_dir / "sections.json"
    sections_path.write_text(
        '{"paper_id":"%s","title":"%s","page_count":1,"sections":{"abstract":{"title":"Abstract","canonical_name":"abstract","start_page":1,"end_page":1,"content":"x"}}}'
        % (paper_id, title),
        encoding="utf-8",
    )
    return PaperRecord(
        paper_id=paper_id,
        topic_slug="topic",
        title=title,
        authors=["Alice"],
        venue="ICSE",
        year=year,
        dblp_url=f"https://dblp.org/{paper_id}",
        ccf_rank=ccf_rank,
        local_pdf_path=str(pdf_path),
        status=PaperStatus.PARSED,
        rank_score=rank_score,
        parse_artifact_paths={"sections": str(sections_path)},
    )


def test_analysis_workflow_prioritizes_ccf_and_recency(tmp_path: Path) -> None:
    topic = TopicConfig(topic_name="Topic", slug="topic", keyword_groups=[["test"]])
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    json_store = JsonArtifactStore(workspace.artifacts_dir)
    sqlite_store = SQLiteStore(workspace.database_path)
    papers = [
        _build_paper(tmp_path, paper_id="b-old", ccf_rank="B", year=2024, rank_score=8.0, title="B Old"),
        _build_paper(tmp_path, paper_id="a-new", ccf_rank="A", year=2025, rank_score=7.0, title="A New"),
        _build_paper(tmp_path, paper_id="a-old-high", ccf_rank="A", year=2024, rank_score=9.0, title="A Old High"),
    ]
    json_store.save_papers(papers)
    sqlite_store.upsert_papers(papers)

    analyzer = FakeAnalyzer()
    workflow = AnalysisWorkflow(
        analyzer=analyzer,  # type: ignore[arg-type]
        renderer=AnalysisRenderer(Path("templates")),
        sqlite_store=sqlite_store,
        json_store=json_store,
    )

    workflow.run(topic_config=topic, workspace=workspace, top_n=2, allowed_ccf={"A", "B"}, force=False)

    assert analyzer.seen == ["a-new", "a-old-high"]


def test_analysis_workflow_reuses_existing_analysis_by_title(tmp_path: Path) -> None:
    topic = TopicConfig(topic_name="Topic", slug="topic", keyword_groups=[["test"]])
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    json_store = JsonArtifactStore(workspace.artifacts_dir)
    sqlite_store = SQLiteStore(workspace.database_path)

    source = _build_paper(tmp_path, paper_id="source", ccf_rank="A", year=2025, rank_score=9.0, title="Same Title")
    source.status = PaperStatus.ANALYZED
    source.llm_analysis = {
        "paper_id": "source",
        "title": "Same Title",
        "venue": "ICSE",
        "year": 2025,
        "analysis": {"research_background_and_core_challenge": {"core_problem": "问题"}, "research_methodology_and_design": {"methodology_type": "方法"}, "key_findings_and_conclusions": {}, "contributions_limitations_and_implications": {}, "concise_summary": "摘要"},
        "classification": {"method_paradigm": "llm_based", "target_languages": ["java"], "input_context": ["source_code_only"]},
        "latex_fields": {"short_citation_key": "Key", "method_steps": [], "experimental_setup": [], "main_results": [], "limitations": [], "tags_for_survey": [], "paper_label": "Paper", "one_paragraph_summary": "摘要"},
    }
    source.classification = {"method_paradigm": "llm_based", "target_languages": ["java"]}
    source.analysis_artifact_paths = {
        "llm_analysis": str((tmp_path / "source_llm_analysis.json").resolve()),
        "llm_analysis_md": str((tmp_path / "source_llm_analysis.md").resolve()),
        "llm_analysis_tex": str((tmp_path / "source_llm_analysis.tex").resolve()),
        "classification": str((tmp_path / "source_classification.json").resolve()),
    }
    for path in source.analysis_artifact_paths.values():
        Path(path).write_text("{}", encoding="utf-8")

    duplicate = _build_paper(tmp_path, paper_id="dup", ccf_rank="A", year=2025, rank_score=8.0, title="Same Title")
    json_store.save_papers([source, duplicate])
    sqlite_store.upsert_papers([source, duplicate])

    analyzer = FakeAnalyzer()
    workflow = AnalysisWorkflow(
        analyzer=analyzer,  # type: ignore[arg-type]
        renderer=AnalysisRenderer(Path("templates")),
        sqlite_store=sqlite_store,
        json_store=json_store,
    )

    papers, _ = workflow.run(topic_config=topic, workspace=workspace, top_n=2, allowed_ccf={"A"}, force=False)

    assert analyzer.seen == []
    reused = next(p for p in papers if p.paper_id == "dup")
    assert reused.status == PaperStatus.ANALYZED
    assert reused.analysis_warnings == ["reused_analysis_from:source"]


def test_survey_builder_groups_by_taxonomy(tmp_path: Path) -> None:
    topic = TopicConfig(topic_name="Topic", slug="topic", keyword_groups=[["test"]])
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    paper = PaperRecord(
        paper_id="paper-1",
        topic_slug="topic",
        title="Paper",
        authors=["Alice"],
        venue="ICSE",
        year=2025,
        dblp_url="https://dblp.org/paper-1",
        ccf_rank="A",
        status=PaperStatus.ANALYZED,
        llm_analysis={
            "paper_id": "paper-1",
            "title": "Paper",
            "venue": "ICSE",
            "year": 2025,
            "analysis": {"research_background_and_core_challenge": {"core_problem": "问题"}, "research_methodology_and_design": {"methodology_type": "方法"}, "key_findings_and_conclusions": {}, "contributions_limitations_and_implications": {}, "concise_summary": "摘要"},
            "classification": {"method_paradigm": "llm_based", "target_languages": ["java"], "input_context": ["source_code_only"]},
            "latex_fields": {"short_citation_key": "25ICSEPaper", "method_steps": [], "experimental_setup": [], "main_results": [], "limitations": [], "tags_for_survey": [], "paper_label": "Paper", "one_paragraph_summary": "摘要"},
        },
        classification={"method_paradigm": "llm_based", "target_languages": ["java"]},
    )

    class FakeDblpBibtexClient:
        def fetch_bibtex(self, dblp_url: str) -> str | None:
            return "@inproceedings{DBLP:conf/icse/Paper2025,\n  title={Paper}\n}"

        def extract_citation_key(self, bibtex: str) -> str | None:
            return "DBLP:conf/icse/Paper2025"

    output = SurveyBuilder(
        renderer=AnalysisRenderer(Path("templates")),
        template_root=Path("templates"),
        dblp_bibtex_client=FakeDblpBibtexClient(),  # type: ignore[arg-type]
    ).build(
        topic_config=topic,
        workspace=workspace,
        papers=[paper],
    )

    assert output["main.tex"].exists()
    assert output["papers.tex"].exists()
    assert output["refs.bib"].exists()
    papers_tex = output["papers.tex"].read_text(encoding="utf-8")
    assert "\\section{ llm_based }" in papers_tex
    assert papers_tex.count("\\begin{itemize}[leftmargin=1.5em]") == 1
    assert "\\textbf{方法与问题。}" in papers_tex
    assert "\\textbf{实验与结论。}" in papers_tex
    assert "\\cite{ DBLP:conf/icse/Paper2025 }" in papers_tex
    assert "@inproceedings{DBLP:conf/icse/Paper2025" in output["refs.bib"].read_text(encoding="utf-8")
