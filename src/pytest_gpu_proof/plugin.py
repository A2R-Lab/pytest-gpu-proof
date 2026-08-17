"""
pytest plugin entry point.

Registers CLI options, markers, and the gpu_proof_check fixture.
At session end, builds a signed receipt for every test that used the fixture.
"""

import datetime
import warnings
from pathlib import Path
from typing import Any, Dict, List

import pytest

from .compare import run_comparison
from .config import GpuProofConfig, load_config


def _utcnow() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _has_gpu() -> bool:
    import subprocess
    try:
        r = subprocess.run(["nvidia-smi"], capture_output=True, timeout=5)
        if r.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        pass
    return False


class GpuProofPlugin:
    def __init__(self, pytest_config):
        self.gpu_proof_config: GpuProofConfig = load_config(pytest_config)
        self.test_results: List[Dict[str, Any]] = []
        self._results_by_node: Dict[str, Dict[str, Any]] = {}
        self.collected_node_ids: List[str] = []
        self.skipped_required: List[str] = []
        self.started_at: str = ""

    # ------------------------------------------------------------------
    # session lifecycle
    # ------------------------------------------------------------------

    def pytest_sessionstart(self, session):
        self.started_at = _utcnow()
        output = Path(self.gpu_proof_config.output)
        if not output.is_absolute():
            output = Path(self.gpu_proof_config.repo_root) / output
            self.gpu_proof_config.output = str(output)
        try:
            output.unlink(missing_ok=True)
        except OSError as exc:
            self._fail_or_warn(session, f"cannot clear stale receipt {output}: {exc}")

    def pytest_collection_finish(self, session):
        self.collected_node_ids = [
            item.nodeid
            for item in session.items
            if self._is_marked(item)
            or "gpu_proof_check" in getattr(item, "fixturenames", ())
        ]

    def _fail_or_warn(self, session, message):
        if self.gpu_proof_config.best_effort:
            warnings.warn(f"[gpu-proof] {message}", stacklevel=1)
        else:
            print(f"\n[gpu-proof] ERROR: {message}")
            session.exitstatus = pytest.ExitCode.TESTS_FAILED

    def pytest_sessionfinish(self, session, exitstatus):
        if not self.gpu_proof_config.enabled:
            return

        if not self.collected_node_ids:
            print(
                "\n[gpu-proof] --gpu-proof-enable is set but no gpu_proof tests were found."
            )
            self._fail_or_warn(session, "receipt requested but no marked tests were collected")
            return

        skipped_marked = [
            node_id
            for node_id, result in self._results_by_node.items()
            if result.get("outcome") == "skipped"
        ]
        if self.gpu_proof_config.fail_on_skip and (skipped_marked or self.skipped_required):
            names = sorted(set(skipped_marked + self.skipped_required))
            print(
                "\n[gpu-proof] --gpu-proof-fail-on-skip: "
                f"{len(names)} marked test(s) were skipped:\n"
                + "".join(f"            - {n}\n" for n in names)
                + "            No receipt was written; session marked as failed."
            )
            session.exitstatus = pytest.ExitCode.TESTS_FAILED
            return

        for node_id in self.collected_node_ids:
            if node_id not in self._results_by_node:
                self._results_by_node[node_id] = {
                    "node_id": node_id,
                    "outcome": "error",
                    "duration_s": 0.0,
                    "checks": [],
                    "phase": "missing-terminal-report",
                }
        self.test_results = [self._results_by_node[node] for node in self.collected_node_ids]
        session_outcome = "passed" if session.exitstatus == pytest.ExitCode.OK else "failed"
        try:
            self._emit_receipt(session_outcome)
        except Exception as exc:
            self._fail_or_warn(session, f"failed to create receipt: {exc}")

    # ------------------------------------------------------------------
    # result collection
    # ------------------------------------------------------------------

    def _is_marked(self, item) -> bool:
        return bool(
            item.get_closest_marker(self.gpu_proof_config.required_marker)
            or item.get_closest_marker("gpu_equivalence")
        )

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()

        included = self._is_marked(item) or "gpu_proof_check" in getattr(
            item, "fixturenames", ()
        )
        if not included:
            if call.when == "setup" and report.skipped and item.get_closest_marker("gpu_required"):
                self.skipped_required.append(item.nodeid)
            return

        if call.when == "setup" and report.skipped:
            # Skipped tests never reach the "call" phase — record them here so
            # they are visible in the receipt (and to --gpu-proof-fail-on-skip)
            # instead of being silently dropped.
            self._results_by_node[item.nodeid] = {
                "node_id": item.nodeid,
                "outcome": "skipped",
                "duration_s": round(call.duration, 4),
                "checks": [],
                "phase": "setup",
            }
            return

        if report.failed:
            previous = self._results_by_node.get(item.nodeid, {})
            self._results_by_node[item.nodeid] = {
                "node_id": item.nodeid,
                "outcome": "failed",
                "duration_s": round(previous.get("duration_s", 0.0) + call.duration, 4),
                "checks": getattr(item, "_gpu_proof_checks", previous.get("checks", [])),
                "phase": call.when,
            }
            return

        if call.when == "teardown":
            # The gpu_proof_check fixture records its checks during fixture
            # teardown, which happens *after* the call-phase report. Patch the
            # already-recorded entry here so checks are not silently dropped.
            checks = getattr(item, "_gpu_proof_checks", None)
            if checks is not None:
                result = self._results_by_node.get(item.nodeid)
                if result is not None:
                    result["checks"] = checks
            return

        if call.when != "call":
            return

        if report.passed:
            outcome_str = "passed"
        elif report.skipped:
            outcome_str = "skipped"
        else:
            outcome_str = "failed"

        self._results_by_node[item.nodeid] = {
            "node_id": item.nodeid,
            "outcome": outcome_str,
            "duration_s": round(call.duration, 4),
            "checks": [],
            "phase": "call",
        }

    # ------------------------------------------------------------------
    # receipt emission
    # ------------------------------------------------------------------

    def _emit_receipt(self, session_outcome):
        from .receipt import build_receipt_payload, finalize_receipt, write_receipt
        from .signers.ed25519 import SSHSigner

        ended_at = _utcnow()
        cfg = self.gpu_proof_config

        payload = build_receipt_payload(
            cfg,
            self.test_results,
            self.started_at,
            ended_at,
            session_outcome=session_outcome,
            collected_node_ids=self.collected_node_ids,
        )
        if cfg.signing_backend == "none":
            receipt = dict(payload)
            receipt["signature"] = None
        else:
            signer = SSHSigner(key_path=cfg.key_path, root=cfg.repo_root)
            receipt = finalize_receipt(payload, signer)
        write_receipt(receipt, cfg.output)
        print(f"\n[gpu-proof] Receipt written to {cfg.output}")
        if cfg.signing_backend == "none":
            print("[gpu-proof] WARNING: receipt is UNSIGNED")
        else:
            print(f"[gpu-proof] Signed with key {signer.key_fingerprint()}")


