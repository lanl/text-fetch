"""Configuration management for text-fetch.

Supports configuration from multiple sources with priority:
1. CLI flags (highest)
2. Environment variables
3. TOML config file (lowest)

Config file locations (searched in order):
1. ./text-fetch.toml (project directory)
2. ~/.config/text-fetch/config.toml (XDG standard)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Use tomllib for Python 3.11+, otherwise tomli
try:
    import tomllib
except ImportError:
    import tomli as tomllib

logger = logging.getLogger(__name__)


@dataclass
class NCBIConfig:
    """NCBI API configuration."""

    email: str | None = None
    api_key: str | None = None


@dataclass
class GrobidConfig:
    """GROBID service configuration."""

    url: str = "http://localhost:8070"


@dataclass
class Config:
    """Application configuration container."""

    ncbi: NCBIConfig = field(default_factory=NCBIConfig)
    grobid: GrobidConfig = field(default_factory=GrobidConfig)
    _config_path: str | None = field(default=None, repr=False)

    @property
    def config_path(self) -> str | None:
        """Return the path to the loaded config file, if any."""
        return self._config_path


# Environment variable mappings
ENV_MAPPINGS = {
    "ncbi.email": "NCBI_EMAIL",
    "ncbi.api_key": "NCBI_API_KEY",
    "grobid.url": "GROBID_URL",
}


def _find_config_file() -> Path | None:
    """Find the first available config file.

    Searches in order:
    1. ./text-fetch.toml (current directory)
    2. ~/.config/text-fetch/config.toml (XDG standard)

    Returns:
        Path to config file if found, None otherwise.
    """
    search_paths = [
        Path.cwd() / "text-fetch.toml",
        Path.home() / ".config" / "text-fetch" / "config.toml",
    ]

    for path in search_paths:
        if path.is_file():
            logger.debug("Found config file: %s", path)
            return path

    logger.debug("No config file found in: %s", [str(p) for p in search_paths])
    return None


def _parse_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file.

    Args:
        path: Path to the TOML file.

    Returns:
        Parsed TOML as a dictionary.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        tomllib.TOMLDecodeError: If the file is invalid TOML.
    """
    with open(path, "rb") as f:
        result: dict[str, Any] = tomllib.load(f)
        return result


def load_config(config_path: str | Path | None = None) -> Config:
    """Load configuration from file.

    Args:
        config_path: Explicit path to config file. If None, searches
                     default locations.

    Returns:
        Config object with values from the config file.
        Returns default Config if no file found.
    """
    config = Config()

    # Find config file
    path: Path | None
    if config_path:
        path = Path(config_path)
        if not path.is_file():
            logger.warning("Config file not found: %s", path)
            return config
    else:
        path = _find_config_file()
        if path is None:
            return config

    # Parse config file
    try:
        data = _parse_toml(path)
        config._config_path = str(path)
    except tomllib.TOMLDecodeError as e:
        logger.error("Invalid TOML in %s: %s", path, e)
        return config

    # Extract NCBI settings
    ncbi_data = data.get("ncbi", {})
    if isinstance(ncbi_data, dict):
        config.ncbi = NCBIConfig(
            email=ncbi_data.get("email"),
            api_key=ncbi_data.get("api_key"),
        )

    # Extract GROBID settings
    grobid_data = data.get("grobid", {})
    if isinstance(grobid_data, dict):
        url = grobid_data.get("url")
        if url:
            config.grobid = GrobidConfig(url=url)

    logger.info("Loaded config from %s", path)
    return config


def get_setting(
    key: str,
    cli_value: str | None = None,
    config: Config | None = None,
    default: str | None = None,
) -> str | None:
    """Get a configuration setting with priority resolution.

    Priority order:
    1. CLI value (if provided)
    2. Environment variable
    3. Config file value
    4. Default value

    Args:
        key: Setting key in dot notation (e.g., "ncbi.email")
        cli_value: Value from CLI flag (highest priority)
        config: Config object from load_config()
        default: Default value if not found anywhere

    Returns:
        The resolved setting value, or default if not found.

    Example:
        >>> config = load_config()
        >>> email = get_setting("ncbi.email", cli_value=args.email, config=config)
    """
    # 1. CLI value (highest priority)
    if cli_value is not None:
        return cli_value

    # 2. Environment variable
    env_var = ENV_MAPPINGS.get(key)
    if env_var:
        env_value = os.environ.get(env_var)
        if env_value is not None:
            return env_value

    # 3. Config file value
    if config:
        parts = key.split(".")
        if len(parts) == 2:
            section, setting = parts
            if section == "ncbi":
                value: str | None = getattr(config.ncbi, setting, None)
                if value is not None:
                    return value
            elif section == "grobid":
                value = getattr(config.grobid, setting, None)
                if value is not None:
                    return str(value) if value else None

    # 4. Default value
    return default


def get_ncbi_email(cli_value: str | None = None, config: Config | None = None) -> str:
    """Get NCBI email with priority resolution.

    Args:
        cli_value: Value from --email CLI flag
        config: Config object

    Returns:
        Email address

    Raises:
        ValueError: If no email is configured
    """
    email = get_setting("ncbi.email", cli_value=cli_value, config=config)
    if not email:
        raise ValueError(
            "NCBI email is required. Set via --email flag, NCBI_EMAIL environment "
            "variable, or ncbi.email in text-fetch.toml"
        )
    return email


def get_ncbi_api_key(
    cli_value: str | None = None, config: Config | None = None
) -> str | None:
    """Get NCBI API key with priority resolution.

    Args:
        cli_value: Value from --api-key CLI flag
        config: Config object

    Returns:
        API key or None if not configured
    """
    return get_setting("ncbi.api_key", cli_value=cli_value, config=config)


def get_grobid_url(cli_value: str | None = None, config: Config | None = None) -> str:
    """Get GROBID URL with priority resolution.

    Args:
        cli_value: Value from --grobid-url CLI flag
        config: Config object

    Returns:
        GROBID service URL
    """
    return (
        get_setting(
            "grobid.url",
            cli_value=cli_value,
            config=config,
            default="http://localhost:8070",
        )
        or "http://localhost:8070"
    )
