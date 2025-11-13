"""
Admin FAQ management routes for the Bisq Support API.
"""

import logging
from typing import Optional

from app.core.config import get_settings
from app.core.exceptions import BaseAppException, FAQNotFoundError
from app.core.security import verify_admin_access
from app.models.faq import (
    BulkFAQRequest,
    BulkFAQResponse,
    FAQIdentifiedItem,
    FAQItem,
    FAQListResponse,
)
from app.services.faq_service import FAQService
from fastapi import APIRouter, Depends, status
from fastapi.responses import Response, StreamingResponse

# Setup logging
logger = logging.getLogger(__name__)

# Create main admin router with authentication dependencies for protected routes
router = APIRouter(
    prefix="/admin",
    tags=["Admin FAQs"],
    dependencies=[Depends(verify_admin_access)],
    responses={
        401: {"description": "Unauthorized - Invalid or missing API key"},
        403: {"description": "Forbidden - Insufficient permissions"},
    },
)

# Initialize settings and services
settings = get_settings()
faq_service = FAQService(settings=settings)


@router.get("/faqs", response_model=FAQListResponse)
async def get_all_faqs_for_admin_route(
    page: int = 1,
    page_size: int = 10,
    search_text: Optional[str] = None,
    categories: Optional[str] = None,  # Comma-separated list
    source: Optional[str] = None,
    verified: Optional[bool] = None,  # Filter by verification status
    bisq_version: Optional[str] = None,  # Filter by Bisq version
    verified_from: Optional[
        str
    ] = None,  # ISO 8601 date string for start of verified_at range
    verified_to: Optional[
        str
    ] = None,  # ISO 8601 date string for end of verified_at range
):
    """Get FAQs for the admin interface with pagination and filtering support.

    Date filtering example:
    - verified_from=2024-01-01T00:00:00Z
    - verified_to=2024-12-31T23:59:59Z
    """
    logger.info(
        f"Admin request to fetch FAQs: page={page}, page_size={page_size}, search_text={search_text}, categories={categories}, source={source}, verified={verified}, bisq_version={bisq_version}, verified_from={verified_from}, verified_to={verified_to}"
    )

    try:
        # Parse comma-separated categories
        categories_list = (
            [cat.strip() for cat in categories.split(",")] if categories else None
        )

        result = faq_service.get_faqs_paginated(
            page=page,
            page_size=page_size,
            search_text=search_text,
            categories=categories_list,
            source=source,
            verified=verified,
            bisq_version=bisq_version,
            verified_from=verified_from,
            verified_to=verified_to,
        )
        return result
    except Exception as e:
        logger.error(f"Failed to fetch FAQs: {e}", exc_info=True)
        raise BaseAppException(
            detail="Failed to fetch FAQs",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="FAQ_FETCH_FAILED",
        ) from e


@router.post("/faqs", response_model=FAQIdentifiedItem, status_code=201)
async def add_new_faq_route(faq_item: FAQItem):
    """Add a new FAQ."""
    logger.info(f"Admin request to add new FAQ: {faq_item.question[:30]}...")
    try:
        new_faq = faq_service.add_faq(faq_item)
        return new_faq
    except Exception as e:
        logger.error(f"Failed to add FAQ: {e}", exc_info=True)
        raise BaseAppException(
            detail="Failed to add FAQ",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="FAQ_ADD_FAILED",
        ) from e


@router.put("/faqs/{faq_id}", response_model=FAQIdentifiedItem)
async def update_existing_faq_route(faq_id: str, faq_item_update: FAQItem):
    """Update an existing FAQ by its ID."""
    logger.info(f"Admin request to update FAQ with id: {faq_id}")
    updated_faq = faq_service.update_faq(faq_id, faq_item_update)
    if not updated_faq:
        raise FAQNotFoundError(faq_id)
    return updated_faq


@router.patch("/faqs/{faq_id}/verify", response_model=FAQIdentifiedItem)
async def verify_faq_route(faq_id: str):
    """Verify an FAQ (one-way operation - cannot be undone through API).

    Args:
        faq_id: The ID of the FAQ to verify

    Returns:
        The updated FAQ with verified status set to True
    """
    logger.info(f"Admin request to verify FAQ {faq_id}")

    def _validate_faq_exists(faq_id: str, faq_obj) -> None:
        """Helper to validate FAQ exists and raise error if not."""
        if not faq_obj:
            raise FAQNotFoundError(faq_id)

    try:
        # Get the current FAQ
        all_faqs = faq_service.get_all_faqs()
        current_faq = next((faq for faq in all_faqs if faq.id == faq_id), None)
        _validate_faq_exists(faq_id, current_faq)

        # Update only the verification status to True
        faq_item = FAQItem(**current_faq.model_dump(exclude={"id"}, exclude_none=False))
        updated_faq = faq_service.update_faq(
            faq_id, faq_item.model_copy(update={"verified": True}, deep=False)
        )
        _validate_faq_exists(faq_id, updated_faq)

        logger.info(f"Successfully verified FAQ {faq_id}")
    except FAQNotFoundError:
        raise
    except Exception as e:
        logger.error(f"Failed to verify FAQ: {e}", exc_info=True)
        raise BaseAppException(
            detail="Failed to verify FAQ",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="FAQ_VERIFY_FAILED",
        ) from e
    else:
        return updated_faq


