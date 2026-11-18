"""Contributor credit matching for GitHub commits."""

from pathlib import Path
from runpy import run_path

import pytest

checker = run_path(str(Path(__file__).resolve().parents[1] / "ci" / "contributors.py"))
Commit = checker["Commit"]
listing = "- Ada Lovelace (@ada)\n- @quietdev"


@pytest.mark.parametrize(
    ("login", "kind", "name", "email", "expected"),
    [
        ("ADA", "User", "Other name", "", 0),
        ("QUIETDEV", "User", "", "", 0),
        ("stranger", "User", "Ada Lovelace", "", 1),
        ("", "", "Ada Lovelace", "", 0),
        ("", "", "quietdev", "", 0),
        ("", "", "Unknown Author", "other@example.org", 1),
        ("an-app", "Bot", "", "", 0),
        ("some-app[bot]", "", "", "", 0),
    ],
)
def test_check_author_credit(
    login: str, kind: str, name: str, email: str, expected: int
) -> None:
    commit = Commit("123abc", login, kind, name, email)
    assert checker["check"]([commit], listing, "test PR") == expected
