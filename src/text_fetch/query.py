"""JSON config → PubMed query builder.

Provides SearchConfig dataclass for loading JSON search configurations
and converting them to PubMed query syntax.
"""

from __future__ import annotations

__all__ = [
    "SearchConfig",
    "SearchConfigError",
]

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SearchConfigError(Exception):
    """Error in search configuration."""

    pass


@dataclass
class DateRange:
    """Date range for PubMed searches."""

    start: str  # YYYY/MM/DD format
    end: str  # YYYY/MM/DD format

    def to_pubmed_filter(self) -> str:
        """Convert to PubMed date filter syntax.

        Returns:
            PubMed date filter like "2020/01/01:2024/12/31[dp]"
        """
        return f"{self.start}:{self.end}[dp]"

    def validate(self) -> list[str]:
        """Validate date range format.

        Returns:
            List of validation errors (empty if valid).
        """
        errors = []
        import re

        date_pattern = r"^\d{4}/\d{2}/\d{2}$"
        if not re.match(date_pattern, self.start):
            errors.append(
                f"Invalid start date format: {self.start} (expected YYYY/MM/DD)"
            )
        if not re.match(date_pattern, self.end):
            errors.append(f"Invalid end date format: {self.end} (expected YYYY/MM/DD)")
        return errors


