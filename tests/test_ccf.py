from pathlib import Path

from providers.ccf import LocalCcfRankProvider


def test_ccf_mapping_is_case_insensitive(tmp_path: Path) -> None:
    mapping_path = tmp_path / "ccf.json"
    mapping_path.write_text('{"ICSE": "A", "ASE": "A", "ISSTA": "B"}', encoding="utf-8")

    provider = LocalCcfRankProvider(mapping_path)

    assert provider.get_rank("icse") == "A"
    assert provider.get_rank("ISSTA") == "B"
    assert provider.get_rank("Unknown Venue") == "Unranked"


def test_ccfrank_directory_matches_by_abbr_full_name_and_dblp_url(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ccfRankUrl.js").write_text(
        'ccf.rankUrl = {\n  "/conf/icse/icse": "A",\n  "/conf/issta/issta": "B"\n}\n',
        encoding="utf-8",
    )
    (data_dir / "ccfRankAbbr.js").write_text(
        'ccf.rankAbbrName = {\n  "/conf/icse/icse": "ICSE",\n  "/conf/issta/issta": "ISSTA"\n}\n',
        encoding="utf-8",
    )
    (data_dir / "ccfRankFull.js").write_text(
        'ccf.rankFullName = {\n  "/conf/icse/icse": "International Conference on Software Engineering",\n  "/conf/issta/issta": "International Symposium on Software Testing and Analysis"\n}\n',
        encoding="utf-8",
    )
    (data_dir / "ccfRankDb.js").write_text(
        'ccf.rankDb = {\n  "/conf/icse": "/conf/icse/icse",\n  "/conf/issta": "/conf/issta/issta"\n}\n',
        encoding="utf-8",
    )
    (data_dir / "ccfFullUrl.js").write_text(
        'ccf.fullUrl = {\n  "INTERNATIONAL CONFERENCE ON SOFTWARE ENGINEERING": "/conf/icse/icse",\n  "INTERNATIONAL SYMPOSIUM ON SOFTWARE TESTING AND ANALYSIS": "/conf/issta/issta"\n}\n',
        encoding="utf-8",
    )
    (data_dir / "ccfAbbrFull.js").write_text(
        'ccf.abbrFull = {\n  "ICSE": "INTERNATIONAL CONFERENCE ON SOFTWARE ENGINEERING",\n  "ISSTA": "INTERNATIONAL SYMPOSIUM ON SOFTWARE TESTING AND ANALYSIS"\n}\n',
        encoding="utf-8",
    )

    provider = LocalCcfRankProvider(data_dir)

    assert provider.get_rank("ICSE") == "A"
    assert provider.get_rank("International Symposium on Software Testing and Analysis") == "B"
    assert provider.get_rank(
        "Some DBLP title venue string",
        "https://dblp.org/rec/conf/icse/FooBar2024",
    ) == "A"