@router.delete("/faqs/{faq_id}", status_code=204)
async def delete_existing_faq_route(faq_id: str):
    """Delete an existing FAQ by its ID."""
    logger.info(f"Admin request to delete FAQ with id: {faq_id}")
    success = faq_service.delete_faq(faq_id)
    if not success:
        raise FAQNotFoundError(faq_id)
    return Response(status_code=204)


@router.post("/faqs/bulk-delete", response_model=BulkFAQResponse)
async def bulk_delete_faqs_route(request: BulkFAQRequest):
    """
    Delete multiple FAQs in a single operation with optimized vector store rebuild.

    This endpoint deletes multiple FAQs and triggers the vector store rebuild only once
    after all deletions complete, providing significant performance improvement over
    individual delete operations.

    Args:
        request: BulkFAQRequest containing list of FAQ IDs to delete

    Returns:
        BulkFAQResponse with success/failure counts and details
    """
    logger.info(f"Bulk delete request for {len(request.faq_ids)} FAQs")

    try:
        success_count, failed_count, failed_ids = faq_service.bulk_delete_faqs(
            request.faq_ids
        )

        message = f"Successfully deleted {success_count} FAQ(s)"
        if failed_count > 0:
            message += f", {failed_count} failed"

        logger.info(
            f"Bulk delete completed: {success_count} succeeded, {failed_count} failed"
        )

        return BulkFAQResponse(
            success_count=success_count,
            failed_count=failed_count,
            failed_ids=failed_ids,
            message=message,
        )
    except Exception as e:
        logger.error(f"Bulk delete operation failed: {e}", exc_info=True)
        raise BaseAppException(
            detail="Bulk delete operation failed",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="BULK_DELETE_FAILED",
        ) from e


@router.get("/faqs/stats")
async def get_faq_stats(
    verified_from: Optional[str] = None,  # ISO 8601 date string
    verified_to: Optional[str] = None,  # ISO 8601 date string
    categories: Optional[str] = None,  # Comma-separated list
    source: Optional[str] = None,
    bisq_version: Optional[str] = None,
):
    """Get FAQ statistics including counts by verification date range.

    This endpoint provides aggregate statistics about FAQs, useful for reporting.
    Date filtering allows admins to answer questions like "How many FAQs were
    verified between date X and date Y?"

    Example queries:
    - /admin/faqs/stats?verified_from=2024-01-01T00:00:00Z&verified_to=2024-12-31T23:59:59Z
    - /admin/faqs/stats?verified_from=2024-01-01T00:00:00Z&categories=Trading,Mediation
    """
    logger.info(
        f"Admin request for FAQ stats: verified_from={verified_from}, verified_to={verified_to}, categories={categories}, source={source}, bisq_version={bisq_version}"
    )

    try:
        # Parse comma-separated categories
        categories_list = (
            [cat.strip() for cat in categories.split(",")] if categories else None
        )

        # Get all FAQs matching the filters without pagination
        # Use get_filtered_faqs() instead of paginated method for aggregation
        faqs = faq_service.get_filtered_faqs(
            categories=categories_list,
            source=source,
            verified=True,  # Only count verified FAQs
            bisq_version=bisq_version,
            verified_from=verified_from,
            verified_to=verified_to,
        )

        # Calculate additional statistics
        total_verified = len(faqs)

        # Get breakdown by category
        category_breakdown: dict[str, int] = {}
        for faq in faqs:
            cat = faq.category or "Uncategorized"
            category_breakdown[cat] = category_breakdown.get(cat, 0) + 1

        # Get breakdown by source
        source_breakdown: dict[str, int] = {}
        for faq in faqs:
            src = faq.source or "Unknown"
            source_breakdown[src] = source_breakdown.get(src, 0) + 1

        stats = {
            "total_verified_count": total_verified,
            "date_range": {
                "from": verified_from,
                "to": verified_to,
            },
            "filters": {
                "categories": categories_list,
                "source": source,
                "bisq_version": bisq_version,
            },
            "breakdown_by_category": category_breakdown,
            "breakdown_by_source": source_breakdown,
        }

        return stats
    except Exception as e:
        logger.error(f"Failed to fetch FAQ stats: {e}", exc_info=True)
        raise BaseAppException(
            detail="Failed to fetch FAQ statistics",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="FAQ_STATS_FAILED",
        ) from e


