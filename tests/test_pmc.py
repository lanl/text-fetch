"""Unit tests for PMC JATS validation and article saving."""

from __future__ import annotations

import json
from pathlib import Path

from text_fetch.pmc import (
    BODY_MIN_CHARS,
    JATSValidator,
    ManifestEntry,
    ValidationResult,
    ValidationStatus,
    compute_sha256,
    read_manifest,
    save_pmc_article,
    write_manifest,
)


class TestValidationStatus:
    """Tests for ValidationStatus enum."""

    def test_status_values(self):
        """Status enum has expected values."""
        assert ValidationStatus.VALID.value == "valid"
        assert ValidationStatus.INCOMPLETE.value == "incomplete"
        assert ValidationStatus.INVALID.value == "invalid"


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_to_dict(self):
        """to_dict converts to JSON-serializable dict."""
        result = ValidationResult(
            status=ValidationStatus.VALID,
            has_title=True,
            has_abstract=True,
            has_body=True,
            body_chars=1500,
            errors=[],
            pmcid="PMC12345",
        )
        d = result.to_dict()
        assert d["status"] == "valid"
        assert d["has_title"] is True
        assert d["pmcid"] == "PMC12345"
        assert d["body_chars"] == 1500

    def test_to_dict_with_errors(self):
        """to_dict includes error list."""
        result = ValidationResult(
            status=ValidationStatus.INCOMPLETE,
            has_title=False,
            has_abstract=True,
            has_body=True,
            errors=["Missing or empty <article-title>"],
        )
        d = result.to_dict()
        assert d["status"] == "incomplete"
        assert "Missing or empty <article-title>" in d["errors"]


