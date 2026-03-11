from parse.section_normalizer import normalize_section_name


def test_normalize_section_name_maps_common_aliases() -> None:
    assert normalize_section_name("1 Introduction").canonical_name == "introduction"
    assert normalize_section_name("Related Work").canonical_name == "related_work"
    assert normalize_section_name("Conclusion and Future Work").canonical_name == "conclusion"
    assert normalize_section_name("Experimental Results").canonical_name == "results"


def test_normalize_section_name_leaves_unknown_heading_unmapped() -> None:
    decision = normalize_section_name("Dataset Description")

    assert decision.canonical_name is None
    assert "no_canonical_mapping" in decision.reasons
