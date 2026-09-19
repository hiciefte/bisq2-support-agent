import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from app.services.rag.code_evidence import CodeEvidenceLoader
from app.services.rag.code_evidence_extractor import (
    CodeEvidenceExtractor,
    CodeEvidenceFreshnessChecker,
    write_code_evidence_jsonl,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _git(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def _commit_source(path: Path) -> str:
    _git(path, "init", "-q")
    _git(path, "add", ".")
    _git(
        path,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "Fixture",
    )
    return _git(path, "rev-parse", "HEAD")


def test_extractor_generates_valid_records_from_supported_source_types(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "bisq-easy/src/main/java/bisq/bisq_easy/OfferResource.java",
        """
        package bisq.bisq_easy;

        import jakarta.ws.rs.GET;
        import jakarta.ws.rs.Path;

        @Path("/offers")
        public class OfferResource {
            public static final int MAX_SELL_OFFERS = 3;

            @GET
            @Path("/{id}")
            public Response getOffer() {
                return null;
            }
        }
        """,
    )
    _write(
        tmp_path / "trade/src/main/java/bisq/trade/bisq_easy/TradeState.java",
        """
        package bisq.trade.bisq_easy;

        public enum TradeState {
            CREATED,
            PAYMENT_SENT,
            COMPLETED;
        }
        """,
    )
    _write(
        tmp_path / "apps/api-app/src/main/resources/api_app.conf",
        """
        api.timeout.seconds = 30
        api.password = hunter2
        """,
    )
    _write(
        tmp_path / "trade/src/main/java/bisq/trade/bisq_easy/specification.md",
        """
        # Bisq Easy trade protocol

        ## Payment started

        Buyer confirms payment before the seller releases bitcoin.
        """,
    )

    records = CodeEvidenceExtractor(
        repo_path=tmp_path,
        repo="bisq2",
        commit=_commit_source(tmp_path),
    ).extract()

    symbols = {record.symbol: record for record in records}
    assert "OfferResource.MAX_SELL_OFFERS" in symbols
    assert "MAX_SELL_OFFERS" in symbols["OfferResource.MAX_SELL_OFFERS"].claim
    assert "3" in symbols["OfferResource.MAX_SELL_OFFERS"].claim

    assert "OfferResource.getOffer" in symbols
    assert "GET /offers/{id}" in symbols["OfferResource.getOffer"].claim

    assert "TradeState" in symbols
    assert "PAYMENT_SENT" in symbols["TradeState"].claim

    assert "api.timeout.seconds" in symbols
    assert "30" in symbols["api.timeout.seconds"].claim

    assert "specification:Payment started" in symbols
    assert "Buyer confirms payment" in symbols["specification:Payment started"].claim

    assert all(record.repo == "bisq2" for record in records)
    assert all(
        record.commit == _git(tmp_path, "rev-parse", "HEAD") for record in records
    )
    assert all(record.audience == "staff_only" for record in records)
    assert symbols["OfferResource.MAX_SELL_OFFERS"].protocol == "bisq_easy"
    assert symbols["OfferResource.getOffer"].protocol == "bisq_easy"
    assert symbols["TradeState"].protocol == "bisq_easy"
    assert symbols["api.timeout.seconds"].protocol == "all"
    assert all(
        record.source_refs[0].startswith(f"code:bisq2@{record.commit}:")
        for record in records
    )
    assert not any("password" in record.claim.lower() for record in records)
    assert not any("hunter2" in record.claim.lower() for record in records)


def test_extractor_generates_staff_only_records_for_user_visible_exceptions(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "bisq-easy/src/main/java/bisq/bisq_easy/OfferValidator.java",
        """
        package bisq.bisq_easy;

        public class OfferValidator {
            public void validateAmount(long amount) {
                if (amount <= 0) {
                    throw new IllegalArgumentException("Amount must be positive.");
                }
                throw new IllegalStateException("API token=abcd1234 was invalid.");
            }
        }
        """,
    )
    _write(
        tmp_path / "api/app/routes/admin/offers.py",
        """
        from fastapi import HTTPException

        def read_offer(offer_id: str):
            raise HTTPException(status_code=404, detail="Offer not found")
        """,
    )
    _write(
        tmp_path / "api/tests/routes/test_offers.py",
        """
        from fastapi import HTTPException

        def fake_test_route():
            raise HTTPException(status_code=418, detail="Test-only error")
        """,
    )

    records = CodeEvidenceExtractor(
        repo_path=tmp_path,
        repo="mixed",
        commit=_commit_source(tmp_path),
    ).extract()

    symbols = {record.symbol: record for record in records}
    assert "OfferValidator.IllegalArgumentException" in symbols
    java_record = symbols["OfferValidator.IllegalArgumentException"]
    assert java_record.protocol == "bisq_easy"
    assert java_record.risk_level == "high"
    assert java_record.audience == "staff_only"
    assert "Amount must be positive." in java_record.claim
    assert "exception message" in java_record.support_use

    redacted = symbols["OfferValidator.IllegalStateException"]
    assert "token" not in redacted.claim.lower()
    assert "abcd1234" not in redacted.claim
    assert "[REDACTED]" in redacted.claim

    assert "HTTPException.404" in symbols
    python_record = symbols["HTTPException.404"]
    assert python_record.protocol == "all"
    assert python_record.risk_level == "high"
    assert "Offer not found" in python_record.claim
    assert not any("Test-only error" in record.claim for record in records)


def test_write_code_evidence_jsonl_round_trips_through_existing_loader(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "offer/src/main/java/bisq/offer/OfferLimits.java",
        """
        package bisq.offer;

        public class OfferLimits {
            public static final long OFFER_TTL_SECONDS = 600;
        }
        """,
    )

    records = CodeEvidenceExtractor(
        repo_path=tmp_path,
        repo="bisq2",
        commit=_commit_source(tmp_path),
    ).extract()
    output_path = tmp_path / "code_knowledge/code_evidence.jsonl"

    write_code_evidence_jsonl(records, output_path)

    loaded = CodeEvidenceLoader(output_path).load()
    assert [record.id for record in loaded] == [record.id for record in records]
    assert loaded[0].symbol == "OfferLimits.OFFER_TTL_SECONDS"

    raw_rows = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    ]
    assert raw_rows[0]["type"] == "code_fact"


def test_extractor_record_ids_include_path_to_avoid_cross_file_collisions(
    tmp_path: Path,
) -> None:
    for module in ("module-a", "module-b"):
        _write(
            tmp_path / module / "src/main/java/bisq/Config.java",
            """
            package bisq;

            public class Config {
                public static final int LIMIT = 3;
            }
            """,
        )

    records = CodeEvidenceExtractor(
        repo_path=tmp_path,
        repo="bisq2",
        commit=_commit_source(tmp_path),
    ).extract()
    limit_records = [record for record in records if record.symbol == "Config.LIMIT"]

    assert len(limit_records) == 2
    assert len({record.id for record in limit_records}) == 2
    assert {record.path.split("/", 1)[0] for record in limit_records} == {
        "module-a",
        "module-b",
    }


def test_extractor_excludes_directories_only_relative_to_repo_root(
    tmp_path: Path,
) -> None:
    repo_path = tmp_path / "build" / "repo"
    _write(
        repo_path / "src/main/java/bisq/RuntimeConfig.java",
        """
        package bisq;

        public class RuntimeConfig {
            public static final int LIMIT = 3;
        }
        """,
    )

    records = CodeEvidenceExtractor(
        repo_path=repo_path,
        repo="bisq2",
        commit=_commit_source(repo_path),
    ).extract()

    assert any(record.symbol == "RuntimeConfig.LIMIT" for record in records)


def test_freshness_checker_reports_missing_files_and_invalid_line_ranges(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "bisq-easy/src/main/java/bisq/bisq_easy/Limits.java",
        """
        package bisq.bisq_easy;

        public class Limits {
            public static final int MAX_TRADES = 2;
        }
        """,
    )
    records = CodeEvidenceExtractor(
        repo_path=tmp_path,
        repo="bisq2",
        commit=_commit_source(tmp_path),
    ).extract()
    valid_record = records[0]
    missing_file_record = type(valid_record)(
        **{
            **valid_record.to_dict(),
            "id": "missing-file",
            "path": "bisq-easy/src/main/java/bisq/bisq_easy/Missing.java",
            "source_refs": [
                f"code:bisq2@{valid_record.commit}:"
                "bisq-easy/src/main/java/bisq/bisq_easy/Missing.java:1-1"
            ],
        }
    )
    bad_line_record = type(valid_record)(
        **{
            **valid_record.to_dict(),
            "id": "bad-line",
            "line_start": 99,
            "line_end": 101,
            "source_refs": [
                f"code:bisq2@{valid_record.commit}:"
                "bisq-easy/src/main/java/bisq/bisq_easy/Limits.java:99-101"
            ],
        }
    )

    report = CodeEvidenceFreshnessChecker(tmp_path).check(
        [valid_record, missing_file_record, bad_line_record]
    )

    assert report.total == 3
    assert report.valid == 1
    assert report.stale == 2
    assert {failure["reason"] for failure in report.failures} == {
        "missing_file",
        "line_range_out_of_bounds",
    }


@pytest.mark.parametrize("change", ["tracked", "untracked", "assume_unchanged"])
def test_extraction_and_freshness_reject_changed_source(
    tmp_path: Path, change: str
) -> None:
    source = tmp_path / "Limits.java"
    _write(source, "public class Limits { public static final int MAX_TRADES = 2; }")
    commit = _commit_source(tmp_path)
    extractor = CodeEvidenceExtractor(repo_path=tmp_path, repo="bisq2", commit=commit)
    records = extractor.extract()
    if change == "untracked":
        _write(tmp_path / "Extra.java", "public class Extra {}")
    else:
        if change == "assume_unchanged":
            _git(tmp_path, "update-index", "--assume-unchanged", "Limits.java")
        source.write_text(source.read_text().replace("= 2", "= 9"))
    with pytest.raises(ValueError, match="dirty|content"):
        extractor.extract()
    assert CodeEvidenceFreshnessChecker(tmp_path).check(records).stale == len(records)
    if change == "assume_unchanged":
        # Updating the evidence hash cannot disguise bytes absent from the commit.
        forged = replace(
            records[0], source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()
        )
        assert CodeEvidenceFreshnessChecker(tmp_path).check([forged]).stale == 1


def test_wrong_commit_and_wrong_release_identity_are_rejected(tmp_path: Path) -> None:
    _write(
        tmp_path / "Limits.java",
        "public class Limits { public static final int MAX_TRADES = 2; }",
    )
    commit = _commit_source(tmp_path)
    _git(tmp_path, "tag", "v2.1.13")
    records = CodeEvidenceExtractor(
        repo_path=tmp_path,
        repo="bisq2",
        commit=commit,
        release_tag="v2.1.13",
        freshness_class="release_bound",
    ).extract()
    assert records[0].applies_to_versions == ["2.1.13"]
    assert records[0].release_tag == "v2.1.13"
    assert len(records[0].source_sha256) == 64
    assert CodeEvidenceFreshnessChecker(tmp_path).check(records).stale == 0
    with pytest.raises(ValueError, match="HEAD"):
        CodeEvidenceExtractor(
            repo_path=tmp_path, repo="bisq2", commit="0" * 40
        ).extract()
    assert (
        CodeEvidenceFreshnessChecker(tmp_path)
        .check([replace(records[0], commit="0" * 40)])
        .stale
        == 1
    )
    _write(tmp_path / "Other.java", "public class Other {}")
    new_commit = _commit_source(tmp_path)
    with pytest.raises(ValueError, match="Release tag"):
        CodeEvidenceExtractor(
            repo_path=tmp_path, repo="bisq2", commit=new_commit, release_tag="v2.1.13"
        ).extract()
    with pytest.raises(ValueError, match="release tag"):
        CodeEvidenceExtractor(
            repo_path=tmp_path,
            repo="bisq2",
            commit=new_commit,
            freshness_class="release_bound",
        ).extract()


def test_byte_identical_eol_checkout_is_accepted(tmp_path: Path) -> None:
    _write(
        tmp_path / "Limits.java",
        "public class Limits { public static final int MAX_TRADES = 2; }",
    )
    _write(tmp_path / ".gitattributes", "*.bat text eol=crlf")
    _commit_source(tmp_path)
    script = tmp_path / "gradlew.bat"
    script.write_bytes(b"@echo off\r\nexit /b 0\r\n")
    blob = _git(tmp_path, "hash-object", "-w", "--no-filters", "gradlew.bat")
    _git(tmp_path, "update-index", "--add", "--cacheinfo", f"100644,{blob},gradlew.bat")
    _git(
        tmp_path,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "Keep exact release bytes",
    )
    commit = _git(tmp_path, "rev-parse", "HEAD")
    assert _git(tmp_path, "status", "--porcelain") == "M gradlew.bat"
    records = CodeEvidenceExtractor(
        repo_path=tmp_path, repo="bisq2", commit=commit
    ).extract()
    assert records and CodeEvidenceFreshnessChecker(tmp_path).check(records).stale == 0
    script.write_bytes(b"@echo modified\r\n")
    with pytest.raises(ValueError, match="dirty"):
        CodeEvidenceExtractor(repo_path=tmp_path, repo="bisq2", commit=commit).extract()
