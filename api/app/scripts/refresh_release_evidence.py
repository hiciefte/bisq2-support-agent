"""Prepare recent official release snapshots; never install or call an LLM.

Checkouts must be dedicated, clean source mirrors: this command checks out the
selected official tags there. Output must be a new directory outside them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.services.rag.code_evidence import CodeEvidenceLoader, release_version
from app.services.rag.code_evidence_extractor import (
    CodeEvidenceExtractor,
    CodeEvidenceFreshnessChecker,
    _git,
    write_code_evidence_jsonl,
)
from app.services.rag.release_notes import ReleaseNote, ReleaseNotesLoader

REPOSITORIES = ("bisq", "bisq2")
REQUIRED_BISQ1 = {
    "trade-phases",
    "deposit-confirmation-state",
    "offer-reservation-state",
    "wallet-spv-replay",
    "mediation-acceptance-payout",
}
REQUIRED_BISQ2 = {
    "payment-states",
    "trade-amount-cap",
    "sell-offer-score",
    "tor-bootstrap-timeout",
}
BISQ1_SYMBOL = "SignMediatedPayoutTx.checkMediatedPayoutAddresses"


def stable_releases(rows: list[dict], repo: str) -> list[dict]:
    releases = []
    for row in rows:
        if row.get("draft") is not False or row.get("prerelease") is not False:
            continue
        try:
            version = release_version(row["tag_name"])
        except (KeyError, ValueError, TypeError):
            continue
        if "-" in version or not version.startswith("1." if repo == "bisq" else "2."):
            continue
        if (
            row.get("html_url")
            != f"https://github.com/bisq-network/{repo}/releases/tag/{row['tag_name']}"
        ):
            raise ValueError("Unexpected official release URL")
        releases.append(row)
    releases.sort(
        key=lambda row: tuple(map(int, release_version(row["tag_name"]).split("."))),
        reverse=True,
    )
    selected = releases[:3]
    if len(selected) != 3 or len({row["tag_name"] for row in selected}) != 3:
        raise ValueError("Need three distinct stable official releases")
    return selected


def fetch_releases(repo: str) -> list[dict]:
    if repo not in REPOSITORIES:
        raise ValueError("Unsupported repository")
    request = urllib.request.Request(
        f"https://api.github.com/repos/bisq-network/{repo}/releases?per_page=10",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "bisq-support-release-evidence",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ValueError("Official release discovery response too large")
    return stable_releases(json.loads(payload), repo)


def prepare(args: argparse.Namespace) -> dict:
    output = args.output.resolve()
    if output.exists():
        raise ValueError(
            "Output must be a new directory; do not overwrite prior evidence"
        )
    checkouts = {"bisq": args.bisq_checkout, "bisq2": args.bisq2_checkout}
    for checkout in checkouts.values():
        if output.is_relative_to(checkout.resolve()):
            raise ValueError("Output must be outside source checkouts")
        if _git(checkout, "status", "--porcelain", "--untracked-files=all"):
            raise ValueError("Use dedicated clean source checkouts")
    all_code = (
        CodeEvidenceLoader(args.previous_code).load() if args.previous_code else []
    )
    all_notes = (
        ReleaseNotesLoader(args.previous_notes).load() if args.previous_notes else []
    )
    coverage = []
    release_payloads = {}
    for repo in REPOSITORIES:
        # Optional cached discovery is for repeatable offline review of already
        # fetched official responses, never a substitute for online verification.
        releases = (
            stable_releases(
                json.loads((args.discovery_cache / f"{repo}.json").read_text()), repo
            )
            if args.discovery_cache
            else fetch_releases(repo)
        )
        release_payloads[repo] = releases
        checkout = checkouts[repo]
        remote = f"https://github.com/bisq-network/{repo}.git"
        for release in releases:
            tag = release["tag_name"]
            if not args.offline:
                refs = subprocess.check_output(
                    [
                        "git",
                        "ls-remote",
                        remote,
                        f"refs/tags/{tag}",
                        f"refs/tags/{tag}^{{}}",
                    ],
                    text=True,
                    timeout=60,
                )
                hashes = {
                    ref: sha
                    for sha, ref in (line.split() for line in refs.splitlines())
                }
                remote_commit = hashes.get(f"refs/tags/{tag}^{{}}") or hashes.get(
                    f"refs/tags/{tag}"
                )
                if not remote_commit:
                    raise ValueError("Official release tag unavailable")
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(checkout),
                        "fetch",
                        "--no-tags",
                        remote,
                        f"refs/tags/{tag}:refs/tags/{tag}",
                    ],
                    check=True,
                    capture_output=True,
                    timeout=180,
                )
            _git(checkout, "checkout", "--detach", tag)
            commit = _git(checkout, "rev-parse", "HEAD")
            if not args.offline and commit != remote_commit:
                raise ValueError("Official tag commit mismatch")
            extractor = CodeEvidenceExtractor(
                repo_path=checkout,
                repo=repo,
                commit=commit,
                release_tag=tag,
                freshness_class="release_bound",
            )
            generated = extractor.extract()
            if repo == "bisq":
                records = [
                    record
                    for record in generated
                    if record.symbol == BISQ1_SYMBOL
                    or record.id.split(":")[-1] in REQUIRED_BISQ1
                ]
                if len(records) != 1 + len(REQUIRED_BISQ1):
                    raise ValueError(
                        "Required Bisq 1 mediated-payout source coverage changed; review before refreshing"
                    )
                missing = []
            else:
                names = {
                    row["name"]
                    for row in json.loads(
                        Path(__file__)
                        .parents[1]
                        .joinpath("services/rag/code_evidence_recipes.json")
                        .read_text()
                    )
                    if row["repo"] == repo
                }
                records = [
                    record for record in generated if record.id.split(":")[-1] in names
                ]
                available = {record.id.split(":")[-1] for record in records}
                if REQUIRED_BISQ2 - available:
                    raise ValueError(
                        "Required Bisq 2 source coverage changed: "
                        + ",".join(sorted(REQUIRED_BISQ2 - available))
                    )
                missing = sorted(names - available)
            report = CodeEvidenceFreshnessChecker(checkout).check(records)
            if report.stale:
                raise ValueError("Source freshness failed")
            note = ReleaseNote.from_dict(
                {
                    "repo": repo,
                    "tag": tag,
                    "commit": commit,
                    "published_at": release["published_at"],
                    "url": release["html_url"],
                    "body": release["body"],
                    "body_sha256": hashlib.sha256(release["body"].encode()).hexdigest(),
                }
            )
            for existing in [*all_code, *all_notes]:
                existing_tag = getattr(existing, "release_tag", None) or getattr(
                    existing, "tag", None
                )
                if (
                    existing.repo == repo
                    and existing_tag == tag
                    and existing.commit != commit
                ):
                    raise ValueError("Previously retained release commit changed")
            all_code = [
                record
                for record in all_code
                if not (record.repo == repo and record.release_tag == tag)
            ] + records
            all_notes = [
                record
                for record in all_notes
                if not (record.repo == repo and record.tag == tag)
            ] + [note]
            coverage.append(
                {
                    "repo": repo,
                    "tag": tag,
                    "commit": commit,
                    "published_at": note.published_at,
                    "release_url": note.url,
                    "code_records": len(records),
                    "missing_optional_recipes": missing,
                    "notes_sha256": note.body_sha256,
                }
            )
    output.mkdir(parents=True)
    write_code_evidence_jsonl(all_code, output / "code_evidence.jsonl")
    (output / "release_notes.jsonl").write_text(
        "".join(json.dumps(note.to_dict(), sort_keys=True) + "\n" for note in all_notes)
    )
    (output / "official-release-responses.json").write_text(
        json.dumps(release_payloads, indent=2) + "\n"
    )
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "remote_tags_verified_this_run": not args.offline,
        "coverage": coverage,
        "code_records": len(all_code),
        "release_notes": len(all_notes),
        "files": {
            name: hashlib.sha256((output / name).read_bytes()).hexdigest()
            for name in (
                "code_evidence.jsonl",
                "release_notes.jsonl",
                "official-release-responses.json",
            )
        },
        "limitations": [
            "Code coverage is curated, not comprehensive.",
            "Unchanged excerpts preserve reviewed claims; changed optional spans are omitted.",
            "Unknown installed version does not establish release applicability.",
            "No production installation, scheduler, or provider call is performed.",
        ],
    }
    (output / "coverage.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bisq-checkout", type=Path, required=True)
    parser.add_argument("--bisq2-checkout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous-code", type=Path)
    parser.add_argument("--previous-notes", type=Path)
    parser.add_argument("--discovery-cache", type=Path)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Review already verified local tags; manifest explicitly marks remote verification absent",
    )
    args = parser.parse_args()
    if args.offline and not args.discovery_cache:
        parser.error("Offline review requires an explicit discovery cache")
    print(json.dumps(prepare(args), indent=2))


if __name__ == "__main__":
    main()
