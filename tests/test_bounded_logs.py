from runner.utils.logs import append_bounded_log


def test_bounded_log_keeps_only_current_and_previous_file(tmp_path):
    path = tmp_path / "runner.log"
    append_bounded_log(path, "first\n", max_bytes=10)
    append_bounded_log(path, "second\n", max_bytes=10)
    append_bounded_log(path, "third\n", max_bytes=10)

    assert path.read_text(encoding="utf-8") == "third\n"
    assert path.with_name("runner.log.1").read_text(encoding="utf-8") == "second\n"