class TestJATSValidator:
    """Tests for JATSValidator class."""

    # Sample complete JATS document (body must be >1000 chars)
    COMPLETE_JATS = """<?xml version="1.0"?>
<article article-type="research-article">
<front>
<article-meta>
<article-id pub-id-type="pmcid">PMC12345</article-id>
<title-group>
<article-title>A Complete Research Article Title</article-title>
</title-group>
<abstract>
<p>This is the abstract of the article. It contains a summary of the
research findings and methodology used in this study.</p>
</abstract>
</article-meta>
</front>
<body>
<sec>
<title>Introduction</title>
<p>This is the introduction section with substantial content.
We present our research on an important topic that has significant
implications for the field. The methodology we employed was carefully
designed to ensure reproducibility and scientific rigor. Our work builds
upon decades of prior research in this domain and aims to address key
gaps in current understanding of the underlying mechanisms.</p>
</sec>
<sec>
<title>Methods</title>
<p>Our methods section describes the experimental procedures in detail.
We collected data from multiple sources and analyzed it using statistical
techniques. The sample size was determined based on power analysis to
ensure adequate statistical power for detecting meaningful effect sizes.
All experiments were conducted in triplicate and results were validated
using independent replication studies performed at collaborating institutions.</p>
</sec>
<sec>
<title>Results</title>
<p>The results section presents our findings. We observed significant
differences between treatment and control groups. Statistical analysis
confirmed the validity of our hypotheses with p-values below 0.05. The
effect sizes observed were consistent with theoretical predictions and
comparable to those reported in related studies in the literature.</p>
</sec>
<sec>
<title>Discussion</title>
<p>In the discussion, we interpret our results in the context of existing
literature. Our findings support previous research while also providing
new insights into the mechanisms underlying the observed phenomena. We
discuss the implications of our work for future research directions and
potential applications in clinical and industrial settings.</p>
</sec>
</body>
</article>"""

    # Article missing abstract
    NO_ABSTRACT_JATS = """<?xml version="1.0"?>
<article>
<front>
<article-meta>
<title-group>
<article-title>Article Without Abstract</article-title>
</title-group>
</article-meta>
</front>
<body>
<p>This is body content repeated many times to meet the minimum length
requirement. This is body content repeated many times to meet the minimum
length requirement. This is body content repeated many times to meet the
minimum length requirement. This is body content repeated many times.</p>
<p>More content here to ensure we have enough characters in the body
for the validation to pass the body check at least.</p>
</body>
</article>"""

    # Article missing body
    NO_BODY_JATS = """<?xml version="1.0"?>
<article>
<front>
<article-meta>
<title-group>
<article-title>Article Without Body Content</article-title>
</title-group>
<abstract>
<p>This article has an abstract but no body content.</p>
</abstract>
</article-meta>
</front>
</article>"""

    # Article with empty title
    EMPTY_TITLE_JATS = """<?xml version="1.0"?>
<article>
<front>
<article-meta>
<title-group>
<article-title></article-title>
</title-group>
<abstract><p>Abstract content here.</p></abstract>
</article-meta>
</front>
<body><p>Body content here repeated many times to meet length requirement.
Body content here repeated many times. Body content here repeated.</p>
<p>More body content to ensure we meet the minimum character threshold
for the body validation check to pass successfully.</p></body>
</article>"""

    # Article with short body
    SHORT_BODY_JATS = """<?xml version="1.0"?>
<article>
<front>
<article-meta>
<title-group>
<article-title>Article With Short Body</article-title>
</title-group>
<abstract><p>This is the abstract.</p></abstract>
</article-meta>
</front>
<body><p>Short body.</p></body>
</article>"""

    # Invalid XML
    INVALID_XML = """<?xml version="1.0"?>
<article>
<front>
<title>Unclosed tag
</article>"""

    def test_validate_complete_article(self):
        """Complete article is marked valid."""
        validator = JATSValidator()
        result = validator.validate(self.COMPLETE_JATS)

        assert result.status == ValidationStatus.VALID
        assert result.has_title is True
        assert result.has_abstract is True
        assert result.has_body is True
        assert result.body_chars >= BODY_MIN_CHARS
        assert result.errors == []
        assert result.pmcid == "PMC12345"

    def test_validate_missing_abstract(self):
        """Article without abstract is incomplete."""
        validator = JATSValidator(body_min_chars=100)
        result = validator.validate(self.NO_ABSTRACT_JATS)

        assert result.status == ValidationStatus.INCOMPLETE
        assert result.has_title is True
        assert result.has_abstract is False
        assert "Missing or empty <abstract>" in result.errors

    def test_validate_missing_body(self):
        """Article without body is incomplete."""
        validator = JATSValidator()
        result = validator.validate(self.NO_BODY_JATS)

        assert result.status == ValidationStatus.INCOMPLETE
        assert result.has_title is True
        assert result.has_abstract is True
        assert result.has_body is False
        assert any("body" in e.lower() for e in result.errors)

    def test_validate_empty_title(self):
        """Article with empty title tag is incomplete."""
        validator = JATSValidator(body_min_chars=100)
        result = validator.validate(self.EMPTY_TITLE_JATS)

        assert result.status == ValidationStatus.INCOMPLETE
        assert result.has_title is False
        assert "Missing or empty <article-title>" in result.errors

    def test_validate_short_body(self):
        """Article with body below threshold is incomplete."""
        validator = JATSValidator(body_min_chars=1000)
        result = validator.validate(self.SHORT_BODY_JATS)

        assert result.status == ValidationStatus.INCOMPLETE
        assert result.has_body is False
        assert any("too short" in e.lower() for e in result.errors)

    def test_validate_invalid_xml(self):
        """Invalid XML is marked invalid."""
        validator = JATSValidator()
        result = validator.validate(self.INVALID_XML)

        assert result.status == ValidationStatus.INVALID
        assert result.has_title is False
        assert result.has_abstract is False
        assert result.has_body is False
        assert any("parse error" in e.lower() for e in result.errors)

    def test_custom_body_threshold(self):
        """Custom body_min_chars is respected."""
        # With low threshold, short body passes
        validator_low = JATSValidator(body_min_chars=5)
        result_low = validator_low.validate(self.SHORT_BODY_JATS)
        assert result_low.has_body is True

        # With high threshold, short body fails
        validator_high = JATSValidator(body_min_chars=1000)
        result_high = validator_high.validate(self.SHORT_BODY_JATS)
        assert result_high.has_body is False

    def test_nested_text_extraction(self):
        """Text in nested elements is extracted correctly."""
        nested_xml = """<?xml version="1.0"?>
<article>
<front>
<article-meta>
<title-group>
<article-title>Title with <italic>nested</italic> elements</article-title>
</title-group>
<abstract><p>Abstract with <bold>bold</bold> text.</p></abstract>
</article-meta>
</front>
<body><sec><p>Body paragraph.</p></sec></body>
</article>"""
        validator = JATSValidator(body_min_chars=5)
        result = validator.validate(nested_xml)

        assert result.has_title is True
        assert result.has_abstract is True

    def test_validate_file(self, tmp_path: Path):
        """validate_file reads and validates from file."""
        xml_file = tmp_path / "test.xml"
        xml_file.write_text(self.COMPLETE_JATS, encoding="utf-8")

        validator = JATSValidator()
        result = validator.validate_file(xml_file)

        assert result.status == ValidationStatus.VALID
        assert result.pmcid == "PMC12345"

    def test_validate_file_not_found(self, tmp_path: Path):
        """validate_file handles missing file."""
        validator = JATSValidator()
        result = validator.validate_file(tmp_path / "nonexistent.xml")

        assert result.status == ValidationStatus.INVALID
        assert any("file read error" in e.lower() for e in result.errors)


