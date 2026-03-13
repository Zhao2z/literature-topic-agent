import json
from pathlib import Path

import httpx

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
        return AnalysisArtifactBundle(
            analysis=analysis,
            model="mimo-v2-flash",
            provider="mimo",
            prompt_version="v1",
            prompt_messages=[
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "user prompt"},
            ],
        )

    def generate_survey_entry(self, *, analysis, citation_key: str):  # type: ignore[no-untyped-def]
        return (
            f"\\item {analysis.year} - {analysis.venue} - {analysis.title} ~\\cite{{{citation_key}}}\n"
            "\\par\n"
            "\\textbf{方法与问题。} 摘要。\n"
            "\\par\n"
            "\\textbf{实验与结论。} 结果。\n",
            [
                {"role": "system", "content": "survey system"},
                {"role": "user", "content": "survey user"},
            ],
        )


class FailingAnalyzer(FakeAnalyzer):
    def analyze(self, *, paper_record, sections_path: Path):  # type: ignore[no-untyped-def]
        if paper_record["paper_id"] == "bad-paper":
            raise ValueError("invalid taxonomy value")
        return super().analyze(paper_record=paper_record, sections_path=sections_path)


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
    prompt_payload = json.loads((tmp_path / "a-new" / "llm_prompt.json").read_text(encoding="utf-8"))
    assert prompt_payload["messages"][0]["role"] == "system"
    assert prompt_payload["messages"][1]["role"] == "user"


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
        "llm_prompt": str((tmp_path / "source_llm_prompt.json").resolve()),
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
    assert "llm_prompt" in reused.analysis_artifact_paths


def test_analysis_workflow_backfills_missing_survey_entry_for_analyzed_paper(tmp_path: Path) -> None:
    topic = TopicConfig(topic_name="Topic", slug="topic", keyword_groups=[["test"]])
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    json_store = JsonArtifactStore(workspace.artifacts_dir)
    sqlite_store = SQLiteStore(workspace.database_path)

    paper = _build_paper(tmp_path, paper_id="analyzed", ccf_rank="A", year=2025, rank_score=9.0, title="Already Analyzed")
    paper.status = PaperStatus.ANALYZED
    paper.llm_analysis = {
        "paper_id": "analyzed",
        "title": "Already Analyzed",
        "venue": "ICSE",
        "year": 2025,
        "analysis": {
            "research_background_and_core_challenge": {
                "core_problem": "问题",
                "motivation_gap": "缺口",
                "significance": "意义",
            },
            "research_methodology_and_design": {
                "methodology_type": "方法",
                "execution_process": ["步骤"],
                "data_sources": ["数据"],
                "tools_techniques": ["技术"],
                "evaluation_metrics": ["指标"],
            },
            "key_findings_and_conclusions": {
                "major_findings": ["发现"],
                "evidence": ["证据"],
                "unexpected_insights": [],
            },
            "contributions_limitations_and_implications": {
                "academic_contributions": ["贡献"],
                "limitations_threats": ["局限"],
                "practical_implications": ["启示"],
            },
            "concise_summary": "摘要",
        },
        "classification": {
            "method_paradigm": "llm_based",
            "target_languages": ["java"],
            "test_task_types": ["unit_test_generation"],
            "input_context": ["source_code_only"],
            "output_artifact": ["test_method"],
            "validation_repair": ["compile_validation"],
            "evaluation_scope": ["benchmark_datasets"],
            "contribution_type": ["framework"],
        },
        "latex_fields": {
            "short_citation_key": "AnalyzedKey",
            "paper_label": "Already Analyzed",
            "one_paragraph_summary": "摘要",
            "method_steps": ["步骤"],
            "experimental_setup": ["设置"],
            "main_results": ["结果"],
            "limitations": ["局限"],
            "tags_for_survey": ["tag"],
        },
    }
    paper.classification = {"method_paradigm": "llm_based", "target_languages": ["java"]}
    paper.analysis_artifact_paths = {
        "llm_prompt": str((tmp_path / "analyzed" / "llm_prompt.json").resolve()),
        "llm_analysis": str((tmp_path / "analyzed" / "llm_analysis.json").resolve()),
        "llm_analysis_md": str((tmp_path / "analyzed" / "llm_analysis.md").resolve()),
        "llm_analysis_tex": str((tmp_path / "analyzed" / "llm_analysis.tex").resolve()),
        "classification": str((tmp_path / "analyzed" / "classification.json").resolve()),
    }
    analyzed_dir = tmp_path / "analyzed"
    analyzed_dir.mkdir(parents=True, exist_ok=True)
    for path in paper.analysis_artifact_paths.values():
        Path(path).write_text("{}", encoding="utf-8")

    json_store.save_papers([paper])
    sqlite_store.upsert_papers([paper])

    analyzer = FakeAnalyzer()
    workflow = AnalysisWorkflow(
        analyzer=analyzer,  # type: ignore[arg-type]
        renderer=AnalysisRenderer(Path("templates")),
        sqlite_store=sqlite_store,
        json_store=json_store,
    )

    papers, _ = workflow.run(topic_config=topic, workspace=workspace, top_n=1, allowed_ccf={"A"}, force=False)

    refreshed = papers[0]
    assert analyzer.seen == []
    assert "survey_entry_tex" in refreshed.analysis_artifact_paths
    assert Path(refreshed.analysis_artifact_paths["survey_entry_tex"]).exists()


