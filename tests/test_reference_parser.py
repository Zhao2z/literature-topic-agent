from parse.reference_parser import parse_reference_entries


def test_parse_reference_entries_extracts_common_fields() -> None:
    content = (
        "[4] S. B. Hossain, M. B. Dwyer, S. Elbaum, and A. Nguyen-Tuong, "
        "“Measuring and mitigating gaps in structural testing,” in 2023 IEEE/ACM 45th International "
        "Conference on Software Engineering (ICSE). IEEE, 2023, pp. 1712–1723."
    )

    entries = parse_reference_entries(content)

    assert len(entries) == 1
    entry = entries[0]
    assert entry["label"] == "[4]"
    assert entry["year"] == 2023
    assert entry["title"] == "Measuring and mitigating gaps in structural testing"
    assert entry["authors"] == ["S. B. Hossain", "M. B. Dwyer", "S. Elbaum", "A. Nguyen-Tuong"]
    assert "International Conference on Software Engineering" in (entry["venue"] or "")


def test_parse_reference_entries_supports_books_and_urls() -> None:
    content = (
        "[1] Synopsys Editorial Team, “Coverity report on the ‘goto fail’ bug,” blog post, Synopsys, "
        "Mountain View, CA, Feb. 25, 2014; https://example.com/goto-fail. "
        "[8] G. J. Myers, C. Sandler, and T. Badgett, The art of software testing. John Wiley & Sons, 2011."
    )

    entries = parse_reference_entries(content)

    assert len(entries) == 2
    assert entries[0]["url"] == "https://example.com/goto-fail"
    assert entries[0]["year"] == 2014
    assert entries[0]["authors"] == ["Synopsys Editorial Team"]
    assert entries[1]["title"] == "The art of software testing"
    assert entries[1]["year"] == 2011
    assert "John Wiley" in (entries[1]["venue"] or "")
