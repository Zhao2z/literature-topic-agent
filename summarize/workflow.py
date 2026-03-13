"""Topic-level LLM analysis and survey building workflows."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.logging import get_logger
from domain.models import JobStageCounts, PaperRecord, PaperStatus, ProcessingJob, TopicConfig
from domain.normalization import normalize_title
from providers.dblp_bibtex import DblpBibtexClient
from storage.json_store import JsonArtifactStore
from storage.sqlite_store import SQLiteStore
from summarize.analyzer import PaperAnalyzer
from summarize.prompts import SURVEY_ENTRY_PROMPT_VERSION
from summarize.renderer import AnalysisRenderer
from summarize.schemas import PaperAnalysisSchema
from summarize.taxonomy import normalize_analysis_payload
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
VENUE_ABBREVIATIONS = {
    "IEEE Trans. Software Eng.": "TSE",
    "ACM Trans. Softw. Eng. Methodol.": "TOSEM",
}
UNICODE_LATEX_REPLACEMENTS = {
    "τ": r"$\tau$",
    "α": r"$\alpha$",
    "β": r"$\beta$",
    "γ": r"$\gamma$",
    "λ": r"$\lambda$",
    "μ": r"$\mu$",
    "σ": r"$\sigma$",
    "Δ": r"$\Delta$",
    "≤": r"$\leq$",
    "≥": r"$\geq$",
    "≈": r"$\approx$",
    "≠": r"$\neq$",
    "±": r"$\pm$",
    "∼": r"$\sim$",
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
        auto_build_survey: bool = False,
        auto_compile_survey: bool = False,
    ) -> None:
        self.analyzer = analyzer
        self.renderer = renderer
        self.sqlite_store = sqlite_store
        self.json_store = json_store
        self.auto_build_survey = auto_build_survey
        self.auto_compile_survey = auto_compile_survey

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
        for paper in papers:
            _repair_workspace_paths(paper, workspace=workspace)
            _recover_existing_analysis_state(paper)
        candidates = self._select_candidates(papers, top_n=top_n, allowed_ccf=allowed_ccf, force=force)
        LOGGER.bind(topic=topic_config.slug, candidates=len(candidates), model=self.analyzer.model_name).info("Starting LLM analysis workflow")
        reusable_analysis = _build_analysis_reuse_index(papers)
        analyzed_count = 0
        for paper in candidates:
            resolved_sections_path = _resolve_sections_artifact_path(paper)
            if resolved_sections_path is None:
                paper.analysis_warnings = ["missing_sections_artifact"]
                paper.last_error = "Missing sections.json artifact"
                continue
            sections_path = str(resolved_sections_path)
            paper.parse_artifact_paths["sections"] = sections_path
            if paper.llm_analysis and _needs_survey_entry_backfill(paper):
                try:
                    analysis = PaperAnalysisSchema.model_validate(normalize_analysis_payload(paper.llm_analysis))
                    citation_key = analysis.latex_fields.short_citation_key
                    survey_entry_text, survey_entry_messages = self.analyzer.generate_survey_entry(
                        analysis=analysis,
                        citation_key=citation_key,
                    )
                    artifact_paths = dict(paper.analysis_artifact_paths)
                    artifact_paths.update(
                        _write_survey_entry_artifacts(
                            survey_entry_text=survey_entry_text,
                            survey_entry_messages=survey_entry_messages,
                            model_name=self.analyzer.model_name,
                            sections_path=resolved_sections_path,
                        )
                    )
                    paper.analysis_artifact_paths = artifact_paths
                    paper.analysis_model = paper.analysis_model or self.analyzer.model_name
                    paper.analysis_warnings = []
                    paper.status = PaperStatus.ANALYZED
                    paper.timestamps.analyzed_at = paper.timestamps.analyzed_at or datetime.now(timezone.utc)
                    paper.timestamps.updated_at = datetime.now(timezone.utc)
                    _persist_analysis_progress(
                        papers=papers,
                        topic_slug=topic_config.slug,
                        json_store=self.json_store,
                        sqlite_store=self.sqlite_store,
                    )
                    analyzed_count += 1
                    continue
                except ValidationError:
                    LOGGER.bind(paper_id=paper.paper_id).warning("Skipping survey entry backfill because stored analysis no longer validates")
                    continue
            reused_from = _find_reusable_analysis(paper=paper, reusable_analysis=reusable_analysis)
            if reused_from is not None:
                _reuse_existing_analysis(source=reused_from, target=paper, sections_path=resolved_sections_path)
                _persist_analysis_progress(
                    papers=papers,
                    topic_slug=topic_config.slug,
                    json_store=self.json_store,
                    sqlite_store=self.sqlite_store,
                )
                analyzed_count += 1
                continue
            try:
                bundle = self.analyzer.analyze(paper_record=paper.model_dump(mode="json"), sections_path=resolved_sections_path)
                citation_key = bundle.analysis.latex_fields.short_citation_key
                survey_entry_text, survey_entry_messages = self.analyzer.generate_survey_entry(
                    analysis=bundle.analysis,
                    citation_key=citation_key,
                )
                artifact_paths = _write_analysis_artifacts(renderer=self.renderer, bundle=bundle, sections_path=resolved_sections_path)
                survey_entry_paths = _write_survey_entry_artifacts(
                    survey_entry_text=survey_entry_text,
                    survey_entry_messages=survey_entry_messages,
                    model_name=self.analyzer.model_name,
                    sections_path=resolved_sections_path,
                )
                artifact_paths.update(survey_entry_paths)
                paper.llm_analysis = bundle.analysis.model_dump(mode="json")
                paper.classification = bundle.analysis.classification.model_dump(mode="json")
                paper.analysis_artifact_paths = artifact_paths
                paper.analysis_model = bundle.model
                paper.analysis_warnings = []
                paper.last_error = None
                paper.status = PaperStatus.ANALYZED
                paper.timestamps.analyzed_at = datetime.now(timezone.utc)
                paper.timestamps.updated_at = paper.timestamps.analyzed_at
                reusable_analysis = _build_analysis_reuse_index(papers)
                _persist_analysis_progress(
                    papers=papers,
                    topic_slug=topic_config.slug,
                    json_store=self.json_store,
                    sqlite_store=self.sqlite_store,
                )
                analyzed_count += 1
            except Exception as exc:  # pragma: no cover - exercised by workflow tests with fakes
                paper.analysis_warnings = [f"analysis_failed:{type(exc).__name__}"]
                paper.last_error = str(exc)
                paper.timestamps.updated_at = datetime.now(timezone.utc)
                LOGGER.bind(paper_id=paper.paper_id, title=paper.title, error_type=type(exc).__name__, error=str(exc)).warning(
                    "Skipping paper after analysis failure"
                )
                _persist_analysis_progress(
                    papers=papers,
                    topic_slug=topic_config.slug,
                    json_store=self.json_store,
                    sqlite_store=self.sqlite_store,
                )
                continue

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
        if self.auto_build_survey:
            builder = SurveyBuilder(renderer=self.renderer, template_root=self.renderer.template_root)
            builder.build(topic_config=topic_config, workspace=workspace, papers=papers)
            if self.auto_compile_survey:
                compile_survey_report(workspace=workspace)
        LOGGER.bind(topic=topic_config.slug, analyzed=analyzed_count, analyzed_total=job.processed_counts.analyzed).info("Completed LLM analysis workflow")
        return papers, job

    def _select_candidates(self, papers: list[PaperRecord], *, top_n: int, allowed_ccf: set[str], force: bool) -> list[PaperRecord]:
        eligible = [
            paper
            for paper in papers
            if paper.status in {PaperStatus.PARSED, PaperStatus.ANALYZED}
            and paper.ccf_rank in allowed_ccf
            and (force or not paper.llm_analysis or _needs_survey_entry_backfill(paper))
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
    llm_prompt_path = artifact_dir / "llm_prompt.json"
    markdown_path = artifact_dir / "llm_analysis.md"
    latex_path = artifact_dir / "llm_analysis.tex"
    classification_path = artifact_dir / "classification.json"
    if not llm_prompt_path.exists():
        llm_prompt_path.write_text(
            json.dumps(
                {
                    "model": bundle.model,
                    "provider": bundle.provider,
                    "prompt_version": bundle.prompt_version,
                    "messages": bundle.prompt_messages,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    llm_analysis_path.write_text(json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(renderer.render_markdown(bundle.analysis), encoding="utf-8")
    latex_path.write_text(renderer.render_paper_latex(bundle.analysis), encoding="utf-8")
    classification_path.write_text(json.dumps(bundle.analysis.classification.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "llm_prompt": str(llm_prompt_path),
        "llm_analysis": str(llm_analysis_path),
        "llm_analysis_md": str(markdown_path),
        "llm_analysis_tex": str(latex_path),
        "classification": str(classification_path),
    }


def _write_survey_entry_artifacts(
    *,
    survey_entry_text: str,
    survey_entry_messages: list[dict[str, str]],
    model_name: str,
    sections_path: Path,
) -> dict[str, str]:
    artifact_dir = sections_path.parent
    survey_entry_path = artifact_dir / "survey_entry.tex"
    survey_prompt_path = artifact_dir / "survey_entry_prompt.json"
    sanitized_entry = _sanitize_latex_fragment(survey_entry_text.strip())
    survey_entry_path.write_text(sanitized_entry + "\n", encoding="utf-8")
    survey_prompt_path.write_text(
        json.dumps(
            {
                "model": model_name,
                "prompt_version": SURVEY_ENTRY_PROMPT_VERSION,
                "messages": survey_entry_messages,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "survey_entry_tex": str(survey_entry_path),
        "survey_entry_prompt": str(survey_prompt_path),
    }


def compile_survey_report(*, workspace: TopicWorkspace, engine: str = "latexmk") -> None:
    """Compile the generated survey LaTeX report."""

    survey_dir = workspace.reports_dir / "survey"
    _clean_stale_latex_artifacts(survey_dir=survey_dir)
    executable = _resolve_executable(engine)
    if engine == "latexmk":
        command = [executable, "-xelatex", "main.tex"]
    else:
        command = [executable, "main.tex"]
    env = os.environ.copy()
    texbin = "/Library/TeX/texbin"
    env["PATH"] = f"{texbin}:{env.get('PATH', '')}" if texbin not in env.get("PATH", "") else env.get("PATH", "")
    subprocess.run(command, cwd=survey_dir, check=True, env=env)


def _resolve_executable(engine: str) -> str:
    resolved = shutil.which(engine)
    if resolved:
        return resolved
    common_tex_bin = Path("/Library/TeX/texbin") / engine
    if common_tex_bin.exists():
        return str(common_tex_bin)
    raise FileNotFoundError(f"Compiler executable not found: {engine}")


def _clean_stale_latex_artifacts(*, survey_dir: Path) -> None:
    for suffix in (".aux", ".toc", ".out", ".bbl", ".blg", ".fdb_latexmk", ".fls", ".xdv"):
        candidate = survey_dir / f"main{suffix}"
        if candidate.exists():
            candidate.unlink()


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


def _persist_analysis_progress(
    *,
    papers: list[PaperRecord],
    topic_slug: str,
    json_store: JsonArtifactStore,
    sqlite_store: SQLiteStore,
) -> ProcessingJob:
    job = ProcessingJob(
        topic_slug=topic_slug,
        total_papers=len(papers),
        processed_counts=_build_stage_counts(papers),
        eta_seconds=0,
        updated_at=datetime.now(timezone.utc),
    )
    sqlite_store.upsert_papers(papers)
    sqlite_store.save_job(job)
    json_store.save_papers(papers)
    json_store.save_job(job)
    return job


def _resolve_sections_artifact_path(paper: PaperRecord) -> Path | None:
    stored_path = paper.parse_artifact_paths.get("sections")
    if stored_path:
        path = Path(stored_path)
        if path.exists():
            return path
    if paper.local_pdf_path:
        pdf_path = Path(paper.local_pdf_path)
        derived_path = pdf_path.with_suffix("") / "sections.json"
        if derived_path.exists():
            return derived_path
    return None


def _repair_workspace_paths(paper: PaperRecord, *, workspace: TopicWorkspace) -> None:
    paper.local_pdf_path = _relocate_topic_path(paper.local_pdf_path, workspace=workspace, topic_slug=paper.topic_slug)
    repaired_parse_paths: dict[str, str] = {}
    for key, value in paper.parse_artifact_paths.items():
        repaired = _relocate_topic_path(value, workspace=workspace, topic_slug=paper.topic_slug)
        repaired_parse_paths[key] = repaired or value
    paper.parse_artifact_paths = repaired_parse_paths
    repaired_analysis_paths: dict[str, str] = {}
    for key, value in paper.analysis_artifact_paths.items():
        repaired = _relocate_topic_path(value, workspace=workspace, topic_slug=paper.topic_slug)
        repaired_analysis_paths[key] = repaired or value
    paper.analysis_artifact_paths = repaired_analysis_paths


def _recover_existing_analysis_state(paper: PaperRecord) -> None:
    if paper.llm_analysis and paper.analysis_artifact_paths:
        return
    sections_path = _resolve_sections_artifact_path(paper)
    if sections_path is None:
        return
    artifact_dir = sections_path.parent
    llm_analysis_path = artifact_dir / "llm_analysis.json"
    if not llm_analysis_path.exists():
        return
    try:
        payload = json.loads(llm_analysis_path.read_text(encoding="utf-8"))
        analysis = PaperAnalysisSchema.model_validate(normalize_analysis_payload(payload))
    except Exception:
        return
    paper.llm_analysis = analysis.model_dump(mode="json")
    paper.classification = analysis.classification.model_dump(mode="json")
    paper.analysis_model = paper.analysis_model or _read_analysis_model(artifact_dir=artifact_dir)
    paper.analysis_artifact_paths = _merge_analysis_artifact_paths(paper=paper, artifact_dir=artifact_dir)
    paper.analysis_warnings = [warning for warning in paper.analysis_warnings if not warning.startswith("analysis_failed:")]
    paper.last_error = None
    paper.status = PaperStatus.ANALYZED
    paper.timestamps.analyzed_at = paper.timestamps.analyzed_at or datetime.now(timezone.utc)
    paper.timestamps.updated_at = datetime.now(timezone.utc)


def _relocate_topic_path(path_value: str | None, *, workspace: TopicWorkspace, topic_slug: str) -> str | None:
    if not path_value:
        return path_value
    candidate = Path(path_value)
    if candidate.exists():
        return str(candidate)
    parts = candidate.parts
    if topic_slug not in parts:
        return path_value
    topic_index = parts.index(topic_slug)
    relocated = workspace.root_dir / Path(*parts[topic_index:])
    return str(relocated)


def _group_papers_for_survey(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for paper in papers:
        analysis = paper["analysis"]
        analysis["survey_entry_tex"] = paper.get("survey_entry_tex", "")
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
            entries.append(_prepare_bibtex_entry(bibtex=bibtex, citation_key=citation_key))
        else:
            entries.append(_build_fallback_bibtex(paper=paper["paper"], citation_key=citation_key))
    return "\n\n".join(entries).strip() + ("\n" if entries else "")


def _rewrite_bibtex_key(*, bibtex: str, citation_key: str) -> str:
    return re.sub(r"^(@\w+\{)\s*([^,]+)", rf"\1{citation_key}", bibtex.strip(), count=1, flags=re.MULTILINE)


def _build_fallback_bibtex(*, paper: PaperRecord, citation_key: str) -> str:
    authors = " and ".join(_sanitize_bibtex_value(author) for author in paper.authors) if paper.authors else "Unknown"
    safe_title = _sanitize_bibtex_value(paper.title)
    safe_venue = _sanitize_bibtex_value(paper.venue)
    url = paper.dblp_url or paper.landing_url or paper.pdf_url or ""
    lines = [
        f"@misc{{{citation_key},",
        f"  title = {{{safe_title}}},",
        f"  author = {{{authors}}},",
        f"  year = {{{paper.year}}},",
        f"  howpublished = {{{safe_venue}}},",
    ]
    if url:
        lines.append(f"  url = {{{_sanitize_bibtex_value(url)}}},")
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
            sanitize_bibtex = getattr(dblp_bibtex_client, "sanitize_bibtex", DblpBibtexClient.sanitize_bibtex)
            bibtex = sanitize_bibtex(bibtex)
            dblp_key = dblp_bibtex_client.extract_citation_key(bibtex)
            if dblp_key:
                citation_key = dblp_key
            analysis.setdefault("latex_fields", {})["short_citation_key"] = citation_key
        survey_entry_tex = _load_survey_entry_tex(paper=paper, citation_key=citation_key)
        enriched.append(
            {
                "paper": paper,
                "analysis": analysis,
                "bibtex": bibtex,
                "citation_key": citation_key,
                "survey_entry_tex": survey_entry_tex,
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


def _load_survey_entry_tex(*, paper: PaperRecord, citation_key: str) -> str:
    path_value = paper.analysis_artifact_paths.get("survey_entry_tex")
    if not path_value:
        return ""
    path = Path(path_value)
    if not path.exists():
        return ""
    content = _normalize_venue_abbreviations(_sanitize_latex_fragment(path.read_text(encoding="utf-8").strip()))
    if not content:
        return ""
    return re.sub(r"\\cite\{[^}]+\}", rf"\\cite{{{citation_key}}}", content)


def _needs_survey_entry_backfill(paper: PaperRecord) -> bool:
    path_value = paper.analysis_artifact_paths.get("survey_entry_tex")
    if not path_value:
        return True
    return not Path(path_value).exists()


def _sanitize_latex_fragment(text: str) -> str:
    """Escape common special characters in LLM-generated LaTeX fragments."""

    sanitized = html.unescape(text.replace("\r\n", "\n").replace("\r", "\n"))
    for source, target in {
        "%": r"\%",
        "&": r"\&",
        "#": r"\#",
        "$": r"\$",
        "_": r"\_",
    }.items():
        sanitized = re.sub(rf"(?<!\\){re.escape(source)}", target, sanitized)
    return _normalize_unicode_for_latex(sanitized)


def _prepare_bibtex_entry(*, bibtex: str, citation_key: str) -> str:
    sanitized = DblpBibtexClient.sanitize_bibtex(bibtex)
    return _rewrite_bibtex_key(bibtex=sanitized, citation_key=citation_key)


def _sanitize_bibtex_value(value: str) -> str:
    sanitized = _normalize_unicode_for_latex(html.unescape(value).replace("\r\n", " ").replace("\r", " ").replace("\n", " "))
    sanitized = sanitized.replace("{", "").replace("}", "")
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    sanitized = re.sub(r"(?<!\\)&", r"\\&", sanitized)
    return sanitized


def _read_analysis_model(*, artifact_dir: Path) -> str | None:
    llm_prompt_path = artifact_dir / "llm_prompt.json"
    if not llm_prompt_path.exists():
        return None
    try:
        payload = json.loads(llm_prompt_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    model = payload.get("model")
    return model if isinstance(model, str) and model else None


def _merge_analysis_artifact_paths(*, paper: PaperRecord, artifact_dir: Path) -> dict[str, str]:
    merged = dict(paper.analysis_artifact_paths)
    known_paths = {
        "llm_prompt": artifact_dir / "llm_prompt.json",
        "llm_analysis": artifact_dir / "llm_analysis.json",
        "llm_analysis_md": artifact_dir / "llm_analysis.md",
        "llm_analysis_tex": artifact_dir / "llm_analysis.tex",
        "classification": artifact_dir / "classification.json",
        "survey_entry_tex": artifact_dir / "survey_entry.tex",
        "survey_entry_prompt": artifact_dir / "survey_entry_prompt.json",
    }
    for key, path in known_paths.items():
        if path.exists():
            merged[key] = str(path)
    return merged


def _normalize_unicode_for_latex(text: str) -> str:
    normalized = html.unescape(text)
    for source, target in UNICODE_LATEX_REPLACEMENTS.items():
        normalized = normalized.replace(source, target)
    return normalized


def _normalize_venue_abbreviations(text: str) -> str:
    normalized = text
    for source, target in VENUE_ABBREVIATIONS.items():
        normalized = normalized.replace(source, target)
    return normalized
