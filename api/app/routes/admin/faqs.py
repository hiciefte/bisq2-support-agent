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
from fastapi.responses import Response

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
):
    """Get FAQs for the admin interface with pagination and filtering support."""
    logger.info(
        f"Admin request to fetch FAQs: page={page}, page_size={page_size}, search_text={search_text}, categories={categories}, source={source}"
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


@router.post("/faqs/bulk-verify", response_model=BulkFAQResponse)
async def bulk_verify_faqs_route(request: BulkFAQRequest):
    """
    Verify multiple FAQs in a single operation with optimized vector store rebuild.

    This endpoint verifies multiple FAQs and triggers the vector store rebuild only once
    after all verifications complete, providing significant performance improvement over
    individual verify operations.

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
