from pathlib import Path
import tomllib

from runner.version import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_package_version_has_one_runtime_owner():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in config["project"]
    assert "version" in config["project"]["dynamic"]
    assert config["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "runner.version.__version__"


def test_displayed_version_matches_release_docs():
    assert __version__ == "1.2.49"
    assert f"Version: {__version__}" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"版本：{__version__}" in (ROOT / "README.zh-TW.md").read_text(encoding="utf-8")
