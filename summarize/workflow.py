"""Topic-level LLM analysis and survey building workflows."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.logging import get_logger
from domain.models import JobStageCounts, PaperRecord, PaperStatus, ProcessingJob, TopicConfig
from domain.normalization import normalize_title
from providers.dblp_bibtex import DblpBibtexClient
from storage.json_store import JsonArtifactStore
from storage.sqlite_store import SQLiteStore
from summarize.analyzer import PaperAnalyzer
from summarize.renderer import AnalysisRenderer
from topic.workspace import TopicWorkspace

LOGGER = get_logger(__name__)

CCF_PRIORITY = {"A": 0, "B": 1, "C": 2, "Unranked": 3}
METHOD_PARADIGM_LABELS = {
    "llm_based": "基于大语言模型的方法",
    "search_based": "基于搜索的方法",
    "symbolic_execution_based": "基于符号执行的方法",
    "constraint_solving_based": "基于约束求解的方法",
    "mutation_based": "基于变异的方法",
    "retrieval_augmented": "检索增强方法",
    "hybrid": "混合方法",
    "not_explicitly_mentioned": "文中未明确提及的方法范式",
}
LANGUAGE_LABELS = {
    "java": "Java",
    "python": "Python",
    "rust": "Rust",
    "javascript": "JavaScript",
    "c_cpp": "C/C++",
    "go": "Go",
    "multi_language": "多语言",
    "language_unspecified": "语言未明确",
}


class AnalysisWorkflow:
    """Analyze parsed papers with the configured LLM."""

    def __init__(
        self,
        *,
        analyzer: PaperAnalyzer,
        renderer: AnalysisRenderer,
        sqlite_store: SQLiteStore,
        json_store: JsonArtifactStore,
    ) -> None:
        self.analyzer = analyzer
        self.renderer = renderer
        self.sqlite_store = sqlite_store
        self.json_store = json_store

    def run(
        self,
        *,
        topic_config: TopicConfig,
        workspace: TopicWorkspace,
        top_n: int,
        allowed_ccf: set[str],
        force: bool,
    ) -> tuple[list[PaperRecord], ProcessingJob]:
        """Analyze eligible parsed papers for one topic."""

        papers = self.json_store.load_papers()
        candidates = self._select_candidates(papers, top_n=top_n, allowed_ccf=allowed_ccf, force=force)
        LOGGER.bind(topic=topic_config.slug, candidates=len(candidates), model=self.analyzer.model_name).info("Starting LLM analysis workflow")
        reusable_analysis = _build_analysis_reuse_index(papers)
        analyzed_count = 0
        for paper in candidates:
            sections_path = paper.parse_artifact_paths.get("sections")
            if not sections_path or not Path(sections_path).exists():
                paper.analysis_warnings = ["missing_sections_artifact"]
                paper.last_error = "Missing sections.json artifact"
                continue
            reused_from = _find_reusable_analysis(paper=paper, reusable_analysis=reusable_analysis)
            if reused_from is not None:
                _reuse_existing_analysis(source=reused_from, target=paper, sections_path=Path(sections_path))
                analyzed_count += 1
                continue
            bundle = self.analyzer.analyze(paper_record=paper.model_dump(mode="json"), sections_path=Path(sections_path))
            artifact_paths = _write_analysis_artifacts(renderer=self.renderer, bundle=bundle, sections_path=Path(sections_path))
            paper.llm_analysis = bundle.analysis.model_dump(mode="json")
            paper.classification = bundle.analysis.classification.model_dump(mode="json")
            paper.analysis_artifact_paths = artifact_paths
            paper.analysis_model = bundle.model
            paper.analysis_warnings = []
            paper.status = PaperStatus.ANALYZED
            paper.timestamps.analyzed_at = datetime.now(timezone.utc)
            paper.timestamps.updated_at = paper.timestamps.analyzed_at
            reusable_analysis = _build_analysis_reuse_index(papers)
            analyzed_count += 1

        job = ProcessingJob(
            topic_slug=topic_config.slug,
            total_papers=len(papers),
            processed_counts=_build_stage_counts(papers),
            eta_seconds=0,
            updated_at=datetime.now(timezone.utc),
        )
        self.sqlite_store.upsert_papers(papers)
        self.sqlite_store.save_job(job)
        self.json_store.save_papers(papers)
        self.json_store.save_job(job)
        LOGGER.bind(topic=topic_config.slug, analyzed=analyzed_count, analyzed_total=job.processed_counts.analyzed).info("Completed LLM analysis workflow")
        return papers, job

    def _select_candidates(self, papers: list[PaperRecord], *, top_n: int, allowed_ccf: set[str], force: bool) -> list[PaperRecord]:
        eligible = [
            paper
            for paper in papers
            if paper.status in {PaperStatus.PARSED, PaperStatus.ANALYZED}
            and paper.ccf_rank in allowed_ccf
            and (force or not paper.llm_analysis)
            and paper.parse_artifact_paths.get("sections")
        ]
        eligible.sort(
            key=lambda paper: (
                CCF_PRIORITY.get(paper.ccf_rank, 9),
                -paper.year,
                -paper.rank_score,
                paper.processing_priority,
            )
        )
        return eligible[:top_n] if top_n > 0 else eligible


class SurveyBuilder:
    """Build a grouped survey report from analyzed papers."""

    def __init__(
        self,
        *,
        renderer: AnalysisRenderer,
        template_root: str | Path,
        dblp_bibtex_client: DblpBibtexClient | None = None,
    ) -> None:
        self.renderer = renderer
        self.template_root = Path(template_root)
        self.dblp_bibtex_client = dblp_bibtex_client or DblpBibtexClient()

    def build(self, *, topic_config: TopicConfig, workspace: TopicWorkspace, papers: list[PaperRecord]) -> dict[str, Path]:
        """Render survey files under the topic workspace."""

        target_dir = workspace.reports_dir / "survey"
        target_dir.mkdir(parents=True, exist_ok=True)
        enriched = _enrich_papers_with_bibtex(papers, dblp_bibtex_client=self.dblp_bibtex_client)
        grouped = _group_papers_for_survey(enriched)
        rendered = self.renderer.render_survey(topic_name=topic_config.topic_name, grouped_papers=grouped)
        main_path = target_dir / "main.tex"
        papers_path = target_dir / "papers.tex"
        refs_path = target_dir / "refs.bib"
        main_path.write_text(rendered["main.tex"], encoding="utf-8")
        papers_path.write_text(rendered["papers.tex"], encoding="utf-8")
        refs_path.write_text(_build_refs_bib(enriched), encoding="utf-8")
        macros_src = self.template_root / "survey" / "macros.tex"
        if macros_src.exists():
            shutil.copyfile(macros_src, target_dir / "macros.tex")
        return {"main.tex": main_path, "papers.tex": papers_path, "refs.bib": refs_path}


def _write_analysis_artifacts(*, renderer: AnalysisRenderer, bundle, sections_path: Path) -> dict[str, str]:
    artifact_dir = sections_path.parent
    llm_analysis_path = artifact_dir / "llm_analysis.json"
    markdown_path = artifact_dir / "llm_analysis.md"
    latex_path = artifact_dir / "llm_analysis.tex"
    classification_path = artifact_dir / "classification.json"
    llm_analysis_path.write_text(json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(renderer.render_markdown(bundle.analysis), encoding="utf-8")
    latex_path.write_text(renderer.render_paper_latex(bundle.analysis), encoding="utf-8")
    classification_path.write_text(json.dumps(bundle.analysis.classification.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "llm_analysis": str(llm_analysis_path),
        "llm_analysis_md": str(markdown_path),
        "llm_analysis_tex": str(latex_path),
        "classification": str(classification_path),
    }


def _build_stage_counts(papers: list[PaperRecord]) -> JobStageCounts:
    return JobStageCounts(
        discovered=len(papers),
        ranked=sum(1 for paper in papers if paper.status in {PaperStatus.RANKED, PaperStatus.DOWNLOADED, PaperStatus.PARSED, PaperStatus.ANALYZED, PaperStatus.SUMMARIZED, PaperStatus.EXPORTED}),
        downloaded=sum(1 for paper in papers if paper.local_pdf_path and Path(paper.local_pdf_path).exists()),
        parsed=sum(1 for paper in papers if paper.status in {PaperStatus.PARSED, PaperStatus.ANALYZED, PaperStatus.SUMMARIZED, PaperStatus.EXPORTED}),
        analyzed=sum(1 for paper in papers if paper.status in {PaperStatus.ANALYZED, PaperStatus.SUMMARIZED, PaperStatus.EXPORTED}),
        summarized=sum(1 for paper in papers if paper.status in {PaperStatus.SUMMARIZED, PaperStatus.EXPORTED}),
        exported=sum(1 for paper in papers if paper.status == PaperStatus.EXPORTED),
        failed=sum(1 for paper in papers if paper.status == PaperStatus.FAILED),
    )


def _group_papers_for_survey(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for paper in papers:
        analysis = paper["analysis"]
        classification = analysis.get("classification", {})
        paradigm = classification.get("method_paradigm", "not_explicitly_mentioned")
        languages = classification.get("target_languages") or ["language_unspecified"]
        paradigm_bucket = groups.setdefault(paradigm, {})
        language_bucket = paradigm_bucket.setdefault(languages[0], [])
        language_bucket.append(analysis)
    result: list[dict[str, Any]] = []
    for paradigm, by_language in sorted(groups.items()):
        language_groups = []
        for language, items in sorted(by_language.items()):
            language_groups.append(
                {
                    "language": language,
                    "language_label": LANGUAGE_LABELS.get(language, language),
                    "papers": sorted(items, key=lambda item: (-item["year"], item["title"])),
                }
            )
        result.append(
            {
                "method_paradigm": paradigm,
                "method_paradigm_label": METHOD_PARADIGM_LABELS.get(paradigm, paradigm),
                "languages": language_groups,
            }
        )
    return result


def _build_refs_bib(papers: list[dict[str, Any]]) -> str:
    entries: list[str] = []
    for paper in papers:
        citation_key = paper["citation_key"]
        bibtex = paper.get("bibtex", "").strip()
        if bibtex:
            entries.append(bibtex)
        else:
            entries.append(_build_fallback_bibtex(paper=paper["paper"], citation_key=citation_key))
    return "\n\n".join(entries).strip() + ("\n" if entries else "")


def _rewrite_bibtex_key(*, bibtex: str, citation_key: str) -> str:
    return re.sub(r"^(@\w+\{)\s*([^,]+)", rf"\1{citation_key}", bibtex.strip(), count=1, flags=re.MULTILINE)


def _build_fallback_bibtex(*, paper: PaperRecord, citation_key: str) -> str:
    authors = " and ".join(paper.authors) if paper.authors else "Unknown"
    safe_title = paper.title.replace("{", "").replace("}", "")
    safe_venue = paper.venue.replace("{", "").replace("}", "")
    url = paper.dblp_url or paper.landing_url or paper.pdf_url or ""
    lines = [
        f"@misc{{{citation_key},",
        f"  title = {{{safe_title}}},",
        f"  author = {{{authors}}},",
        f"  year = {{{paper.year}}},",
        f"  howpublished = {{{safe_venue}}},",
    ]
    if url:
        lines.append(f"  url = {{{url}}},")
    lines.append("}")
    return "\n".join(lines)


def _enrich_papers_with_bibtex(
    papers: list[PaperRecord],
    *,
    dblp_bibtex_client: DblpBibtexClient,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for paper in papers:
        if not paper.llm_analysis:
            continue
        analysis = json.loads(json.dumps(paper.llm_analysis, ensure_ascii=False))
        bibtex = (paper.bibtex or "").strip()
        citation_key = analysis.get("latex_fields", {}).get("short_citation_key") or paper.paper_id
        if not bibtex and paper.dblp_url:
            try:
                bibtex = dblp_bibtex_client.fetch_bibtex(paper.dblp_url) or ""
            except Exception:
                LOGGER.bind(paper_id=paper.paper_id, dblp_url=paper.dblp_url).warning("Failed to fetch DBLP BibTeX")
                bibtex = ""
        if bibtex:
            dblp_key = dblp_bibtex_client.extract_citation_key(bibtex)
            if dblp_key:
                citation_key = dblp_key
            analysis.setdefault("latex_fields", {})["short_citation_key"] = citation_key
        enriched.append(
            {
                "paper": paper,
                "analysis": analysis,
                "bibtex": bibtex,
                "citation_key": citation_key,
            }
        )
    return enriched


def _build_analysis_reuse_index(papers: list[PaperRecord]) -> dict[str, PaperRecord]:
    index: dict[str, PaperRecord] = {}
    for paper in papers:
        if not paper.llm_analysis:
            continue
        if paper.doi:
            index[f"doi:{paper.doi.strip().lower()}"] = paper
        index[f"title:{normalize_title(paper.title)}"] = paper
    return index


def _find_reusable_analysis(*, paper: PaperRecord, reusable_analysis: dict[str, PaperRecord]) -> PaperRecord | None:
    if paper.doi:
        match = reusable_analysis.get(f"doi:{paper.doi.strip().lower()}")
        if match is not None and match.paper_id != paper.paper_id:
            return match
    match = reusable_analysis.get(f"title:{normalize_title(paper.title)}")
    if match is not None and match.paper_id != paper.paper_id:
        return match
    return None


def _reuse_existing_analysis(*, source: PaperRecord, target: PaperRecord, sections_path: Path) -> None:
    target_dir = sections_path.parent
    copied_paths: dict[str, str] = {}
    for key, source_path in source.analysis_artifact_paths.items():
        source_file = Path(source_path)
        if not source_file.exists():
            continue
        target_file = target_dir / source_file.name
        shutil.copyfile(source_file, target_file)
        copied_paths[key] = str(target_file)
    target.llm_analysis = json.loads(json.dumps(source.llm_analysis, ensure_ascii=False))
    target.classification = json.loads(json.dumps(source.classification, ensure_ascii=False))
    target.analysis_artifact_paths = copied_paths
    target.analysis_model = source.analysis_model
    target.analysis_warnings = [f"reused_analysis_from:{source.paper_id}"]
    target.status = PaperStatus.ANALYZED
    target.timestamps.analyzed_at = datetime.now(timezone.utc)
    target.timestamps.updated_at = target.timestamps.analyzed_at