def test_analysis_workflow_continues_after_single_paper_failure(tmp_path: Path) -> None:
    topic = TopicConfig(topic_name="Topic", slug="topic", keyword_groups=[["test"]])
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    json_store = JsonArtifactStore(workspace.artifacts_dir)
    sqlite_store = SQLiteStore(workspace.database_path)
    papers = [
        _build_paper(tmp_path, paper_id="bad-paper", ccf_rank="A", year=2025, rank_score=9.0, title="Bad Paper"),
        _build_paper(tmp_path, paper_id="good-paper", ccf_rank="A", year=2025, rank_score=8.0, title="Good Paper"),
    ]
    json_store.save_papers(papers)
    sqlite_store.upsert_papers(papers)

    workflow = AnalysisWorkflow(
        analyzer=FailingAnalyzer(),  # type: ignore[arg-type]
        renderer=AnalysisRenderer(Path("templates")),
        sqlite_store=sqlite_store,
        json_store=json_store,
    )

    papers, _ = workflow.run(topic_config=topic, workspace=workspace, top_n=2, allowed_ccf={"A"}, force=False)

    by_id = {paper.paper_id: paper for paper in papers}
    assert by_id["bad-paper"].status == PaperStatus.PARSED
    assert by_id["bad-paper"].analysis_warnings == ["analysis_failed:ValueError"]
    assert by_id["good-paper"].status == PaperStatus.ANALYZED
    persisted = {paper.paper_id: paper for paper in json_store.load_papers()}
    assert persisted["good-paper"].status == PaperStatus.ANALYZED
    assert persisted["good-paper"].llm_analysis is not None


