"""Render analysis JSON into Markdown and LaTeX outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from summarize.schemas import PaperAnalysisSchema

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
VENUE_ABBREVIATIONS = {
    "IEEE Trans. Software Eng.": "TSE",
    "ACM Trans. Softw. Eng. Methodol.": "TOSEM",
}


class AnalysisRenderer:
    """Renderer for Markdown, per-paper LaTeX, and survey documents."""

    def __init__(self, template_root: str | Path) -> None:
        self.template_root = Path(template_root)
        self.environment = Environment(loader=FileSystemLoader(self.template_root), autoescape=False, trim_blocks=True, lstrip_blocks=True)
        self.environment.filters["latex_escape"] = _latex_escape
        self.environment.filters["latex_join"] = _latex_join
        self.environment.filters["venue_label"] = _venue_label

    def render_markdown(self, analysis: PaperAnalysisSchema) -> str:
        """Render per-paper Markdown."""

        template = self.environment.get_template("analysis/paper_analysis.md.j2")
        return template.render(paper=analysis)

    def render_paper_latex(self, analysis: PaperAnalysisSchema) -> str:
        """Render per-paper LaTeX."""

        template = self.environment.get_template("analysis/paper_analysis.tex.j2")
        return template.render(paper=analysis)

    def render_survey(self, *, topic_name: str, grouped_papers: list[dict[str, Any]]) -> dict[str, str]:
        """Render the survey main file and grouped entries."""

        return {
            "main.tex": self.environment.get_template("survey/main.tex.j2").render(topic_name=topic_name, groups=grouped_papers),
            "papers.tex": self.environment.get_template("survey/section_group.tex.j2").render(groups=grouped_papers),
        }


def _latex_escape(value: Any) -> str:
    text = str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    for source, target in UNICODE_LATEX_REPLACEMENTS.items():
        text = text.replace(source, target)
    return text


def _latex_join(values: list[Any], separator: str = "；") -> str:
    return separator.join(_latex_escape(value) for value in values)


def _venue_label(value: Any) -> str:
    text = str(value)
    return VENUE_ABBREVIATIONS.get(text, text)
