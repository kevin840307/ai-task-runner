from pathlib import Path


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

    assert seen["target"] == target.resolve()
    assert seen["source"].parent == target.parent.resolve()
    assert target.name not in seen["source"].name
    assert seen["source"].name.startswith(".tmp-")
