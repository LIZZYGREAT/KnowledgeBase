import sys

from tools import perf_smoke


def test_perf_smoke_measures_library_state_endpoints(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "perf_smoke.py",
            "--repeat",
            "1",
            "--source-id",
            "source-one",
            "--term-id",
            "term-one",
        ],
    )
    requested_paths = []

    def record_measurement(base_url, path, repeats):
        requested_paths.append(path)
        return [12.0] * repeats

    monkeypatch.setattr(perf_smoke, "measure", record_measurement)

    assert perf_smoke.main() == 0

    assert "/api/library/document-states" in requested_paths
    assert "/api/library/source-states" in requested_paths
    assert "/api/documents?limit=1&offset=0" not in requested_paths
    output = capsys.readouterr().out
    assert "Library document states: median=12.0 ms" in output
    assert "Library source states: median=12.0 ms" in output
