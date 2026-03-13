"""Prompt construction and optimization for structured paper analysis."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Any

from summarize.schemas import PaperAnalysisSchema

PROMPT_VERSION = "analysis-v2"
SURVEY_ENTRY_PROMPT_VERSION = "survey-entry-v1"
EXCLUDED_SECTION_KEYS = {"references"}
EXPERIMENT_SECTION_KEYS = {"experiments", "evaluation", "results"}
SECONDARY_SECTION_KEYS = {"background", "related_work", "implementation"}
FOCUS_SECTION_KEYS = ["abstract", "introduction", "approach", "method", "model", "implementation", "evaluation", "experiments", "results", "conclusion", "limitations"]
NOISE_PATTERNS = [
    re.compile(r"\b\d{4}\s+ieee(?:/acm)?\b", re.IGNORECASE),
    re.compile(r"\bpersonal use is permitted\b", re.IGNORECASE),
    re.compile(r"\bdoi:\s*10\.\d{4,9}/\S+\b", re.IGNORECASE),
    re.compile(r"\b10\.\d{4,9}/\S+\b"),
    re.compile(r"\bdownloaded on .+ ieee xplore\b", re.IGNORECASE),
    re.compile(r"\bauthorized licensed use limited to\b", re.IGNORECASE),
    re.compile(r"\brestrictions apply\.?\b", re.IGNORECASE),
]
WHITESPACE_RE = re.compile(r"[ \t]+")
BLANK_RE = re.compile(r"\n{3,}")
RELEVANT_PARAGRAPH_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\brq\d+\b",
        r"\bresearch question\b",
        r"\bsetup\b",
        r"\bdataset\b",
        r"\bbenchmark\b",
        r"\bproject(s)?\b",
        r"\bsubject(s)?\b",
        r"\bmetric(s)?\b",
        r"\bbaseline(s)?\b",
        r"\bcompare(d|s|ison)?\b",
        r"\bresult(s)?\b",
        r"\bfind(ing|ings)\b",
        r"\bimprov(e|es|ed|ement)\b",
        r"\bmutant(s)?\b",
        r"\bdefects4j\b",
        r"\baccuracy\b",
        r"\bprecision\b",
        r"\brecall\b",
        r"\bf1\b",
        r"\bbleu\b",
        r"\bpass@k\b",
    )
]
MAX_PARAGRAPHS_PER_EXPERIMENT_SECTION = 8
MAX_PARAGRAPHS_PER_SECONDARY_SECTION = 6
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
TABLE_LINE_PATTERNS = [
    re.compile(r"^table\s+[ivx\d]+", re.IGNORECASE),
    re.compile(r"^fig(?:ure)?\s+[ivx\d]+", re.IGNORECASE),
]


@dataclass(slots=True)
class PromptBuildResult:
    """Optimized prompt package for one paper."""

    messages: list[dict[str, str]]
    paper_context: dict[str, Any]
    prompt_stats: dict[str, Any]


def build_analysis_prompt(*, paper_context: dict[str, Any], model_name: str) -> PromptBuildResult:
    """Build optimized messages and prompt stats for one paper."""

    optimized_paper, section_stats = _optimize_paper_context(paper_context)
    schema_hint = PaperAnalysisSchema.model_json_schema()
    system_prompt = (
        "你是学术综述分析助手。"
        "必须仅输出一个合法 JSON 对象，不得输出 Markdown、解释、代码块或额外文本。"
        "输出语言使用简体中文。"
        "重要技术术语首次出现时使用“中文术语 (English Term)”格式。"
        "语气必须正式、客观、学术化，不使用第一人称。"
        "必须优先根据 title、focus_context、abstract、introduction、method/approach、evaluation/results、conclusion 中的明确信息完成分析。"
        "必须尽量从 evaluation/results 中提取实验对象、baseline 方法、关键指标和主要结果；"
        "如果论文明确列出对比方法，不得遗漏。"
        "只有在这些内容中都无法支持判断时，才能填写“文中未明确提及 (Not explicitly mentioned)”。"
        "分类字段必须严格遵循 schema 中的枚举值。"
    )
    user_payload = {
        "task": "基于论文已解析章节生成结构化综述分析 JSON",
        "model": model_name,
        "schema": schema_hint,
        "focus_context": _build_focus_context(optimized_paper),
        "paper": optimized_paper,
    }
    user_prompt = json.dumps(user_payload, ensure_ascii=False, indent=2)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    prompt_stats = {
        "prompt_version": PROMPT_VERSION,
        "section_stats": section_stats,
        "included_sections": list(optimized_paper.get("sections", {}).keys()),
        "system_chars": len(system_prompt),
        "system_estimated_tokens": _estimate_tokens(system_prompt),
        "user_chars": len(user_prompt),
        "user_estimated_tokens": _estimate_tokens(user_prompt),
        "total_chars": len(system_prompt) + len(user_prompt),
        "total_estimated_tokens": _estimate_tokens(system_prompt) + _estimate_tokens(user_prompt),
    }
    return PromptBuildResult(messages=messages, paper_context=optimized_paper, prompt_stats=prompt_stats)


def build_survey_entry_messages(
    *,
    analysis_payload: dict[str, Any],
    citation_key: str,
    model_name: str,
) -> list[dict[str, str]]:
    """Build a compact prompt for per-paper survey LaTeX generation."""

    system_prompt = (
        "你是学术综述写作助手。"
        "你只输出一段可直接嵌入 LaTeX itemize 环境的单篇论文条目。"
        "必须仅输出 LaTeX 片段，不得输出解释、Markdown、代码块或额外文本。"
        "语气正式、客观、简洁，使用简体中文。"
        "必须使用合法、可编译的 LaTeX 语法；出现 %, _, &, #, $ 等特殊字符时必须正确转义。"
        "只能基于提供的结构化 JSON 改写，不得补充 JSON 中不存在的新事实。"
        "若某些字段为空数组或为“文中未明确提及 (Not explicitly mentioned)”，则自然省略，不要机械复述缺失信息。"
        "实验与结论段如存在 baseline_methods，必须自然地写出对比基线方法。"
        "输出格式必须遵循给定模板：先输出一个 \\item 行，再输出两段 \\par 文本。"
    )
    user_payload = {
        "task": "根据结构化论文分析生成单篇 survey LaTeX 条目",
        "model": model_name,
        "citation_key": citation_key,
        "template": (
            "\\item <year> - <venue> - <title> ~\\cite{<citation_key>}\n"
            "\\par\n"
            "\\textbf{方法与问题。} <一段通顺文字，概括问题、方法与核心流程。>\n"
            "\\par\n"
            "\\textbf{实验与结论。} <一段通顺文字，概括实验设置、baseline 方法、主要结果、局限与标签。>"
        ),
        "paper": analysis_payload,
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, indent=2)},
    ]


def _optimize_paper_context(paper_context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    optimized = {key: value for key, value in paper_context.items() if key != "sections"}
    optimized_sections: dict[str, dict[str, str]] = {}
    section_stats: dict[str, dict[str, Any]] = {}
    for key, section in paper_context.get("sections", {}).items():
        title = str(section.get("title", ""))
        content = str(section.get("content", ""))
        stats: dict[str, Any] = {
            "title": title,
            "original_chars": len(content),
            "original_estimated_tokens": _estimate_tokens(content),
            "included": False,
            "truncated": False,
            "notes": [],
        }
        if key in EXCLUDED_SECTION_KEYS:
            stats["notes"].append("excluded_by_default")
            section_stats[key] = stats
            continue
        cleaned = _clean_prompt_text(content)
        stats["cleaned_chars"] = len(cleaned)
        stats["cleaned_estimated_tokens"] = _estimate_tokens(cleaned)
        final_content = cleaned
        if key in EXPERIMENT_SECTION_KEYS:
            filtered, filter_stats = _filter_experiment_paragraphs(cleaned)
            final_content = filtered
            stats.update(filter_stats)
        elif key in SECONDARY_SECTION_KEYS:
            filtered, filter_stats = _filter_secondary_section(cleaned)
            final_content = filtered
            stats.update(filter_stats)
        if not final_content.strip():
            stats["notes"].append("empty_after_cleanup")
            section_stats[key] = stats
            continue
        stats["included"] = True
        stats["final_chars"] = len(final_content)
        stats["final_estimated_tokens"] = _estimate_tokens(final_content)
        optimized_sections[key] = {"title": title, "content": final_content}
        section_stats[key] = stats
    optimized["sections"] = optimized_sections
    return optimized, section_stats


def _clean_prompt_text(text: str) -> str:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = WHITESPACE_RE.sub(" ", raw_line).strip()
        if not line:
            if lines and lines[-1]:
                lines.append("")
            continue
        if _is_noise_line(line):
            continue
        for pattern in NOISE_PATTERNS:
            line = pattern.sub("", line)
        line = WHITESPACE_RE.sub(" ", line).strip(" .")
        if line:
            lines.append(line)
    cleaned = "\n".join(lines)
    cleaned = BLANK_RE.sub("\n\n", cleaned).strip()
    return cleaned


def _is_noise_line(line: str) -> bool:
    lowered = line.lower()
    if re.fullmatch(r"\d{1,4}", line):
        return True
    if "ieee/acm" in lowered and "conference" in lowered:
        return True
    if lowered.startswith("digital object identifier"):
        return True
    if lowered.startswith("©") or lowered.startswith("copyright"):
        return True
    return any(pattern.search(line) for pattern in NOISE_PATTERNS)


def _filter_experiment_paragraphs(content: str) -> tuple[str, dict[str, Any]]:
    paragraphs = _split_experiment_units(content)
    if len(paragraphs) <= 2:
        return content, {
            "paragraph_count": len(paragraphs),
            "selected_paragraph_count": len(paragraphs),
            "truncated": False,
        }
    selected: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        if index < 2:
            selected.append(paragraph)
            continue
        if any(pattern.search(paragraph) for pattern in RELEVANT_PARAGRAPH_PATTERNS):
            selected.append(paragraph)
    deduplicated = list(dict.fromkeys(selected))
    if len(deduplicated) > MAX_PARAGRAPHS_PER_EXPERIMENT_SECTION:
        deduplicated = deduplicated[:MAX_PARAGRAPHS_PER_EXPERIMENT_SECTION]
    truncated = len(deduplicated) < len(paragraphs)
    notes: list[str] = []
    if truncated:
        notes.append("paragraph_filtered")
    filtered = "\n\n".join(deduplicated) if deduplicated else "\n\n".join(paragraphs[:2])
    return filtered, {
        "paragraph_count": len(paragraphs),
        "selected_paragraph_count": len(deduplicated) if deduplicated else min(2, len(paragraphs)),
        "truncated": truncated,
        "notes": notes,
    }


def _filter_secondary_section(content: str) -> tuple[str, dict[str, Any]]:
    paragraphs = _split_experiment_units(content)
    if len(paragraphs) <= MAX_PARAGRAPHS_PER_SECONDARY_SECTION:
        return content, {
            "paragraph_count": len(paragraphs),
            "selected_paragraph_count": len(paragraphs),
            "truncated": False,
        }
    selected: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        if index < 2:
            selected.append(paragraph)
            continue
        if any(pattern.search(paragraph) for pattern in RELEVANT_PARAGRAPH_PATTERNS):
            selected.append(paragraph)
    deduplicated = list(dict.fromkeys(selected))
    if len(deduplicated) > MAX_PARAGRAPHS_PER_SECONDARY_SECTION:
        deduplicated = deduplicated[:MAX_PARAGRAPHS_PER_SECONDARY_SECTION]
    truncated = len(deduplicated) < len(paragraphs)
    notes: list[str] = []
    if truncated:
        notes.append("secondary_section_filtered")
    filtered = "\n\n".join(deduplicated) if deduplicated else "\n\n".join(paragraphs[:MAX_PARAGRAPHS_PER_SECONDARY_SECTION])
    return filtered, {
        "paragraph_count": len(paragraphs),
        "selected_paragraph_count": len(deduplicated) if deduplicated else min(MAX_PARAGRAPHS_PER_SECONDARY_SECTION, len(paragraphs)),
        "truncated": truncated,
        "notes": notes,
    }


def _split_experiment_units(content: str) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in content.split("\n\n") if paragraph.strip()]
    paragraphs = [_strip_table_noise(paragraph) for paragraph in paragraphs]
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    if len(paragraphs) > 2:
        return paragraphs
    sentences = [sentence.strip() for sentence in SENTENCE_SPLIT_RE.split(content) if sentence.strip()]
    sentences = [_strip_table_noise(sentence) for sentence in sentences]
    sentences = [sentence for sentence in sentences if sentence]
    if len(sentences) <= 6:
        return paragraphs if paragraphs else [content.strip()]
    chunks: list[str] = []
    chunk_size = 3
    for index in range(0, len(sentences), chunk_size):
        chunk = " ".join(sentences[index : index + chunk_size]).strip()
        if chunk:
            chunks.append(chunk)
    return chunks or (paragraphs if paragraphs else [content.strip()])


def _estimate_tokens(text: str) -> int:
    """Return a rough token estimate for debugging only."""

    if not text:
        return 0
    return math.ceil(len(text) / 3)


def _build_focus_context(paper_context: dict[str, Any]) -> dict[str, str]:
    sections = paper_context.get("sections", {})
    focus_context: dict[str, str] = {}
    for key in FOCUS_SECTION_KEYS:
        section = sections.get(key)
        if not section:
            continue
        content = str(section.get("content", "")).strip()
        if not content:
            continue
        focus_context[key] = content[:1800]
    return focus_context


def _strip_table_noise(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    kept: list[str] = []
    for line in lines:
        if any(pattern.match(line) for pattern in TABLE_LINE_PATTERNS):
            continue
        if _looks_like_table_row(line):
            continue
        kept.append(line)
    return " ".join(kept).strip()


def _looks_like_table_row(line: str) -> bool:
    compact = line.strip()
    if not compact:
        return True
    if len(compact) < 6:
        return False
    digit_count = sum(char.isdigit() for char in compact)
    upper_count = sum(char.isupper() for char in compact)
    token_count = len(compact.split())
    if token_count >= 4 and digit_count >= 4:
        return True
    if token_count >= 5 and upper_count >= len(compact.replace(" ", "")) * 0.5:
        return True
    if compact.count("|") >= 2:
        return True
    return False
