"""JSON config → multi-source query builder.

Provides SearchConfig dataclass for loading JSON search configurations
and converting them to queries for various sources (PubMed, Europe PMC,
arXiv, bioRxiv, ChemRxiv).
"""

from __future__ import annotations

__all__ = [
    "ALL_SOURCES",
    "SearchConfig",
    "SearchConfigError",
    "SourceName",
    "SourceOptions",
]

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

# Type alias for supported source names
SourceName = Literal["pmc", "europepmc", "arxiv", "biorxiv", "medrxiv", "chemrxiv"]

ALL_SOURCES: list[SourceName] = [
    "pmc",
    "europepmc",
    "arxiv",
    "biorxiv",
    "medrxiv",
    "chemrxiv",
]


class SearchConfigError(Exception):
    """Error in search configuration."""

    pass


@dataclass
class SourceOptions:
    """Source-specific options for multi-source queries."""

    # arXiv/biorxiv/medrxiv/chemrxiv categories
    categories: list[str] = field(default_factory=list)

    # Extra query terms for this source only
    extra_keywords: list[str] = field(default_factory=list)

    # Override max_results for this source
    max_results: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceOptions:
        """Create SourceOptions from dictionary."""
        return cls(
            categories=data.get("categories", []),
            extra_keywords=data.get("extra_keywords", []),
            max_results=data.get("max_results"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {}
        if self.categories:
            result["categories"] = self.categories
        if self.extra_keywords:
            result["extra_keywords"] = self.extra_keywords
        if self.max_results is not None:
            result["max_results"] = self.max_results
        return result


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
                f"Invalid start date format: {self.start} " "(expected YYYY/MM/DD)"
            )
        if not re.match(date_pattern, self.end):
            errors.append(f"Invalid end date format: {self.end} (expected YYYY/MM/DD)")
        return errors


@dataclass
class SearchConfig:
    """Search configuration for multi-source queries.

    Supports multiple configuration formats:
    1. Simple author/keyword search:
       {"author": "hlavacek ws", "keywords": ["systems biology"]}

    2. Complex multi-category search (ebola.json format):
       {"virus_keywords": [...], "disease_keywords": [...], ...}

    3. Multi-source unified search:
       {"author": "hlavacek ws", "sources": ["pmc", "europepmc"]}

    Example:
        >>> config = SearchConfig.from_json("input/search.json")
        >>> query = config.to_pubmed_query()
        >>> print(query)
        'hlavacek ws[au] AND (systems biology[tiab] OR modeling[tiab])'
    """

    # Metadata
    name: str | None = None
    description: str | None = None

    # Basic fields
    author: str | None = None
    keywords: list[str] = field(default_factory=list)

    # Extended keyword categories (ebola.json format)
    virus_keywords: list[str] = field(default_factory=list)
    disease_keywords: list[str] = field(default_factory=list)
    vaccine_keywords: list[str] = field(default_factory=list)

    # Date filtering
    date_range: DateRange | None = None

    # arXiv-specific fields
    arxiv_categories: list[str] = field(default_factory=list)

    # Multi-source support
    sources: list[str] = field(default_factory=list)
    source_options: dict[str, SourceOptions] = field(default_factory=dict)
    max_results_per_source: int = 100
    open_access_only: bool = True
    deduplicate_by_doi: bool = True

    # Expansion configuration (europepmc only)
    expand_references: bool = False
    expand_citations: bool = False
    expansion_depth: int = 1
    max_expansion: int | None = None

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

        # Parse source_options
        source_options: dict[str, SourceOptions] = {}
        if "source_options" in data:
            for source, opts in data["source_options"].items():
                source_options[source] = SourceOptions.from_dict(opts)

        return cls(
            name=data.get("name"),
            description=data.get("description"),
            author=data.get("author"),
            keywords=data.get("keywords", []),
            virus_keywords=data.get("virus_keywords", []),
            disease_keywords=data.get("disease_keywords", []),
            vaccine_keywords=data.get("vaccine_keywords", []),
            date_range=date_range,
            arxiv_categories=data.get("arxiv_categories", []),
            sources=data.get("sources", []),
            source_options=source_options,
            max_results_per_source=data.get("max_results_per_source", 100),
            open_access_only=data.get("open_access_only", True),
            deduplicate_by_doi=data.get("deduplicate_by_doi", True),
            expand_references=data.get("expand_references", False),
            expand_citations=data.get("expand_citations", False),
            expansion_depth=data.get("expansion_depth", 1),
            max_expansion=data.get("max_expansion"),
            source_path=source_path,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result: dict[str, Any] = {}
        if self.name:
            result["name"] = self.name
        if self.description:
            result["description"] = self.description
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
        if self.arxiv_categories:
            result["arxiv_categories"] = self.arxiv_categories
        if self.sources:
            result["sources"] = self.sources
        if self.source_options:
            result["source_options"] = {
                k: v.to_dict() for k, v in self.source_options.items()
            }
        # Only include if non-default values
        if self.max_results_per_source != 100:
            result["max_results_per_source"] = self.max_results_per_source
        if not self.open_access_only:
            result["open_access_only"] = self.open_access_only
        if not self.deduplicate_by_doi:
            result["deduplicate_by_doi"] = self.deduplicate_by_doi
        # Expansion configuration (only include if non-default)
        if self.expand_references:
            result["expand_references"] = self.expand_references
        if self.expand_citations:
            result["expand_citations"] = self.expand_citations
        if self.expansion_depth != 1:
            result["expansion_depth"] = self.expansion_depth
        if self.max_expansion is not None:
            result["max_expansion"] = self.max_expansion
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

    def to_arxiv_query(self) -> str:
        """Convert config to arXiv query syntax.

        Returns:
            arXiv query string.

        Raises:
            SearchConfigError: If config has no searchable criteria.

        Example:
            >>> config = SearchConfig(author="hlavacek ws")
            >>> config.to_arxiv_query()
            'au:"hlavacek ws"'
        """
        from .arxiv import build_query

        # Check we have something to search
        has_author = bool(self.author)
        has_keywords = bool(self.all_keywords)
        has_categories = bool(self.arxiv_categories)

        if not has_author and not has_keywords and not has_categories:
            raise SearchConfigError(
                "Config must specify at least one of: author, keywords, "
                "or arxiv_categories for arXiv search"
            )

        return build_query(
            author=self.author,
            all_keywords=self.all_keywords if self.all_keywords else None,
            categories=self.arxiv_categories if self.arxiv_categories else None,
        )

    def to_europepmc_query(self) -> str:
        """Convert config to Europe PMC Lucene query syntax.

        For multi-category searches (virus_keywords, disease_keywords, etc.),
        groups keywords by category with AND between categories:
        (virus_kw1 OR virus_kw2) AND (disease_kw1 OR ...) AND ...

        Returns:
            Europe PMC query string.

        Example:
            >>> config = SearchConfig(
            ...     author="hlavacek ws", keywords=["modeling"]
            ... )
            >>> config.to_europepmc_query()
            'AUTH:"hlavacek ws" AND "modeling" AND OPEN_ACCESS:Y AND HAS_FT:Y'
        """
        parts = []

        # Author
        if self.author:
            parts.append(f'AUTH:"{self.author}"')

        # Handle keyword categories - group by category with AND between groups
        # Each category uses OR within the group
        categories = [
            self.keywords,
            self.virus_keywords,
            self.disease_keywords,
            self.vaccine_keywords,
        ]

        for cat_keywords in categories:
            if cat_keywords:
                # Quote each keyword and combine with OR
                kw_parts = [f'"{kw}"' for kw in cat_keywords]
                if len(kw_parts) == 1:
                    parts.append(kw_parts[0])
                else:
                    parts.append(f"({' OR '.join(kw_parts)})")

        # Date range
        if self.date_range:
            start = self._date_iso("start")
            end = self._date_iso("end")
            if start or end:
                start = start or "*"
                end = end or "*"
                parts.append(f"FIRST_PDATE:[{start} TO {end}]")

        # Open access filter
        if self.open_access_only:
            parts.append("OPEN_ACCESS:Y")

        # Full text required
        parts.append("HAS_FT:Y")

        return " AND ".join(parts) if parts else "*"

    def to_biorxiv_params(self, server: str = "biorxiv") -> dict[str, Any]:
        """Convert config to bioRxiv/medRxiv fetch parameters.

        Args:
            server: Either "biorxiv" or "medrxiv".

        Returns:
            Dictionary of parameters for fetch_biorxiv/fetch_medrxiv.
        """
        params: dict[str, Any] = {
            "max_results": self.max_results_per_source,
        }

        # Get source-specific options
        opts = self.source_options.get(server, SourceOptions())
        if opts.categories:
            # bioRxiv uses single category
            params["category"] = opts.categories[0]
        if opts.max_results is not None:
            params["max_results"] = opts.max_results

        # Convert date range
        if self.date_range:
            params["start_date"] = self._date_iso("start")
            params["end_date"] = self._date_iso("end")

        return params

    def to_chemrxiv_params(self) -> dict[str, Any]:
        """Convert config to ChemRxiv fetch parameters.

        Returns:
            Dictionary of parameters for fetch_chemrxiv.
        """
        params: dict[str, Any] = {
            "max_results": self.max_results_per_source,
        }

        # Keywords become search term
        if self.all_keywords:
            params["term"] = " ".join(self.all_keywords)

        # Get source-specific options
        opts = self.source_options.get("chemrxiv", SourceOptions())
        if opts.categories:
            from .chemrxiv import get_category_ids

            params["category_ids"] = get_category_ids(opts.categories)
        if opts.max_results is not None:
            params["max_results"] = opts.max_results

        # Convert date range
        if self.date_range:
            params["date_from"] = self._date_iso("start")
            params["date_to"] = self._date_iso("end")

        return params

    def _date_iso(self, which: str) -> str | None:
        """Get date in ISO format (YYYY-MM-DD).

        Args:
            which: Either "start" or "end".

        Returns:
            Date string in YYYY-MM-DD format, or None if no date_range.
        """
        if not self.date_range:
            return None
        date_str = self.date_range.start if which == "start" else self.date_range.end
        # Convert YYYY/MM/DD to YYYY-MM-DD if needed
        return date_str.replace("/", "-")

    def __str__(self) -> str:
        """Return human-readable description."""
        desc_parts = []
        if self.name:
            desc_parts.append(f"name='{self.name}'")
        if self.author:
            desc_parts.append(f"author='{self.author}'")
        kw_count = len(self.all_keywords)
        if kw_count:
            desc_parts.append(f"keywords={kw_count}")
        if self.date_range:
            start = self.date_range.start
            end = self.date_range.end
            desc_parts.append(f"dates={start} to {end}")
        if self.arxiv_categories:
            desc_parts.append(f"arxiv_cats={len(self.arxiv_categories)}")
        if self.sources:
            desc_parts.append(f"sources={self.sources}")
        return f"SearchConfig({', '.join(desc_parts)})"