# ------------------------------------------------------------------
# plugin registration hooks (module-level, always active)
# ------------------------------------------------------------------

def pytest_addoption(parser):
    group = parser.getgroup("gpu-proof", "GPU proof receipt generation")
    group.addoption(
        "--gpu-proof-enable",
        action="store_true",
        default=False,
        help="Enable GPU proof receipt generation",
    )
    group.addoption(
        "--gpu-proof-mode",
        default=None,
        choices=["local", "ci-gpu"],
        help="Execution mode: local (default) or ci-gpu",
    )
    group.addoption(
        "--gpu-proof-out",
        default=None,
        metavar="PATH",
        help="Output path for the receipt JSON (default: gpu-proof.json)",
    )
    group.addoption(
        "--gpu-proof-key",
        default=None,
        metavar="PATH",
        help="Path to SSH private key (default: auto-discover from git config or ~/.ssh/)",
    )
    group.addoption(
        "--gpu-proof-signing-backend",
        default=None,
        choices=["ed25519", "none"],
        help="Signing backend (default: ed25519 via SSH key)",
    )
    group.addoption(
        "--gpu-proof-required-marker",
        default=None,
        help="Marker name that flags a test for the receipt (default: gpu_proof)",
    )
    group.addoption(
        "--gpu-proof-fail-on-skip",
        action="store_true",
        default=False,
        help="Fail the session if any gpu_required test is skipped",
    )
    group.addoption(
        "--gpu-proof-fingerprint-paths",
        default=None,
        metavar="PATHS",
        help="Comma-separated tracked paths to fingerprint (default: entire repository)",
    )
    group.addoption(
        "--gpu-proof-fingerprint-extra-paths",
        default=None,
        metavar="PATHS",
        help="Explicit generated/ignored files or directories to fingerprint",
    )
    group.addoption(
        "--gpu-proof-fingerprint-excluded-paths",
        default=None,
        metavar="PATHS",
        help="Comma-separated receipt artifacts to exclude from the source manifest "
        "(default: gpu-proof.json)",
    )
    group.addoption(
        "--gpu-proof-shard",
        default=None,
        metavar="NAME",
        help="Declare this run as one SHARD of a larger suite: the receipt has "
        "a per-shard fingerprint, enabling "
        "verifiable carry-forward via `gpu-proof merge --carry-from`",
    )
    group.addoption(
        "--gpu-proof-shard-fingerprint-paths",
        default=None,
        metavar="PATHS",
        help="Comma-separated paths for THIS shard's narrow fingerprint "
        "(default: the global fingerprint paths)",
    )
    group.addoption(
        "--gpu-proof-shard-fingerprint-extra-paths",
        default=None,
        metavar="PATHS",
        help="Explicit generated/ignored inputs for this shard",
    )
    group.addoption(
        "--gpu-proof-github-user",
        default=None,
        metavar="USERNAME",
        help="GitHub username of the signer (default: auto-detect from git remote)",
    )
    group.addoption(
        "--gpu-proof-best-effort",
        action="store_true",
        default=False,
        help="Warn instead of failing pytest when receipt creation fails",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "gpu_proof: include test in GPU proof receipt")
    config.addinivalue_line("markers", "gpu_required: skip test if no GPU is available")
    config.addinivalue_line(
        "markers",
        "gpu_equivalence: alias for gpu_proof; marks a GPU equivalence check",
    )

    try:
        enabled = config.getoption("--gpu-proof-enable")
    except ValueError:
        enabled = False

    if enabled:
        if hasattr(config, "workerinput"):
            raise pytest.UsageError(
                "pytest-gpu-proof does not support xdist workers; run receipt "
                "shards as separate pytest processes and merge them instead"
            )
        plugin = GpuProofPlugin(config)
        config.pluginmanager.register(plugin, "gpu-proof-plugin")


