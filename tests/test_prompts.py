import json

from summarize.prompts import build_analysis_prompt


def test_build_analysis_prompt_excludes_references_and_taxonomy() -> None:
    paper_context = {
        "paper_id": "paper-1",
        "title": "Paper",
        "venue": "ICSE",
        "year": 2025,
        "ccf_rank": "A",
        "rank_score": 18.0,
        "sections": {
            "abstract": {"title": "Abstract", "content": "Abstract text."},
            "references": {"title": "References", "content": "[1] Ref one.\n[2] Ref two."},
        },
    }

    prompt = build_analysis_prompt(paper_context=paper_context, model_name="mimo-v2-flash")
    payload = json.loads(prompt.messages[1]["content"])

    assert "taxonomy" not in payload
    assert "references" not in payload["paper"]["sections"]
    assert "focus_context" in payload
    assert prompt.prompt_stats["section_stats"]["references"]["included"] is False


def test_build_analysis_prompt_cleans_noise_and_filters_experiment_paragraphs() -> None:
    paper_context = {
        "paper_id": "paper-2",
        "title": "Paper",
        "venue": "ICSE",
        "year": 2025,
        "sections": {
            "introduction": {
                "title": "1 Introduction",
                "content": (
                    "2025 IEEE/ACM 47th International Conference on Software Engineering\n"
                    "Digital Object Identifier 10.1109/ICSE12345.2025.00001\n"
                    "This paper studies unit test generation."
                ),
            },
            "experiments": {
                "title": "5 Evaluation",
                "content": (
                    "We evaluate TOGLL on 25 projects.\n\n"
                    "The setup uses Defects4J and mutation analysis.\n\n"
                    "Table 3 lists all raw values.\n\n"
                    "CodeLlama 72.1 74.0 81.2 79.8\n\n"
                    "RQ1: TOGLL improves assertion correctness.\n\n"
                    "We report precision and recall against baselines."
                ),
            },
        },
    }

    prompt = build_analysis_prompt(paper_context=paper_context, model_name="mimo-v2-flash")
    payload = json.loads(prompt.messages[1]["content"])
    introduction = payload["paper"]["sections"]["introduction"]["content"]
    experiments = payload["paper"]["sections"]["experiments"]["content"]

    assert "IEEE/ACM" not in introduction
    assert "10.1109/" not in introduction
    assert "Defects4J" in experiments
    assert "RQ1" in experiments
    assert "Table 3" not in experiments
    assert "CodeLlama 72.1 74.0 81.2 79.8" not in experiments
    assert prompt.prompt_stats["section_stats"]["experiments"]["selected_paragraph_count"] >= 2
    assert prompt.prompt_stats["total_chars"] > 0


def test_schema_contains_empty_array_guidance() -> None:
    prompt = build_analysis_prompt(
        paper_context={
            "paper_id": "paper-3",
            "title": "Paper",
            "venue": "ICSE",
            "year": 2025,
            "sections": {"abstract": {"title": "Abstract", "content": "text"}},
        },
        model_name="mimo-v2-flash",
    )
    payload = json.loads(prompt.messages[1]["content"])
    schema = payload["schema"]
    research_design = schema["$defs"]["ResearchMethodologyAndDesign"]["properties"]
    latex_fields = schema["$defs"]["LatexFields"]["properties"]

    assert research_design["execution_process"]["description"] == "If none, return an empty array []."
    assert latex_fields["baseline_methods"]["description"] == "If none, return an empty array []."


def test_build_analysis_prompt_filters_secondary_sections() -> None:
    background_text = "\n\n".join(
        [
            "Rust has a strict ownership model and borrow checker.",
            "Existing tools struggle with complex type dependencies.",
            "This paragraph is long but less important.",
            "Another low-signal description of ecosystem details.",
            "We compare baseline tools and report benchmark behavior.",
            "Developers need compilation-aware test generation.",
            "Additional background paragraph that should be truncated.",
        ]
    )
    prompt = build_analysis_prompt(
        paper_context={
            "paper_id": "paper-4",
            "title": "Paper",
            "venue": "ICSE",
            "year": 2025,
            "sections": {
                "abstract": {"title": "Abstract", "content": "short abstract"},
                "background": {"title": "Background", "content": background_text},
            },
        },
        model_name="mimo-v2-flash",
    )

    payload = json.loads(prompt.messages[1]["content"])
    assert "focus_context" in payload
    assert prompt.prompt_stats["section_stats"]["background"]["truncated"] is True