class TestComputeSha256:
    """Tests for compute_sha256 function."""

    def test_string_input(self):
        """SHA256 of string is computed correctly."""
        h = compute_sha256("test content")
        assert len(h) == 64
        assert h == compute_sha256("test content")  # Deterministic

    def test_bytes_input(self):
        """SHA256 of bytes is computed correctly."""
        h = compute_sha256(b"test content")
        assert len(h) == 64

    def test_string_and_bytes_same(self):
        """String and encoded bytes produce same hash."""
        text = "test content"
        assert compute_sha256(text) == compute_sha256(text.encode("utf-8"))

    def test_different_content_different_hash(self):
        """Different content produces different hash."""
        h1 = compute_sha256("content 1")
        h2 = compute_sha256("content 2")
        assert h1 != h2


class TestManifestEntry:
    """Tests for ManifestEntry dataclass."""

    def test_to_dict(self):
        """to_dict converts to dictionary."""
        entry = ManifestEntry(
            pmcid="PMC12345",
            filename="valid/PMC12345.xml",
            status="valid",
            has_title=True,
            has_abstract=True,
            has_body=True,
            body_chars=1500,
            saved_at="2025-01-21T12:00:00Z",
            sha256="abc123",
        )
        d = entry.to_dict()
        assert d["pmcid"] == "PMC12345"
        assert d["status"] == "valid"
        assert d["sha256"] == "abc123"

    def test_from_dict(self):
        """from_dict creates entry from dictionary."""
        data = {
            "pmcid": "PMC12345",
            "filename": "valid/PMC12345.xml",
            "status": "valid",
            "has_title": True,
            "has_abstract": True,
            "has_body": True,
            "body_chars": 1500,
            "saved_at": "2025-01-21T12:00:00Z",
            "sha256": "abc123",
        }
        entry = ManifestEntry.from_dict(data)
        assert entry.pmcid == "PMC12345"
        assert entry.status == "valid"

    def test_round_trip(self):
        """to_dict and from_dict are inverse operations."""
        original = ManifestEntry(
            pmcid="PMC12345",
            filename="valid/PMC12345.xml",
            status="valid",
            has_title=True,
            has_abstract=True,
            has_body=True,
            body_chars=1500,
            saved_at="2025-01-21T12:00:00Z",
            sha256="abc123",
        )
        reconstructed = ManifestEntry.from_dict(original.to_dict())
        assert original == reconstructed


