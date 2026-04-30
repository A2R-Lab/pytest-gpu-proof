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

    args = parser.parse_args()

    if args.command == "verify":
        from .verify import verify_receipt

        ok = verify_receipt(
            receipt_path=args.receipt,
            policy_path=args.policy,
            repo_root=args.repo,
            github_user_override=args.github_user,
            max_age_days=args.max_age_days,
        )
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
