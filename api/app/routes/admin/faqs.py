"""
Admin FAQ management routes for the Bisq Support API.
"""

import logging
from typing import Optional

from app.core.config import get_settings
from app.core.exceptions import BaseAppException, FAQNotFoundError
from app.core.security import verify_admin_access
from app.models.faq import FAQIdentifiedItem, FAQItem, FAQListResponse
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


@router.delete("/faqs/{faq_id}", status_code=204)
async def delete_existing_faq_route(faq_id: str):
    """Delete an existing FAQ by its ID."""
    logger.info(f"Admin request to delete FAQ with id: {faq_id}")
    success = faq_service.delete_faq(faq_id)
    if not success:
        raise FAQNotFoundError(faq_id)
    return Response(status_code=204)
