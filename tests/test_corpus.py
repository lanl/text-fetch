"""Check the local document importer and its LitKit-facing JATS artifacts."""

import errno
import os
import tarfile
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from click.testing import CliRunner
from text_fetch.cli import cli
from text_fetch.corpus import document_to_jats
from text_fetch.pmc import JATSValidator, ValidationStatus


def test_markdown_headings_lists_and_source_text() -> None:
    markdown = """Gauge & field notes
===================

## Setup

- Level the **base**.
- Read the [dial](https://example.org) at `0°`.

### Reading

> Keep A < B.

```text
# literal code
```
"""
    root = ET.fromstring(document_to_jats(markdown, Path("log.md")))

    assert root.findtext(".//article-title") == "Gauge & field notes"
    assert root.findtext("./body/sec/title") == "Setup"
    assert root.findtext("./body/sec/sec/title") == "Reading"
    assert [p.text for p in root.findall("./body//p")] == [
        "Level the base.",
        "Read the dial at 0°.",
        "Keep A < B.",
        "# literal code",
    ]
    assert root.findtext(".//abstract[@abstract-type='excerpt']/p") == (
        "Level the base. Read the dial at 0°. Keep A < B."
    )


def test_headings_inside_quotes_and_lists_stay_with_their_text() -> None:
    markdown = (
        "> # Quoted title\n> Quoted text.\n\n# Field notes\n\n"
        "1. ## Daily task\n\nFinal observation."
    )
    root = ET.fromstring(document_to_jats(markdown, Path("notes.md")))
    assert root.findtext(".//article-title") == "Field notes"
    assert [sec.text for sec in root.findall("./body//sec/title")] == ["Field notes"]
    assert [p.text for p in root.findall("./body//p")] == [
        "Quoted title",
        "Quoted text.",
        "Daily task",
        "Final observation.",
    ]


@pytest.mark.parametrize(
    ("filename", "observations"),
    [
        ("notes.md", "Field notes\n\n- Temperature: twelve degrees."),
        ("notes.txt", "Gauge: brass\nLocation: orchard"),
    ],
)
def test_thematic_breaks_preserve_observations(
    filename: str, observations: str
) -> None:
    root = ET.fromstring(
        document_to_jats(f"---\n{observations}\n---\n\nMore text.", Path(filename))
    )
    body = root.find("body")
    assert body is not None
    body_text = " ".join(body.itertext())
    assert "More text." in body_text
    for line in observations.splitlines():
        assert line.removeprefix("- ") in body_text


def test_import_archive_with_duplicate_basenames_and_short_paragraphs(
    tmp_path: Path,
) -> None:
    notes = tmp_path / "notes"
    (notes / "east").mkdir(parents=True)
    (notes / "west").mkdir()
    (notes / "east/setup.md").write_text(
        "---\ntitle: East setup\nsummary: >-\n  Prepare the\n  eastern gauge.\n---\n"
        "# Checklist\n\nLevel the base.\n",
        encoding="utf-8",
    )
    (notes / "west/setup.md").write_text(
        "# West setup\n\nZero the dial.", encoding="utf-8"
    )
    (notes / "readings.TXT").write_bytes(
        "\ufeff2 mm & rising.\r\n\r\nDone.\r\n".encode()
    )
    (notes / "ignored.xml").write_text("<article/>")
    output = tmp_path / "tars" / "field-notes.tar.gz"

    result = CliRunner().invoke(
        cli, ["corpus", "import", str(notes), "--out", str(output)]
    )
    assert result.exit_code == 0, result.output
    with tarfile.open(output) as archive:
        assert set(archive.getnames()) == {
            "east/setup.md.xml",
            "west/setup.md.xml",
            "readings.TXT.xml",
        }
        records = {}
        for item in archive:
            stream = archive.extractfile(item)
            assert stream is not None
            xml = stream.read()
            assert (
                JATSValidator().validate(xml.decode()).status == ValidationStatus.VALID
            )
            records[item.name] = ET.fromstring(xml)

    east = records["east/setup.md.xml"]
    assert (
        east.findtext(".//article-id[@pub-id-type='publisher-id']") == "east/setup.md"
    )
    assert east.findtext(".//article-title") == "East setup"
    assert east.findtext(".//abstract/p") == "Prepare the eastern gauge."
    assert east.findtext("./body/sec/title") == "Checklist"
    assert east.findtext("./body/sec/p") == "Level the base."
    txt = records["readings.TXT.xml"]
    assert txt.findtext(".//article-title") == "readings"
    assert [p.text for p in txt.findall("./body/p")] == ["2 mm & rising.", "Done."]


