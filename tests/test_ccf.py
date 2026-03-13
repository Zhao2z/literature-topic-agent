from pathlib import Path

from providers.ccf import LocalCcfRankProvider


def test_ccf_mapping_is_case_insensitive(tmp_path: Path) -> None:
    mapping_path = tmp_path / "ccf.json"
    mapping_path.write_text('{"ICSE": "A", "ASE": "A", "ISSTA": "B"}', encoding="utf-8")

    provider = LocalCcfRankProvider(mapping_path)

    assert provider.get_rank("icse") == "A"
    assert provider.get_rank("ISSTA") == "B"
    assert provider.get_rank("Unknown Venue") == "Unranked"


def test_simple_json_mapping_supports_aliases_and_dblp_prefixes(tmp_path: Path) -> None:
    mapping_path = tmp_path / "ccf.json"
    mapping_path.write_text('{"TSE": "A", "ICLR": "A", "ICPC": "B"}', encoding="utf-8")

    provider = LocalCcfRankProvider(mapping_path)

    assert provider.get_rank("IEEE Trans. Software Eng.") == "A"
    assert provider.get_rank("International Conference on Learning Representations") == "A"
    assert provider.get_rank("IEEE International Conference on Program Comprehension") == "B"
    assert provider.get_rank("Unknown", "https://dblp.org/rec/journals/tse/HayetSd25") == "A"
    assert provider.get_rank("Unknown", "https://dblp.org/rec/conf/iclr/JainSR25") == "A"
    assert provider.get_rank("Unknown", "https://dblp.org/rec/conf/icpc/Foo25") == "B"


def test_simple_json_mapping_reads_override_file(tmp_path: Path) -> None:
    mapping_path = tmp_path / "ccf.json"
    mapping_path.write_text('{"ICSE": "A"}', encoding="utf-8")
    (tmp_path / "ccf_overrides.json").write_text(
        '{"venues":{"IEEE Software":"B","SEIP ICSE":"A"},"dblp_prefixes":{"/conf/date":"B"}}',
        encoding="utf-8",
    )

    provider = LocalCcfRankProvider(mapping_path)

    assert provider.get_rank("IEEE Software") == "B"
    assert provider.get_rank("SEIP ICSE") == "A"
    assert provider.get_rank("Unknown", "https://dblp.org/rec/conf/date/Foo25") == "B"


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
