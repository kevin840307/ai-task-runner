from pathlib import Path

from runner.utils.files import path_key, same_path


def test_atomic_resource_temp_name_does_not_repeat_long_target_name(tmp_path, monkeypatch):
    import runner.resources as resources

    seen = {}
    original_replace = resources.os.replace

    def capture(source, target):
        seen["source"] = Path(source)
        seen["target"] = Path(target)
        return original_replace(source, target)

    monkeypatch.setattr(resources.os, "replace", capture)
    target = tmp_path / ("a" * 96 + ".md")
    resources.write_text(target, "ok")

    assert same_path(seen["target"], target)
    assert same_path(seen["source"].parent, target.parent)
    assert target.name not in seen["source"].name
    assert seen["source"].name.startswith(".tmp-")


def test_path_identity_ignores_logical_spelling(tmp_path):
    nested = tmp_path / "folder"
    nested.mkdir()
    alternate = nested / ".." / "folder"

    assert path_key(nested) == path_key(alternate)
    assert same_path(nested, alternate)
