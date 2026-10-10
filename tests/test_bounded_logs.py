from runner.utils import append_bounded_log


def test_bounded_log_keeps_only_current_and_previous_file(tmp_path):
    path = tmp_path / "runner.log"
    append_bounded_log(path, "first\n", max_bytes=10)
    append_bounded_log(path, "second\n", max_bytes=10)
    append_bounded_log(path, "third\n", max_bytes=10)

    assert path.read_text(encoding="utf-8") == "third\n"
    assert path.with_name("runner.log.1").read_text(encoding="utf-8") == "second\n"



def test_bounded_log_truncates_single_oversized_write_by_bytes(tmp_path):
    path = tmp_path / "runner.log"
    append_bounded_log(path, "前" * 20 + "tail", max_bytes=16)

    assert path.stat().st_size <= 16
    assert path.read_text(encoding="utf-8").endswith("tail")


def test_bounded_log_oversized_write_rotates_previous_current_file(tmp_path):
    path = tmp_path / "runner.log"
    append_bounded_log(path, "before\n", max_bytes=12)
    append_bounded_log(path, "x" * 40, max_bytes=12)

    assert path.stat().st_size <= 12
    assert path.read_text(encoding="utf-8") == "x" * 12
    assert path.with_name("runner.log.1").read_text(encoding="utf-8") == "before\n"
