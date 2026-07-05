"""
pytest plugin entry point.

Registers CLI options, markers, and the gpu_proof_check fixture.
At session end, builds a signed receipt for every test that used the fixture.
"""

import datetime
import warnings
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
        self.skipped_required: List[str] = []
        self.started_at: str = ""

    # ------------------------------------------------------------------
    # session lifecycle
    # ------------------------------------------------------------------

    def pytest_sessionstart(self, session):
        self.started_at = _utcnow()

    def pytest_sessionfinish(self, session, exitstatus):
        if not self.gpu_proof_config.enabled:
            return

        skipped_marked = [
            t["node_id"] for t in self.test_results if t.get("outcome") == "skipped"
        ]
        if self.gpu_proof_config.fail_on_skip and (skipped_marked or self.skipped_required):
            names = sorted(set(skipped_marked + self.skipped_required))
            print(
                "\n[gpu-proof] --gpu-proof-fail-on-skip: "
                f"{len(names)} marked test(s) were skipped:\n"
                + "".join(f"            - {n}\n" for n in names)
                + "            No receipt was written; session marked as failed."
            )
            session.exitstatus = 1
            return

        if not self.test_results:
            print(
                "\n[gpu-proof] --gpu-proof-enable is set but no gpu_proof tests were found.\n"
                "            Add @pytest.mark.gpu_proof to your tests or use the gpu_proof_check fixture.\n"
                "            No receipt was written.\n"
                "            Tip: try 'pytest examples/minimal_python_only/test_minimal.py --gpu-proof-enable -v'"
            )
            return
        self._emit_receipt()

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

        if call.when == "setup" and report.skipped:
            # Skipped tests never reach the "call" phase — record them here so
            # they are visible in the receipt (and to --gpu-proof-fail-on-skip)
            # instead of being silently dropped.
            if item.get_closest_marker("gpu_required") and not self._is_marked(item):
                self.skipped_required.append(item.nodeid)
            if self._is_marked(item):
                self.test_results.append(
                    {
                        "node_id": item.nodeid,
                        "outcome": "skipped",
                        "duration_s": round(call.duration, 4),
                        "checks": [],
                    }
                )
            return

        if call.when == "teardown":
            # The gpu_proof_check fixture records its checks during fixture
            # teardown, which happens *after* the call-phase report. Patch the
            # already-recorded entry here so checks are not silently dropped.
            checks = getattr(item, "_gpu_proof_checks", None)
            if checks is not None:
                for t in reversed(self.test_results):
                    if t["node_id"] == item.nodeid:
                        t["checks"] = checks
                        break
            return

        if call.when != "call":
            return

        uses_fixture = "gpu_proof_check" in getattr(item, "fixturenames", ())
        if not uses_fixture and not self._is_marked(item):
            return

        if report.passed:
            outcome_str = "passed"
        elif report.skipped:
            outcome_str = "skipped"
        else:
            outcome_str = "failed"

        self.test_results.append(
            {
                "node_id": item.nodeid,
                "outcome": outcome_str,
                "duration_s": round(call.duration, 4),
                "checks": [],  # filled in at teardown once the fixture finalizes
            }
        )

    # ------------------------------------------------------------------
    # receipt emission
    # ------------------------------------------------------------------

    def _emit_receipt(self):
        from .receipt import build_receipt_payload, finalize_receipt, write_receipt
        from .signers.ed25519 import SSHSigner
        from .signers.base import VerifierError

        ended_at = _utcnow()
        cfg = self.gpu_proof_config

        if cfg.signing_backend == "none":
            try:
                payload = build_receipt_payload(cfg, self.test_results, self.started_at, ended_at)
                receipt = dict(payload)
                receipt["signature"] = None
                write_receipt(receipt, cfg.output)
                print(f"\n[gpu-proof] Receipt written to {cfg.output}")
                print(
                    "[gpu-proof] WARNING: signing backend is 'none' — the receipt is UNSIGNED\n"
                    "            and will fail verification unless --allow-unsigned is passed."
                )
            except Exception as e:
                warnings.warn(f"[gpu-proof] Failed to write receipt: {e}", stacklevel=1)
            return

        try:
            signer = SSHSigner(key_path=cfg.key_path)
        except VerifierError as e:
            warnings.warn(f"[gpu-proof] Signing skipped: {e}", stacklevel=1)
            return

        try:
            payload = build_receipt_payload(cfg, self.test_results, self.started_at, ended_at)
            receipt = finalize_receipt(payload, signer)
            write_receipt(receipt, cfg.output)
            print(f"\n[gpu-proof] Receipt written to {cfg.output}")
            print(f"[gpu-proof] Signed with key {signer.key_fingerprint()}")
        except Exception as e:
            warnings.warn(f"[gpu-proof] Failed to write receipt: {e}", stacklevel=1)


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
        default="local",
        choices=["local", "ci-gpu"],
        help="Execution mode: local (default) or ci-gpu",
    )
    group.addoption(
        "--gpu-proof-out",
        default="gpu-proof.json",
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
        default="ed25519",
        choices=["ed25519", "none"],
        help="Signing backend (default: ed25519 via SSH key)",
    )
    group.addoption(
        "--gpu-proof-policy",
        default=None,
        metavar="PATH",
        help="Path to verification policy YAML",
    )
    group.addoption(
        "--gpu-proof-required-marker",
        default="gpu_proof",
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
        default="src,tests",
        metavar="PATHS",
        help="Comma-separated paths to fingerprint (default: src,tests)",
    )
    group.addoption(
        "--gpu-proof-github-user",
        default=None,
        metavar="USERNAME",
        help="GitHub username of the signer (default: auto-detect from git remote)",
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
        plugin = GpuProofPlugin(config)
        config.pluginmanager.register(plugin, "gpu-proof-plugin")


def pytest_collection_modifyitems(config, items):
    try:
        enabled = config.getoption("--gpu-proof-enable")
    except ValueError:
        enabled = False

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