def pytest_collection_modifyitems(config, items):
    skip_no_gpu = pytest.mark.skip(reason="No GPU available (gpu_required marker)")
    has_gpu = None  # lazy

    for item in items:
        if item.get_closest_marker("gpu_required"):
            if has_gpu is None:
                has_gpu = _has_gpu()
            if not has_gpu:
                item.add_marker(skip_no_gpu)


# ------------------------------------------------------------------
# fixture
# ------------------------------------------------------------------

@pytest.fixture
def gpu_proof_check(request):
    """
    Fixture for GPU equivalence checking.

    Usage::

        def test_rnea(gpu_proof_check):
            gpu_proof_check(
                name="rnea",
                reference=python_ref,
                candidate=cuda_fn,
                args=(q, qd, qdd),
                compare=my_compare_fn,   # optional; default: numpy.allclose / ==
                metadata={"robot": "go2"},
            )
    """
    checks = []

    def check(name, reference, candidate, args=(), kwargs=None, compare=None, metadata=None):
        outcome, _ref, _cand, error = run_comparison(
            reference, candidate, args or (), kwargs or {}, compare
        )
        checks.append(
            {
                "name": name,
                "outcome": outcome,
                "metadata": metadata or {},
            }
        )
        if outcome != "passed":
            pytest.fail(f"gpu_proof_check {name!r}: {error}")

    yield check

    request.node._gpu_proof_checks = checks
