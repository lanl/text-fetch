"""Tests for shared helpers in text_fetch.common."""

from __future__ import annotations

import pytest

from text_fetch.common import normalize_pmcid


class TestNormalizePmcid:
    """normalize_pmcid accepts any case of the PMC prefix and nothing else."""

    @pytest.mark.parametrize(
        "raw",
        ["PMC12345", "pmc12345", "Pmc12345", "pMc12345", "12345", " PMC12345\n"],
    )
    def test_accepts_prefix_in_any_case(self, raw: str) -> None:
        """Every spelling of the same PMCID normalizes to PMC12345."""
        assert normalize_pmcid(raw) == "PMC12345"

    def test_accepts_integer(self) -> None:
        """A bare integer (as some APIs return IDs) gets the prefix."""
        assert normalize_pmcid(12345) == "PMC12345"

    @pytest.mark.parametrize(
        "raw",
        ["PMCPMC1", "PMC", "", "  ", "PMC12a", "arxiv:2301.12345", "PMC 123", "١٢٣"],
    )
    def test_rejects_non_pmcids(self, raw: str) -> None:
        """Anything other than an optional PMC prefix plus ASCII digits raises."""
        with pytest.raises(ValueError, match="Invalid PMC ID"):
            normalize_pmcid(raw)
