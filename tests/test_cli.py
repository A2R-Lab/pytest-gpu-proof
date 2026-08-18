import runpy
import sys
from types import SimpleNamespace

import pytest

from pytest_gpu_proof import cli
from pytest_gpu_proof.merge import MergeError


def test_verify_cli_forwards_options(monkeypatch, tmp_path):
    seen = {}

    def verify_receipt(**kwargs):
        seen.update(kwargs)
        return True

    monkeypatch.setattr("pytest_gpu_proof.verify.verify_receipt", verify_receipt)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gpu-proof", "verify", "--receipt", "r.json", "--policy", "p.json",
            "--repo", str(tmp_path), "--github-user", "alice", "--max-age-days", "4",
            "--allow-unsigned", "--allow-skipped", "--require-gpu",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert seen["github_user_override"] == "alice"
    assert seen["max_age_days"] == 4
    assert seen["allow_unsigned"] and seen["allow_skipped"] and seen["require_gpu"]


def test_verify_cli_failure(monkeypatch):
    monkeypatch.setattr("pytest_gpu_proof.verify.verify_receipt", lambda **_: False)
    monkeypatch.setattr(sys, "argv", ["gpu-proof", "verify", "--receipt", "r.json"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1


def test_merge_cli_success_and_error(monkeypatch, capsys):
    monkeypatch.setattr(
        "pytest_gpu_proof.merge.merge_receipts",
        lambda *args, **kwargs: {"tests": [{}, {}], "session": {"shards": [{}, {}]}},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["gpu-proof", "merge", "a.json", "b.json", "--out", "out.json", "--unsigned"],
    )
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert "2 shard(s), 2 tests" in capsys.readouterr().out

    def fail(*args, **kwargs):
        raise MergeError("bad shards")

    monkeypatch.setattr("pytest_gpu_proof.merge.merge_receipts", fail)
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert "bad shards" in capsys.readouterr().err


def test_module_entrypoint(monkeypatch):
    monkeypatch.setattr("pytest_gpu_proof.cli.main", lambda: (_ for _ in ()).throw(SystemExit(7)))
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("pytest_gpu_proof.__main__", run_name="__main__")
    assert exc.value.code == 7


@pytest.mark.filterwarnings("ignore:.*found in sys.modules.*:RuntimeWarning")
def test_cli_file_entrypoint(monkeypatch):
    monkeypatch.setattr("pytest_gpu_proof.verify.verify_receipt", lambda **kwargs: True)
    monkeypatch.setattr(sys, "argv", ["gpu-proof", "verify", "--receipt", "r.json"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("pytest_gpu_proof.cli", run_name="__main__")
    assert exc.value.code == 0