class TestManifestIO:
    """Tests for read_manifest and write_manifest functions."""

    def test_write_manifest_creates_file(self, tmp_path: Path):
        """write_manifest creates manifest.json."""
        entries = {
            "PMC12345": ManifestEntry(
                pmcid="PMC12345",
                filename="valid/PMC12345.xml",
                status="valid",
                has_title=True,
                has_abstract=True,
                has_body=True,
                body_chars=1500,
                saved_at="2025-01-21T12:00:00Z",
                sha256="abc123",
            )
        }
        result_path = write_manifest(tmp_path, entries)

        assert result_path.exists()
        assert result_path.name == "manifest.json"

    def test_write_manifest_content(self, tmp_path: Path):
        """write_manifest writes correct content."""
        entries = {
            "PMC12345": ManifestEntry(
                pmcid="PMC12345",
                filename="valid/PMC12345.xml",
                status="valid",
                has_title=True,
                has_abstract=True,
                has_body=True,
                body_chars=1500,
                saved_at="2025-01-21T12:00:00Z",
                sha256="abc123",
            ),
            "PMC67890": ManifestEntry(
                pmcid="PMC67890",
                filename="incomplete/PMC67890.xml",
                status="incomplete",
                has_title=True,
                has_abstract=False,
                has_body=True,
                body_chars=2000,
                saved_at="2025-01-21T12:00:00Z",
                sha256="def456",
            ),
        }
        write_manifest(tmp_path, entries)

        data = json.loads((tmp_path / "manifest.json").read_text())
        assert data["version"] == "1.0"
        assert data["statistics"]["total"] == 2
        assert data["statistics"]["valid"] == 1
        assert data["statistics"]["incomplete"] == 1
        assert len(data["articles"]) == 2

    def test_read_manifest_empty_dir(self, tmp_path: Path):
        """read_manifest returns empty dict for empty directory."""
        result = read_manifest(tmp_path)
        assert result == {}

    def test_read_manifest_existing(self, tmp_path: Path):
        """read_manifest reads existing manifest."""
        manifest_data = {
            "version": "1.0",
            "articles": [
                {
                    "pmcid": "PMC12345",
                    "filename": "valid/PMC12345.xml",
                    "status": "valid",
                    "has_title": True,
                    "has_abstract": True,
                    "has_body": True,
                    "body_chars": 1500,
                    "saved_at": "2025-01-21T12:00:00Z",
                    "sha256": "abc123",
                }
            ],
        }
        (tmp_path / "manifest.json").write_text(json.dumps(manifest_data))

        result = read_manifest(tmp_path)
        assert "PMC12345" in result
        assert result["PMC12345"].sha256 == "abc123"

    def test_read_write_round_trip(self, tmp_path: Path):
        """read_manifest can read what write_manifest writes."""
        original_entries = {
            "PMC12345": ManifestEntry(
                pmcid="PMC12345",
                filename="valid/PMC12345.xml",
                status="valid",
                has_title=True,
                has_abstract=True,
                has_body=True,
                body_chars=1500,
                saved_at="2025-01-21T12:00:00Z",
                sha256="abc123",
            )
        }
        write_manifest(tmp_path, original_entries)
        read_entries = read_manifest(tmp_path)

        assert read_entries["PMC12345"].pmcid == "PMC12345"
        assert read_entries["PMC12345"].sha256 == "abc123"


