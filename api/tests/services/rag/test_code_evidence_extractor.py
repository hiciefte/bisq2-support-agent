import json
from pathlib import Path

from app.services.rag.code_evidence import CodeEvidenceLoader
from app.services.rag.code_evidence_extractor import (
    CodeEvidenceExtractor,
    CodeEvidenceFreshnessChecker,
    write_code_evidence_jsonl,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


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
        commit="abc123def456",
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
    assert all(record.commit == "abc123def456" for record in records)
    assert all(record.audience == "staff_only" for record in records)
    assert symbols["OfferResource.MAX_SELL_OFFERS"].protocol == "bisq_easy"
    assert symbols["OfferResource.getOffer"].protocol == "bisq_easy"
    assert symbols["TradeState"].protocol == "bisq_easy"
    assert symbols["api.timeout.seconds"].protocol == "all"
    assert all(
        record.source_refs[0].startswith("code:bisq2@abc123def456:")
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
        commit="abc123",
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
        commit="feedbee",
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
        commit="abc123",
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
        commit="abc123",
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
        commit="abc123",
    ).extract()
    valid_record = records[0]
    missing_file_record = type(valid_record)(
        **{
            **valid_record.to_dict(),
            "id": "missing-file",
            "path": "bisq-easy/src/main/java/bisq/bisq_easy/Missing.java",
            "source_refs": [
                "code:bisq2@abc123:"
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
                "code:bisq2@abc123:"
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
