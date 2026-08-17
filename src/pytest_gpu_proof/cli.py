import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="gpu-proof",
        description="pytest-gpu-proof: verify signed GPU test receipts",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # verify
    vp = subparsers.add_parser(
        "verify",
        help="Verify a signed receipt against GitHub public keys",
    )
    vp.add_argument("--receipt", required=True, metavar="PATH", help="Path to gpu-proof.json")
    vp.add_argument(
        "--policy",
        default=None,
        metavar="PATH",
        help="Path to policy YAML/JSON (optional)",
    )
    vp.add_argument(
        "--repo",
        default=".",
        metavar="PATH",
        help="Repository root for fingerprint recomputation (default: .)",
    )
    vp.add_argument(
        "--github-user",
        default=None,
        metavar="USERNAME",
        help="Override GitHub username (default: read from receipt)",
    )
    vp.add_argument(
        "--max-age-days",
        type=int,
        default=None,
        metavar="N",
        help="Override max receipt age in days",
    )
    vp.add_argument(
        "--allow-unsigned",
        action="store_true",
        default=False,
        help="Accept UNSIGNED receipts (signature: null). Unsigned receipts prove "
        "nothing about who ran the tests — use only if you accept that.",
    )
    vp.add_argument(
        "--allow-skipped",
        action="store_true",
        default=False,
        help="Accept receipts that contain skipped marked tests (default: reject)",
    )
    vp.add_argument(
        "--expected-skips",
        default=None,
        metavar="PATH",
        help="Baseline file of node IDs (one per line, '#' comments) that the "
        "receipt's skipped tests must match EXACTLY — new skips fail, and a "
        "baselined test that now runs flags the baseline as stale. Stricter "
        "than (and mutually exclusive with) --allow-skipped. Can also be set "
        "as an inline list via expected_skips in [tool.gpu_proof].",
    )
    vp.add_argument(
        "--require-gpu",
        action="store_true",
        default=None,
        help="Fail verification if the receipt's environment.gpu_info is null/absent "
        "(modest hardening, not proof of GPU execution). Can also be set via "
        "require_gpu = true in [tool.gpu_proof].",
    )

    # merge
    mp = subparsers.add_parser(
        "merge",
        help="Merge shard receipts from ONE commit into a single re-signed receipt",
        description=(
            "Union the tests of N shard receipts (same commit SHA, fingerprint, "
            "and environment) into one receipt, re-signed with your local SSH "
            "key, that flows through `gpu-proof verify` unchanged. Shards that "
            "disagree on anything a receipt pins are refused; duplicate node "
            "IDs across shards are always an error."
        ),
    )
    mp.add_argument("shards", nargs="+", metavar="RECEIPT",
                    help="Shard receipt paths (two or more, typically)")
    mp.add_argument("--out", required=True, metavar="PATH",
                    help="Path for the merged receipt")
    mp.add_argument("--github-user", default=None, metavar="USERNAME",
                    help="Recorded signer identity for the merged receipt "
                    "(default: the first shard's repo.github_username)")
    mp.add_argument("--key", default=None, metavar="PATH",
                    help="SSH private key to sign with (default: git "
                    "user.signingKey, then ~/.ssh/id_ed25519 etc.)")
    mp.add_argument("--unsigned", action="store_true", default=False,
                    help="Write signature: null — the merged receipt then "
                    "verifies only with --allow-unsigned, loudly")
    mp.add_argument("--carry-from", default=None, metavar="RECEIPT",
                    help="Graft still-valid shards from an older sharded "
                    "receipt: each absent-from-fresh shard is carried iff the "
                    "old commit is an ancestor of the new one AND its narrow "
                    "fingerprint recomputes clean at the current tree. Carried "
                    "shards are marked and gated at verify time by policy "
                    "allow_carried (default: rejected).")
    mp.add_argument("--repo", default=".", metavar="PATH",
                    help="Repo root for carry-from fingerprint/ancestry checks")

    args = parser.parse_args()

    if args.command == "merge":
        from .merge import MergeError, merge_receipts

        try:
            receipt = merge_receipts(
                args.shards, args.out,
                github_user=args.github_user,
                key_path=args.key,
                unsigned=args.unsigned,
                carry_from=args.carry_from,
                repo_root=args.repo,
            )
        except MergeError as e:
            print(f"gpu-proof merge: {e}", file=sys.stderr)
            sys.exit(1)
        n = len(receipt.get("tests", []))
        shards = len(receipt.get("session", {}).get("shards", []))
        print(f"merged {shards} shard(s), {n} tests -> {args.out}"
              + (" (UNSIGNED)" if args.unsigned else ""))
        sys.exit(0)

    if args.command == "verify":  # pragma: no branch - argparse requires a known subcommand
        from .verify import verify_receipt

        ok = verify_receipt(
            receipt_path=args.receipt,
            policy_path=args.policy,
            repo_root=args.repo,
            github_user_override=args.github_user,
            max_age_days=args.max_age_days,
            allow_unsigned=args.allow_unsigned,
            allow_skipped=args.allow_skipped,
            require_gpu=args.require_gpu,
            expected_skips_path=args.expected_skips,
        )
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
