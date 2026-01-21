"""Unit tests for configuration management."""

from __future__ import annotations

from pathlib import Path

import pytest
from text_fetch.config import (
    Config,
    GrobidConfig,
    NCBIConfig,
    get_grobid_url,
    get_ncbi_api_key,
    get_ncbi_email,
    get_setting,
    load_config,
)


class TestConfigDataclasses:
    """Tests for configuration dataclasses."""

    def test_ncbi_config_defaults(self):
        """NCBIConfig has None defaults."""
        config = NCBIConfig()
        assert config.email is None
        assert config.api_key is None

    def test_ncbi_config_with_values(self):
        """NCBIConfig accepts values."""
        config = NCBIConfig(email="test@example.com", api_key="my_key")
        assert config.email == "test@example.com"
        assert config.api_key == "my_key"

    def test_grobid_config_defaults(self):
        """GrobidConfig has sensible defaults."""
        config = GrobidConfig()
        assert config.url == "http://localhost:8070"

    def test_grobid_config_with_values(self):
        """GrobidConfig accepts custom URL."""
        config = GrobidConfig(url="http://grobid:8080")
        assert config.url == "http://grobid:8080"

    def test_config_defaults(self):
        """Config has nested default configs."""
        config = Config()
        assert isinstance(config.ncbi, NCBIConfig)
        assert isinstance(config.grobid, GrobidConfig)
        assert config.config_path is None

    def test_config_with_custom_nested(self):
        """Config accepts custom nested configs."""
        config = Config(
            ncbi=NCBIConfig(email="user@example.com"),
            grobid=GrobidConfig(url="http://custom:8080"),
        )
        assert config.ncbi.email == "user@example.com"
        assert config.grobid.url == "http://custom:8080"


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_config_no_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Returns default config when no file exists."""
        monkeypatch.chdir(tmp_path)
        config = load_config()
        assert config.ncbi.email is None
        assert config.ncbi.api_key is None
        assert config.grobid.url == "http://localhost:8070"
        assert config.config_path is None

    def test_load_config_with_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Loads config from TOML file."""
        config_file = tmp_path / "text-fetch.toml"
        config_file.write_text("""
[ncbi]
email = "loaded@example.com"
api_key = "loaded_key"

[grobid]
url = "http://loaded:8080"
""")
        monkeypatch.chdir(tmp_path)
        config = load_config()
        assert config.ncbi.email == "loaded@example.com"
        assert config.ncbi.api_key == "loaded_key"
        assert config.grobid.url == "http://loaded:8080"
        assert config.config_path == str(config_file)

    def test_load_config_partial(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Loads partial config, uses defaults for missing."""
        config_file = tmp_path / "text-fetch.toml"
        config_file.write_text("""
[ncbi]
email = "partial@example.com"
""")
        monkeypatch.chdir(tmp_path)
        config = load_config()
        assert config.ncbi.email == "partial@example.com"
        assert config.ncbi.api_key is None
        assert config.grobid.url == "http://localhost:8070"

    def test_load_config_explicit_path(self, tmp_path: Path):
        """Loads from explicit path."""
        config_file = tmp_path / "custom-config.toml"
        config_file.write_text("""
[ncbi]
email = "explicit@example.com"
""")
        config = load_config(config_file)
        assert config.ncbi.email == "explicit@example.com"
        assert config.config_path == str(config_file)

    def test_load_config_missing_explicit_path(self, tmp_path: Path):
        """Returns default if explicit path doesn't exist."""
        config = load_config(tmp_path / "nonexistent.toml")
        assert config.ncbi.email is None
        assert config.config_path is None

    def test_load_config_invalid_toml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Returns default config for invalid TOML."""
        config_file = tmp_path / "text-fetch.toml"
        config_file.write_text("invalid [ toml syntax")
        monkeypatch.chdir(tmp_path)
        config = load_config()
        assert config.ncbi.email is None
        assert config.config_path is None


class TestGetSetting:
    """Tests for get_setting priority resolution."""

    def test_cli_value_highest_priority(self):
        """CLI value takes precedence over everything."""
        config = Config(ncbi=NCBIConfig(email="config@example.com"))
        result = get_setting("ncbi.email", cli_value="cli@example.com", config=config)
        assert result == "cli@example.com"

    def test_env_var_over_config(self, monkeypatch: pytest.MonkeyPatch):
        """Environment variable takes precedence over config file."""
        monkeypatch.setenv("NCBI_EMAIL", "env@example.com")
        config = Config(ncbi=NCBIConfig(email="config@example.com"))
        result = get_setting("ncbi.email", config=config)
        assert result == "env@example.com"

    def test_config_file_value(self):
        """Config file value used when no CLI or env."""
        config = Config(ncbi=NCBIConfig(email="config@example.com"))
        result = get_setting("ncbi.email", config=config)
        assert result == "config@example.com"

    def test_default_value(self):
        """Default value used when nothing else available."""
        config = Config()
        result = get_setting("ncbi.email", config=config, default="default@example.com")
        assert result == "default@example.com"

    def test_none_when_not_found(self):
        """Returns None when no value found anywhere."""
        config = Config()
        result = get_setting("ncbi.email", config=config)
        assert result is None

    def test_grobid_url_setting(self):
        """Works for grobid section."""
        config = Config(grobid=GrobidConfig(url="http://custom:8080"))
        result = get_setting("grobid.url", config=config)
        assert result == "http://custom:8080"

    def test_cli_overrides_env(self, monkeypatch: pytest.MonkeyPatch):
        """CLI value overrides environment variable."""
        monkeypatch.setenv("NCBI_EMAIL", "env@example.com")
        result = get_setting("ncbi.email", cli_value="cli@example.com")
        assert result == "cli@example.com"


class TestGetNCBIEmail:
    """Tests for get_ncbi_email helper."""

    def test_returns_email(self):
        """Returns email when configured."""
        config = Config(ncbi=NCBIConfig(email="user@example.com"))
        email = get_ncbi_email(config=config)
        assert email == "user@example.com"

    def test_raises_when_missing(self):
        """Raises ValueError when email not configured."""
        config = Config()
        with pytest.raises(ValueError, match="NCBI email is required"):
            get_ncbi_email(config=config)

    def test_cli_override(self):
        """CLI value overrides config."""
        config = Config(ncbi=NCBIConfig(email="config@example.com"))
        email = get_ncbi_email(cli_value="cli@example.com", config=config)
        assert email == "cli@example.com"


class TestGetNCBIAPIKey:
    """Tests for get_ncbi_api_key helper."""

    def test_returns_key(self):
        """Returns API key when configured."""
        config = Config(ncbi=NCBIConfig(api_key="my_key"))
        key = get_ncbi_api_key(config=config)
        assert key == "my_key"

    def test_returns_none_when_missing(self):
        """Returns None when API key not configured."""
        config = Config()
        key = get_ncbi_api_key(config=config)
        assert key is None

    def test_cli_override(self):
        """CLI value overrides config."""
        config = Config(ncbi=NCBIConfig(api_key="config_key"))
        key = get_ncbi_api_key(cli_value="cli_key", config=config)
        assert key == "cli_key"


class TestGetGrobidURL:
    """Tests for get_grobid_url helper."""

    def test_returns_url(self):
        """Returns URL when configured."""
        config = Config(grobid=GrobidConfig(url="http://custom:8080"))
        url = get_grobid_url(config=config)
        assert url == "http://custom:8080"

    def test_returns_default(self):
        """Returns default when not configured."""
        config = Config()
        url = get_grobid_url(config=config)
        assert url == "http://localhost:8070"

    def test_cli_override(self):
        """CLI value overrides config."""
        config = Config(grobid=GrobidConfig(url="http://config:8080"))
        url = get_grobid_url(cli_value="http://cli:8080", config=config)
        assert url == "http://cli:8080"


class TestEnvironmentVariables:
    """Tests for environment variable support."""

    def test_ncbi_email_env(self, monkeypatch: pytest.MonkeyPatch):
        """NCBI_EMAIL environment variable works."""
        monkeypatch.setenv("NCBI_EMAIL", "env@example.com")
        email = get_ncbi_email()
        assert email == "env@example.com"

    def test_ncbi_api_key_env(self, monkeypatch: pytest.MonkeyPatch):
        """NCBI_API_KEY environment variable works."""
        monkeypatch.setenv("NCBI_API_KEY", "env_key")
        key = get_ncbi_api_key()
        assert key == "env_key"

    def test_grobid_url_env(self, monkeypatch: pytest.MonkeyPatch):
        """GROBID_URL environment variable works."""
        monkeypatch.setenv("GROBID_URL", "http://env:8080")
        url = get_grobid_url()
        assert url == "http://env:8080"
