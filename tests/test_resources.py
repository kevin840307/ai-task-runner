from pathlib import Path

from runner.utils import path_key, remove_path, same_path


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


def test_remove_path_deletes_short_root_with_deep_descendants(tmp_path):
    root = tmp_path / "tree"
    deep = root
    index = 0
    while len(str(deep)) <= 300:
        deep = deep / (f"segment-{index}-" + "x" * 38)
        index += 1

    from runner.utils import io_path

    io_path(deep).mkdir(parents=True, exist_ok=True)
    io_path(deep / "payload.txt").write_text("x", encoding="utf-8")

    remove_path(root)

    assert not root.exists()
