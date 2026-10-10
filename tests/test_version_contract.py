from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from runner.version import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_package_version_has_one_runtime_owner():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" not in config["project"]
    assert "version" in config["project"]["dynamic"]
    assert config["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "runner.version.__version__"


def test_displayed_version_matches_release_docs():
    assert f"Version: {__version__}" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"版本：{__version__}" in (ROOT / "README.zh-TW.md").read_text(encoding="utf-8")


def test_readmes_do_not_document_removed_error_route():
    for name in ("README.md", "README.zh-TW.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "error: stop" not in text
        assert "routes.error" not in text