def test_analysis_workflow_recovers_sections_path_from_local_pdf(tmp_path: Path) -> None:
    topic = TopicConfig(topic_name="Topic", slug="topic", keyword_groups=[["test"]])
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    json_store = JsonArtifactStore(workspace.artifacts_dir)
    sqlite_store = SQLiteStore(workspace.database_path)

    paper = _build_paper(tmp_path, paper_id="portable", ccf_rank="A", year=2025, rank_score=9.0, title="Portable Paper")
    paper.parse_artifact_paths["sections"] = "workspace/test-case-generation/papers/CCF-A/portable/sections.json"
    json_store.save_papers([paper])
    sqlite_store.upsert_papers([paper])

    analyzer = FakeAnalyzer()
    workflow = AnalysisWorkflow(
        analyzer=analyzer,  # type: ignore[arg-type]
        renderer=AnalysisRenderer(Path("templates")),
        sqlite_store=sqlite_store,
        json_store=json_store,
    )

    papers, _ = workflow.run(topic_config=topic, workspace=workspace, top_n=1, allowed_ccf={"A"}, force=False)

    updated = papers[0]
    assert analyzer.seen == ["portable"]
    assert Path(updated.parse_artifact_paths["sections"]).exists()
    assert updated.status == PaperStatus.ANALYZED


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
        analysis_artifact_paths={"survey_entry_tex": str((tmp_path / "survey_entry.tex").resolve())},
    )
    (tmp_path / "survey_entry.tex").write_text(
        "\\item 2025 - ICSE - Paper ~\\cite{25ICSEPaper}\n\\par\n\\textbf{方法与问题。} 自定义。\n\\par\n\\textbf{实验与结论。} 自定义结果。\n",
        encoding="utf-8",
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
    assert "\\section{ 基于大语言模型的方法 }" in papers_tex
    assert papers_tex.count("\\begin{itemize}[leftmargin=1.5em]") == 1
    assert "\\textbf{方法与问题。} 自定义。" in papers_tex
    assert "\\textbf{实验与结论。} 自定义结果。" in papers_tex
    assert "\\cite{DBLP:conf/icse/Paper2025}" in papers_tex
    assert "@inproceedings{DBLP:conf/icse/Paper2025" in output["refs.bib"].read_text(encoding="utf-8")


def test_survey_builder_sanitizes_special_characters_in_survey_entry(tmp_path: Path) -> None:
    topic = TopicConfig(topic_name="Topic", slug="topic", keyword_groups=[["test"]])
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    paper = PaperRecord(
        paper_id="paper-2",
        topic_slug="topic",
        title="Paper",
        authors=["Alice"],
        venue="ASE",
        year=2025,
        dblp_url="https://dblp.org/paper-2",
        ccf_rank="A",
        status=PaperStatus.ANALYZED,
        llm_analysis={
            "paper_id": "paper-2",
            "title": "Paper",
            "venue": "ASE",
            "year": 2025,
            "analysis": {"research_background_and_core_challenge": {"core_problem": "问题"}, "research_methodology_and_design": {"methodology_type": "方法"}, "key_findings_and_conclusions": {}, "contributions_limitations_and_implications": {}, "concise_summary": "摘要"},
            "classification": {"method_paradigm": "hybrid", "target_languages": ["python"], "input_context": ["source_code_only"]},
            "latex_fields": {"short_citation_key": "25ASEPaper", "method_steps": [], "experimental_setup": [], "main_results": [], "limitations": [], "tags_for_survey": [], "paper_label": "Paper", "one_paragraph_summary": "摘要"},
        },
        classification={"method_paradigm": "hybrid", "target_languages": ["python"]},
        analysis_artifact_paths={"survey_entry_tex": str((tmp_path / "survey_entry_special.tex").resolve())},
    )
    (tmp_path / "survey_entry_special.tex").write_text(
        "\\item 2025 - ASE - Paper ~\\cite{25ASEPaper}\n\\par\n\\textbf{方法与问题。} 覆盖率提升 35.4% 且使用 input_context，并采用 τ-way 策略。\n\\par\n\\textbf{实验与结论。} 接受率达到 85.5% 并比较 A&B，提升约 2.1∼2.5 倍。\n",
        encoding="utf-8",
    )

    class FakeDblpBibtexClient:
        def fetch_bibtex(self, dblp_url: str) -> str | None:
            return "@inproceedings{DBLP:conf/ase/Paper2025,\n  title={Paper}\n}"

        def extract_citation_key(self, bibtex: str) -> str | None:
            return "DBLP:conf/ase/Paper2025"

    output = SurveyBuilder(
        renderer=AnalysisRenderer(Path("templates")),
        template_root=Path("templates"),
        dblp_bibtex_client=FakeDblpBibtexClient(),  # type: ignore[arg-type]
    ).build(topic_config=topic, workspace=workspace, papers=[paper])

    papers_tex = output["papers.tex"].read_text(encoding="utf-8")
    assert "35.4\\%" in papers_tex
    assert "85.5\\%" in papers_tex
    assert "input\\_context" in papers_tex
    assert "A\\&B" in papers_tex
    assert "$\\tau$-way" in papers_tex
    assert "$\\sim$" in papers_tex


def test_analysis_workflow_recovers_analysis_artifacts_from_disk(tmp_path: Path) -> None:
    topic = TopicConfig(topic_name="Topic", slug="topic", keyword_groups=[["test"]])
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    json_store = JsonArtifactStore(workspace.artifacts_dir)
    sqlite_store = SQLiteStore(workspace.database_path)

    paper = _build_paper(tmp_path, paper_id="recovered", ccf_rank="A", year=2025, rank_score=9.0, title="Recovered Paper")
    artifact_dir = Path(paper.parse_artifact_paths["sections"]).parent
    llm_analysis_payload = FakeAnalyzer().analyze(paper_record=paper.model_dump(mode="json"), sections_path=Path(paper.parse_artifact_paths["sections"]))
    (artifact_dir / "llm_analysis.json").write_text(json.dumps(llm_analysis_payload.analysis.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    (artifact_dir / "llm_prompt.json").write_text(json.dumps({"model": "mimo-v2-flash"}, ensure_ascii=False, indent=2), encoding="utf-8")
    json_store.save_papers([paper])
    sqlite_store.upsert_papers([paper])

    workflow = AnalysisWorkflow(
        analyzer=FakeAnalyzer(),  # type: ignore[arg-type]
        renderer=AnalysisRenderer(Path("templates")),
        sqlite_store=sqlite_store,
        json_store=json_store,
    )

    papers, _ = workflow.run(topic_config=topic, workspace=workspace, top_n=1, allowed_ccf={"A"}, force=False)

    recovered = papers[0]
    assert recovered.status == PaperStatus.ANALYZED
    assert recovered.llm_analysis is not None
    assert recovered.analysis_model == "mimo-v2-flash"
    assert recovered.analysis_artifact_paths["llm_analysis"].endswith("llm_analysis.json")


def test_survey_builder_rewrites_and_sanitizes_bibtex_entries(tmp_path: Path) -> None:
    topic = TopicConfig(topic_name="Topic", slug="topic", keyword_groups=[["test"]])
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    survey_entry_path = tmp_path / "survey_entry_bib.tex"
    survey_entry_path.write_text(
        "\\item 2025 - ICSE - Paper ~\\cite{LocalKey}\n\\par\n\\textbf{方法与问题。} 自定义。\n\\par\n\\textbf{实验与结论。} 自定义结果。\n",
        encoding="utf-8",
    )
    paper = PaperRecord(
        paper_id="paper-bib",
        topic_slug="topic",
        title="Paper",
        authors=["Ishrak Hayet", "Marcelo d&apos;Amorim"],
        venue="ICSE",
        year=2025,
        dblp_url="https://dblp.org/rec/conf/icse/Paper2025",
        ccf_rank="A",
        status=PaperStatus.ANALYZED,
        llm_analysis={
            "paper_id": "paper-bib",
            "title": "Paper",
            "venue": "ICSE",
            "year": 2025,
            "analysis": {"research_background_and_core_challenge": {"core_problem": "问题"}, "research_methodology_and_design": {"methodology_type": "方法"}, "key_findings_and_conclusions": {}, "contributions_limitations_and_implications": {}, "concise_summary": "摘要"},
            "classification": {"method_paradigm": "llm_based", "target_languages": ["java"], "input_context": ["source_code_only"]},
            "latex_fields": {"short_citation_key": "LocalKey", "method_steps": [], "experimental_setup": [], "main_results": [], "limitations": [], "tags_for_survey": [], "paper_label": "Paper", "one_paragraph_summary": "摘要"},
        },
        classification={"method_paradigm": "llm_based", "target_languages": ["java"]},
        analysis_artifact_paths={"survey_entry_tex": str(survey_entry_path.resolve())},
        bibtex="@inproceedings{WrongKey,\n  author={Ishrak Hayet and Marcelo d&apos;Amorim},\n  title={Paper & Practice}\n}",
    )

    class FakeDblpBibtexClient:
        def fetch_bibtex(self, dblp_url: str) -> str | None:
            return None

        def extract_citation_key(self, bibtex: str) -> str | None:
            return None

        @staticmethod
        def sanitize_bibtex(bibtex: str) -> str:
            return bibtex.replace("&apos;", "'")

    output = SurveyBuilder(
        renderer=AnalysisRenderer(Path("templates")),
        template_root=Path("templates"),
        dblp_bibtex_client=FakeDblpBibtexClient(),  # type: ignore[arg-type]
    ).build(topic_config=topic, workspace=workspace, papers=[paper])

    papers_tex = output["papers.tex"].read_text(encoding="utf-8")
    refs_bib = output["refs.bib"].read_text(encoding="utf-8")
    assert "\\cite{LocalKey}" in papers_tex
    assert "@inproceedings{LocalKey," in refs_bib
    assert "d'Amorim" in refs_bib
    assert "Paper \\& Practice" in refs_bib


def test_survey_builder_normalizes_journal_venue_abbreviations(tmp_path: Path) -> None:
    topic = TopicConfig(topic_name="Topic", slug="topic", keyword_groups=[["test"]])
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    survey_entry_path = tmp_path / "survey_entry_venue.tex"
    survey_entry_path.write_text(
        "\\item 2025 - IEEE Trans. Software Eng. - Journal Paper ~\\cite{LocalKey}\n\\par\n\\textbf{方法与问题。} 自定义。\n\\par\n\\textbf{实验与结论。} 自定义结果。\n",
        encoding="utf-8",
    )
    paper = PaperRecord(
        paper_id="paper-journal",
        topic_slug="topic",
        title="Journal Paper",
        authors=["Alice"],
        venue="ACM Trans. Softw. Eng. Methodol.",
        year=2025,
        ccf_rank="A",
        status=PaperStatus.ANALYZED,
        llm_analysis={
            "paper_id": "paper-journal",
            "title": "Journal Paper",
            "venue": "ACM Trans. Softw. Eng. Methodol.",
            "year": 2025,
            "analysis": {"research_background_and_core_challenge": {"core_problem": "问题"}, "research_methodology_and_design": {"methodology_type": "方法"}, "key_findings_and_conclusions": {}, "contributions_limitations_and_implications": {}, "concise_summary": "摘要"},
            "classification": {"method_paradigm": "llm_based", "target_languages": ["java"], "input_context": ["source_code_only"]},
            "latex_fields": {"short_citation_key": "LocalKey", "method_steps": [], "experimental_setup": [], "main_results": [], "limitations": [], "tags_for_survey": [], "paper_label": "Journal Paper", "one_paragraph_summary": "摘要"},
        },
        classification={"method_paradigm": "llm_based", "target_languages": ["java"]},
        analysis_artifact_paths={"survey_entry_tex": str(survey_entry_path.resolve())},
        bibtex="@article{LocalKey,\n  title={Journal Paper}\n}",
    )
    fallback_paper = PaperRecord(
        paper_id="paper-fallback",
        topic_slug="topic",
        title="Fallback Journal Paper",
        authors=["Bob"],
        venue="ACM Trans. Softw. Eng. Methodol.",
        year=2024,
        ccf_rank="A",
        status=PaperStatus.ANALYZED,
        llm_analysis={
            "paper_id": "paper-fallback",
            "title": "Fallback Journal Paper",
            "venue": "ACM Trans. Softw. Eng. Methodol.",
            "year": 2024,
            "analysis": {
                "research_background_and_core_challenge": {"core_problem": "问题", "motivation_gap": "缺口", "significance": "意义"},
                "research_methodology_and_design": {
                    "methodology_type": "方法",
                    "execution_process": ["步骤"],
                    "data_sources": ["数据"],
                    "tools_techniques": ["技术"],
                    "evaluation_metrics": ["指标"],
                },
                "key_findings_and_conclusions": {"major_findings": ["发现"], "evidence": ["证据"], "unexpected_insights": []},
                "contributions_limitations_and_implications": {
                    "academic_contributions": ["贡献"],
                    "limitations_threats": ["局限"],
                    "practical_implications": ["启示"],
                },
                "concise_summary": "摘要",
            },
            "classification": {
                "method_paradigm": "llm_based",
                "target_languages": ["java"],
                "test_task_types": ["unit_test_generation"],
                "input_context": ["source_code_only"],
                "output_artifact": ["test_method"],
                "validation_repair": ["compile_validation"],
                "evaluation_scope": ["benchmark_datasets"],
                "contribution_type": ["framework"],
            },
            "latex_fields": {
                "short_citation_key": "FallbackKey",
                "paper_label": "Fallback Journal Paper",
                "one_paragraph_summary": "摘要",
                "method_steps": ["步骤"],
                "experimental_setup": ["设置"],
                "main_results": ["结果"],
                "limitations": ["局限"],
                "tags_for_survey": ["tag"],
            },
        },
        classification={"method_paradigm": "llm_based", "target_languages": ["java"]},
        bibtex="@article{FallbackKey,\n  title={Fallback Journal Paper}\n}",
    )

    output = SurveyBuilder(
        renderer=AnalysisRenderer(Path("templates")),
        template_root=Path("templates"),
    ).build(topic_config=topic, workspace=workspace, papers=[paper, fallback_paper])

    papers_tex = output["papers.tex"].read_text(encoding="utf-8")
    assert "IEEE Trans. Software Eng." not in papers_tex
    assert "ACM Trans. Softw. Eng. Methodol." not in papers_tex
    assert "TSE" in papers_tex
    assert "TOSEM" in papers_tex


def test_survey_builder_falls_back_when_dblp_bibtex_fetch_fails(tmp_path: Path) -> None:
    topic = TopicConfig(topic_name="Topic", slug="topic", keyword_groups=[["test"]])
    workspace = TopicWorkspace(tmp_path, topic)
    workspace.ensure()
    paper = PaperRecord(
        paper_id="paper-fallback-bib",
        topic_slug="topic",
        title="Fallback Bib Paper",
        authors=["Alice", "Bob"],
        venue="IEEE Trans. Software Eng.",
        year=2025,
        dblp_url="https://dblp.org/rec/journals/tse/0001A25",
        ccf_rank="A",
        status=PaperStatus.ANALYZED,
        llm_analysis={
            "paper_id": "paper-fallback-bib",
            "title": "Fallback Bib Paper",
            "venue": "IEEE Trans. Software Eng.",
            "year": 2025,
            "analysis": {
                "research_background_and_core_challenge": {"core_problem": "问题", "motivation_gap": "缺口", "significance": "意义"},
                "research_methodology_and_design": {
                    "methodology_type": "方法",
                    "execution_process": ["步骤"],
                    "data_sources": ["数据"],
                    "tools_techniques": ["技术"],
                    "evaluation_metrics": ["指标"],
                },
                "key_findings_and_conclusions": {"major_findings": ["发现"], "evidence": ["证据"], "unexpected_insights": []},
                "contributions_limitations_and_implications": {
                    "academic_contributions": ["贡献"],
                    "limitations_threats": ["局限"],
                    "practical_implications": ["启示"],
                },
                "concise_summary": "摘要",
            },
            "classification": {
                "method_paradigm": "llm_based",
                "target_languages": ["java"],
                "test_task_types": ["unit_test_generation"],
                "input_context": ["source_code_only"],
                "output_artifact": ["test_method"],
                "validation_repair": ["compile_validation"],
                "evaluation_scope": ["benchmark_datasets"],
                "contribution_type": ["framework"],
            },
            "latex_fields": {
                "short_citation_key": "FallbackBib2025",
                "paper_label": "Fallback Bib Paper",
                "one_paragraph_summary": "摘要",
                "method_steps": ["步骤"],
                "experimental_setup": ["设置"],
                "main_results": ["结果"],
                "limitations": ["局限"],
                "tags_for_survey": ["tag"],
            },
        },
        classification={"method_paradigm": "llm_based", "target_languages": ["java"]},
    )

    class FailingDblpBibtexClient:
        def fetch_bibtex(self, dblp_url: str) -> str | None:
            request = httpx.Request("GET", f"{dblp_url}.bib")
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError("server error", request=request, response=response)

        def extract_citation_key(self, bibtex: str) -> str | None:
            return None

    output = SurveyBuilder(
        renderer=AnalysisRenderer(Path("templates")),
        template_root=Path("templates"),
        dblp_bibtex_client=FailingDblpBibtexClient(),  # type: ignore[arg-type]
    ).build(topic_config=topic, workspace=workspace, papers=[paper])

    refs_bib = output["refs.bib"].read_text(encoding="utf-8")
    papers_tex = output["papers.tex"].read_text(encoding="utf-8")
    assert "@misc{FallbackBib2025," in refs_bib
    assert "TSE" in papers_tex
    assert "\\cite{FallbackBib2025}" in papers_tex