@dataclass
class SearchConfig:
    """Search configuration for PubMed queries.

    Supports multiple configuration formats:
    1. Simple author/keyword search:
       {"author": "hlavacek ws", "keywords": ["systems biology"]}

    2. Complex multi-category search (ebola.json format):
       {"virus_keywords": [...], "disease_keywords": [...], "vaccine_keywords": [...]}

    Example:
        >>> config = SearchConfig.from_json("input/search.json")
        >>> query = config.to_pubmed_query()
        >>> print(query)
        'hlavacek ws[au] AND (systems biology[tiab] OR modeling[tiab])'
    """

    # Basic fields
    author: str | None = None
    keywords: list[str] = field(default_factory=list)

    # Extended keyword categories (ebola.json format)
    virus_keywords: list[str] = field(default_factory=list)
    disease_keywords: list[str] = field(default_factory=list)
    vaccine_keywords: list[str] = field(default_factory=list)

    # Date filtering
    date_range: DateRange | None = None

    # Source file path (for error messages)
    source_path: str | None = None

    @classmethod
    def from_json(cls, path: str | Path) -> SearchConfig:
        """Load and validate config from JSON file.

        Args:
            path: Path to JSON configuration file.

        Returns:
            SearchConfig instance.

        Raises:
            SearchConfigError: If file cannot be read or parsed.
        """
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise SearchConfigError(f"Config file not found: {path}") from e
        except json.JSONDecodeError as e:
            raise SearchConfigError(f"Invalid JSON in {path}: {e}") from e

        return cls.from_dict(data, source_path=str(path))

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], source_path: str | None = None
    ) -> SearchConfig:
        """Create SearchConfig from dictionary.

        Args:
            data: Configuration dictionary.
            source_path: Optional source file path.

        Returns:
            SearchConfig instance.
        """
        # Parse date_range if present
        date_range = None
        if "date_range" in data:
            dr = data["date_range"]
            if isinstance(dr, dict) and "start" in dr and "end" in dr:
                date_range = DateRange(start=dr["start"], end=dr["end"])

        return cls(
            author=data.get("author"),
            keywords=data.get("keywords", []),
            virus_keywords=data.get("virus_keywords", []),
            disease_keywords=data.get("disease_keywords", []),
            vaccine_keywords=data.get("vaccine_keywords", []),
            date_range=date_range,
            source_path=source_path,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {}
        if self.author:
            result["author"] = self.author
        if self.keywords:
            result["keywords"] = self.keywords
        if self.virus_keywords:
            result["virus_keywords"] = self.virus_keywords
        if self.disease_keywords:
            result["disease_keywords"] = self.disease_keywords
        if self.vaccine_keywords:
            result["vaccine_keywords"] = self.vaccine_keywords
        if self.date_range:
            result["date_range"] = {
                "start": self.date_range.start,
                "end": self.date_range.end,
            }
        return result

    @property
    def all_keywords(self) -> list[str]:
        """Combine all keyword arrays.

        Returns:
            List of all keywords from all categories.
        """
        result = []
        for kw_list in [
            self.keywords,
            self.virus_keywords,
            self.disease_keywords,
            self.vaccine_keywords,
        ]:
            result.extend(kw_list)
        return result

    def validate(self) -> list[str]:
        """Validate configuration.

        Returns:
            List of validation errors (empty if valid).
        """
        errors = []

        # Must have at least one search criterion
        has_author = bool(self.author)
        has_keywords = bool(self.all_keywords)

        if not has_author and not has_keywords:
            errors.append(
                "Config must specify at least one of: author, keywords, "
                "virus_keywords, disease_keywords, vaccine_keywords"
            )

        # Validate date range if present
        if self.date_range:
            errors.extend(self.date_range.validate())

        return errors

    def to_pubmed_query(self) -> str:
        """Convert config to PubMed query syntax.

        Returns:
            PubMed query string.

        Raises:
            SearchConfigError: If config is invalid.

        Example:
            >>> config = SearchConfig(author="hlavacek ws")
            >>> config.to_pubmed_query()
            'hlavacek ws[au]'
        """
        errors = self.validate()
        if errors:
            raise SearchConfigError(f"Invalid config: {'; '.join(errors)}")

        parts = []

        # Author search
        if self.author:
            parts.append(f"{self.author}[au]")

        # Keyword searches (combine all keyword categories with OR)
        all_kw = self.all_keywords
        if all_kw:
            # Each keyword searches title/abstract
            kw_parts = [f'"{kw}"[tiab]' for kw in all_kw]
            if len(kw_parts) == 1:
                parts.append(kw_parts[0])
            else:
                parts.append(f"({' OR '.join(kw_parts)})")

        # Date range filter
        if self.date_range:
            parts.append(self.date_range.to_pubmed_filter())

        return " AND ".join(parts)

    def to_pubmed_query_by_category(self) -> str:
        """Convert config to PubMed query with category grouping.

        This variant groups keywords by category with AND between categories.
        Useful for multi-category searches like ebola.json.

        Returns:
            PubMed query string.

        Example:
            For ebola.json, produces:
            (virus_kw1 OR virus_kw2)[tiab] AND
            (disease_kw1 OR disease_kw2)[tiab] AND
            (vaccine_kw1 OR vaccine_kw2)[tiab] AND
            date_range[dp]
        """
        errors = self.validate()
        if errors:
            raise SearchConfigError(f"Invalid config: {'; '.join(errors)}")

        parts = []

        # Author search
        if self.author:
            parts.append(f"{self.author}[au]")

        # Group keywords by category
        categories = [
            self.keywords,
            self.virus_keywords,
            self.disease_keywords,
            self.vaccine_keywords,
        ]

        for cat_keywords in categories:
            if cat_keywords:
                kw_parts = [f'"{kw}"[tiab]' for kw in cat_keywords]
                if len(kw_parts) == 1:
                    parts.append(kw_parts[0])
                else:
                    parts.append(f"({' OR '.join(kw_parts)})")

        # Date range filter
        if self.date_range:
            parts.append(self.date_range.to_pubmed_filter())

        return " AND ".join(parts)

    def __str__(self) -> str:
        """Return human-readable description."""
        desc_parts = []
        if self.author:
            desc_parts.append(f"author='{self.author}'")
        kw_count = len(self.all_keywords)
        if kw_count:
            desc_parts.append(f"keywords={kw_count}")
        if self.date_range:
            desc_parts.append(f"dates={self.date_range.start} to {self.date_range.end}")
        return f"SearchConfig({', '.join(desc_parts)})"
