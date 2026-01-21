"""Pytest fixtures for text-fetch tests."""

import pytest


@pytest.fixture
def sample_tei_xml() -> str:
    """Minimal TEI XML with bibliographic metadata."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title>Sample Paper Title</title>
      </titleStmt>
      <sourceDesc>
        <biblStruct>
          <analytic>
            <title type="main">Sample Paper Title</title>
            <author>
              <persName>
                <forename>John</forename>
                <surname>Smith</surname>
              </persName>
            </author>
            <idno type="DOI">10.1234/example.2024</idno>
          </analytic>
          <monogr>
            <title level="j">Journal of Examples</title>
            <imprint>
              <date when="2024-01-15"/>
            </imprint>
          </monogr>
        </biblStruct>
      </sourceDesc>
    </fileDesc>
  </teiHeader>
  <text>
    <body>
      <p>This is the body text.</p>
    </body>
  </text>
</TEI>"""


@pytest.fixture
def sample_tei_with_pmid() -> str:
    """TEI XML with PMID and PMCID."""
    return """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <sourceDesc>
        <biblStruct>
          <analytic>
            <title type="main">PubMed Paper</title>
            <author>
              <persName>
                <surname>Hlavacek</surname>
              </persName>
            </author>
            <idno type="DOI">10.1016/j.cell.2024.01.001</idno>
            <idno type="PMID">12345678</idno>
            <idno type="PMCID">PMC9876543</idno>
          </analytic>
          <monogr>
            <title level="j">Cell</title>
            <imprint>
              <date when="2024"/>
            </imprint>
          </monogr>
        </biblStruct>
      </sourceDesc>
    </fileDesc>
  </teiHeader>
</TEI>"""


@pytest.fixture
def minimal_tei_xml() -> str:
    """Minimal valid TEI with no metadata."""
    return '<?xml version="1.0"?><TEI xmlns="http://www.tei-c.org/ns/1.0"/>'


@pytest.fixture
def sample_pdf_path(tmp_path):
    """Create a minimal PDF file for testing.

    Note: This creates a valid PDF structure but contains no real content.
    For actual PDF processing tests, use real PDFs from Manuscripts/.
    """
    pdf_content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
trailer
<< /Size 4 /Root 1 0 R >>
startxref
196
%%EOF
"""
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(pdf_content)
    return pdf_path