class TestSavePmcArticle:
    """Tests for save_pmc_article function."""

    COMPLETE_XML = """<?xml version="1.0"?>
<article>
<front><article-meta>
<article-id pub-id-type="pmcid">PMC99999</article-id>
<title-group><article-title>Test Title</article-title></title-group>
<abstract><p>Test abstract content here.</p></abstract>
</article-meta></front>
<body>
<p>This is body content that needs to be long enough to pass validation.
We need at least 1000 characters of body content for the default threshold.
Adding more text to ensure we reach that minimum requirement here.
Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod
tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim
veniam quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea
commodo consequat. Duis aute irure dolor in reprehenderit in voluptate
velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint
occaecat cupidatat non proident sunt in culpa qui officia deserunt
mollit anim id est laborum. More content to reach the threshold.
Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium
doloremque laudantium totam rem aperiam eaque ipsa quae ab illo inventore
veritatis et quasi architecto beatae vitae dicta sunt explicabo. Nemo enim
ipsam voluptatem quia voluptas sit aspernatur aut odit aut fugit sed quia
consequuntur magni dolores eos qui ratione voluptatem sequi nesciunt.</p>
</body>
</article>"""

    INCOMPLETE_XML = """<?xml version="1.0"?>
<article>
<front><article-meta>
<title-group><article-title>Incomplete Article</article-title></title-group>
</article-meta></front>
<body><p>Short body.</p></body>
</article>"""

    def test_save_valid_to_valid_folder(self, tmp_path: Path):
        """Valid article is saved to valid/ subfolder."""
        path, result, entry = save_pmc_article(
            "PMC12345",
            self.COMPLETE_XML,
            tmp_path,
        )

        assert path is not None
        assert path.parent.name == "valid"
        assert path.name == "PMC12345.xml"
        assert path.exists()
        assert result.status == ValidationStatus.VALID
        assert entry.status == "valid"

    def test_save_incomplete_to_incomplete_folder(self, tmp_path: Path):
        """Incomplete article is saved to incomplete/ subfolder."""
        path, result, entry = save_pmc_article(
            "PMC12345",
            self.INCOMPLETE_XML,
            tmp_path,
        )

        assert path is not None
        assert path.parent.name == "incomplete"
        assert result.status == ValidationStatus.INCOMPLETE
        assert entry.status == "incomplete"

    def test_pmcid_normalization(self, tmp_path: Path):
        """PMCID is normalized to include PMC prefix."""
        # Without prefix
        path1, _, entry1 = save_pmc_article(
            "12345",
            self.COMPLETE_XML,
            tmp_path,
        )
        assert path1 is not None
        assert "PMC12345" in path1.name
        assert entry1.pmcid == "PMC12345"

    def test_duplicate_detection_skips(self, tmp_path: Path):
        """Duplicate with same hash is skipped."""
        # First save
        path1, _, entry1 = save_pmc_article(
            "PMC12345",
            self.COMPLETE_XML,
            tmp_path,
        )
        assert path1 is not None

        # Create manifest from first save
        manifest = {"PMC12345": entry1}

        # Second save with same content
        path2, result2, entry2 = save_pmc_article(
            "PMC12345",
            self.COMPLETE_XML,
            tmp_path,
            existing_manifest=manifest,
        )

        # Should be skipped (path is None)
        assert path2 is None
        assert entry2 == entry1  # Returns existing entry

    def test_duplicate_with_different_content_saves(self, tmp_path: Path):
        """Same PMCID with different content is saved."""
        # First save
        path1, _, entry1 = save_pmc_article(
            "PMC12345",
            self.COMPLETE_XML,
            tmp_path,
        )

        manifest = {"PMC12345": entry1}

        # Second save with different content
        modified_xml = self.COMPLETE_XML.replace("Test Title", "Modified Title")
        path2, _, entry2 = save_pmc_article(
            "PMC12345",
            modified_xml,
            tmp_path,
            existing_manifest=manifest,
        )

        # Should save (different hash)
        assert path2 is not None
        assert entry2.sha256 != entry1.sha256

    def test_manifest_entry_has_correct_fields(self, tmp_path: Path):
        """Manifest entry contains all required fields."""
        _, _, entry = save_pmc_article(
            "PMC12345",
            self.COMPLETE_XML,
            tmp_path,
        )

        assert entry.pmcid == "PMC12345"
        assert entry.filename.startswith("valid/")
        assert entry.status == "valid"
        assert entry.has_title is True
        assert entry.has_abstract is True
        assert entry.has_body is True
        assert entry.body_chars > 0
        assert entry.saved_at  # Non-empty timestamp
        assert len(entry.sha256) == 64  # SHA256 hex length

    def test_custom_validator(self, tmp_path: Path):
        """Custom validator is used when provided."""
        # Use very low threshold so INCOMPLETE_XML passes
        validator = JATSValidator(body_min_chars=5)

        path, result, entry = save_pmc_article(
            "PMC12345",
            self.INCOMPLETE_XML,
            tmp_path,
            validator=validator,
        )

        # With low threshold, only missing abstract makes it incomplete
        assert path is not None
        # Still incomplete due to missing abstract
        assert result.has_abstract is False