def test_single_txt_to_xml_preserves_body_beyond_stage_one_excerpt(
    tmp_path: Path,
) -> None:
    note = tmp_path / "procedure.txt"
    paragraph = "word " * 100 + "last word."
    note.write_text(paragraph + "\n\n# Literal text.", encoding="utf-8")
    output = tmp_path / "procedure.xml"
    result = CliRunner().invoke(
        cli, ["corpus", "import", str(note), "--out", str(output)]
    )
    assert result.exit_code == 0, result.output
    root = ET.parse(output)
    assert root.findtext(".//abstract/p") == " ".join(["word"] * 100)
    assert [p.text for p in root.findall("./body/p")] == [paragraph, "# Literal text."]


@pytest.mark.parametrize("bad", [b"# Only a heading\n", b"\xff", b"bad\x00text"])
def test_failed_import_identifies_bad_file_and_keeps_previous_archive(
    tmp_path: Path, bad: bytes
) -> None:
    (tmp_path / "a.txt").write_text("A valid note.")
    output = tmp_path / "corpus.tar.gz"
    args = ["corpus", "import", str(tmp_path), "--out", str(output)]
    runner = CliRunner()
    assert runner.invoke(cli, args).exit_code == 0
    original = output.read_bytes()
    (tmp_path / "b.md").write_bytes(bad)
    result = runner.invoke(cli, args)
    assert result.exit_code != 0
    assert "b.md" in result.output
    assert output.read_bytes() == original


def test_unreadable_directory_keeps_previous_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "visible.txt").write_text("Visible note.")
    private = tmp_path / "field"
    private.mkdir()
    (private / "note.md").write_text("Field observation.")
    output = tmp_path / "corpus.tgz"
    args = ["corpus", "import", str(tmp_path), "--out", str(output)]
    runner = CliRunner()
    assert runner.invoke(cli, args).exit_code == 0
    original = output.read_bytes()

    # Simulate a real enumeration failure even on Windows or when running as root.
    scandir = os.scandir

    def deny_field_directory(path):
        if path == private or path == str(private):
            raise PermissionError(errno.EACCES, "Permission denied", str(private))
        return scandir(path)

    monkeypatch.setattr(os, "scandir", deny_field_directory)
    result = runner.invoke(cli, args)
    assert result.exit_code != 0
    assert repr(str(private)) in result.output
    assert output.read_bytes() == original


def test_archive_preserves_subsecond_edits_for_litkit_updates(tmp_path: Path) -> None:
    note = tmp_path / "field.txt"
    output = tmp_path / "corpus.tar.gz"
    args = ["corpus", "import", str(note), "--out", str(output)]
    runner = CliRunner()
    sizes = []
    for content, timestamp in [
        ("Reading 1.", 1700000000.25),
        ("Reading 2.", 1700000000.75),
    ]:
        note.write_text(content)
        os.utime(note, (timestamp, timestamp))
        assert runner.invoke(cli, args).exit_code == 0
        with tarfile.open(output) as archive:
            member = archive.getmember("field.txt.xml")
            assert member.mtime == timestamp
            sizes.append(member.size)
    assert sizes[0] == sizes[1]