@router.post("/faqs/bulk-verify", response_model=BulkFAQResponse)
async def bulk_verify_faqs_route(request: BulkFAQRequest):
    """
    Verify multiple FAQs in a single operation (metadata-only, no vector store rebuild).

    This endpoint performs bulk verification by updating FAQ metadata (verified status)
    without triggering vector store rebuilds. Verification is metadata-only and does not
    affect the indexed content, so no rebuild is necessary.

    Args:
        request: BulkFAQRequest containing list of FAQ IDs to verify

    Returns:
        BulkFAQResponse with success/failure counts and details
    """
    logger.info(f"Bulk verify request for {len(request.faq_ids)} FAQs")

    try:
        success_count, failed_count, failed_ids = faq_service.bulk_verify_faqs(
            request.faq_ids
        )

        message = f"Successfully verified {success_count} FAQ(s)"
        if failed_count > 0:
            message += f", {failed_count} failed"

        logger.info(
            f"Bulk verify completed: {success_count} succeeded, {failed_count} failed"
        )

        return BulkFAQResponse(
            success_count=success_count,
            failed_count=failed_count,
            failed_ids=failed_ids,
            message=message,
        )
    except Exception as e:
        logger.error(f"Bulk verify operation failed: {e}", exc_info=True)
        raise BaseAppException(
            detail="Bulk verify operation failed",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code="BULK_VERIFY_FAILED",
        ) from e


@router.get("/faqs/export")
async def export_faqs_to_csv(
    search_text: Optional[str] = None,
    categories: Optional[str] = None,
    source: Optional[str] = None,
    verified: Optional[bool] = None,
    bisq_version: Optional[str] = None,
    verified_from: Optional[str] = None,
    verified_to: Optional[str] = None,
):
    """Stream FAQs as CSV file with memory-efficient pagination.

    This endpoint streams CSV data in chunks to avoid memory issues with large datasets.
    The browser receives the file progressively without holding all data in memory.

    Date filtering example:
    - verified_from=2024-01-01T00:00:00Z
    - verified_to=2024-12-31T23:59:59Z
    """
    logger.info(
        f"CSV export request: search_text={search_text}, categories={categories}, "
        f"source={source}, verified={verified}, bisq_version={bisq_version}, "
        f"verified_from={verified_from}, verified_to={verified_to}"
    )

    def sanitize_csv_field(value: Optional[str]) -> str:
        """Escape and quote CSV field values."""
        if value is None:
            return '""'
        # Replace double quotes with two double quotes (CSV escaping)
        safe = str(value).replace('"', '""')
        return f'"{safe}"'

    def format_timestamp(timestamp: Optional[str]) -> str:
        """Format timestamp for CSV output."""
        if timestamp is None:
            return ""
        return str(timestamp)

    def generate_csv_rows():
        """Generator that yields CSV rows in chunks."""
        try:
            # Parse comma-separated categories
            categories_list = (
                [cat.strip() for cat in categories.split(",")] if categories else None
            )

            # Write CSV header
            header = (
                "Question,Answer,Category,Source,Verified,Bisq Version,"
                "Created At,Updated At,Verified At\n"
            )
            yield header.encode("utf-8")

            # Get all filtered FAQs (uses memory-efficient method without pagination)
            faqs = faq_service.get_filtered_faqs(
                search_text=search_text,
                categories=categories_list,
                source=source,
                verified=verified,
                bisq_version=bisq_version,
                verified_from=verified_from,
                verified_to=verified_to,
            )

            # Stream each FAQ as CSV row
            for faq in faqs:
                row = ",".join(
                    [
                        sanitize_csv_field(faq.question),
                        sanitize_csv_field(faq.answer),
                        sanitize_csv_field(faq.category),
                        sanitize_csv_field(faq.source),
                        sanitize_csv_field("Yes" if faq.verified else "No"),
                        sanitize_csv_field(faq.bisq_version),
                        sanitize_csv_field(format_timestamp(faq.created_at)),
                        sanitize_csv_field(format_timestamp(faq.updated_at)),
                        sanitize_csv_field(format_timestamp(faq.verified_at)),
                    ]
                )
                yield (row + "\n").encode("utf-8")

            logger.info(f"CSV export completed: {len(faqs)} FAQs exported")

        except Exception as e:
            logger.error(f"CSV export failed: {e}", exc_info=True)
            error_msg = "An internal error occurred while exporting FAQs.\n"
            yield error_msg.encode("utf-8")

    # Generate filename with date range if applicable
    filename_parts = ["faqs_export"]
    if verified_from or verified_to:
        date_range = f"{verified_from or 'start'}_to_{verified_to or 'end'}"
        filename_parts.append(date_range)
    filename = "_".join(filename_parts) + ".csv"

    # Return streaming response with proper headers
    return StreamingResponse(
        generate_csv_rows(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-cache",
        },
    )
