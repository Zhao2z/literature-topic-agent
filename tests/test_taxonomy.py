from summarize.taxonomy import normalize_analysis_payload


def test_normalize_analysis_payload_maps_common_aliases() -> None:
    payload = {
        "classification": {
            "method_paradigm": "LLM-based",
            "target_languages": ["C/C++", "Java"],
            "test_task_types": [],
            "input_context": [],
            "output_artifact": [],
            "validation_repair": [],
            "evaluation_scope": [],
            "contribution_type": [],
        }
    }

    normalized = normalize_analysis_payload(payload)

    assert normalized["classification"]["method_paradigm"] == "llm_based"
    assert normalized["classification"]["target_languages"] == ["c_cpp", "Java"]
