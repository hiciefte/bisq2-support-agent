"""Public FAQ API endpoints (no authentication required)."""

import logging
from typing import Optional

from app.services.public_faq_service import PublicFAQService
from fastapi import APIRouter, HTTPException, Query, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public/faqs", tags=["Public FAQs"])


def get_public_faq_service(request: Request) -> PublicFAQService:
    """Get PublicFAQService from request state."""
    if not hasattr(request.app.state, "public_faq_service"):
        raise HTTPException(status_code=503, detail="Public FAQ service not available")
    return request.app.state.public_faq_service


@router.get("")
async def list_faqs(
    request: Request,
    response: Response,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=50, description="Items per page"),
    search: Optional[str] = Query(None, max_length=200, description="Search query"),
    category: Optional[str] = Query(None, description="Filter by category"),
):
    """
    List FAQs with pagination and filtering.

    - **page**: Page number (default: 1)
    - **limit**: Items per page (default: 20, max: 50)
    - **search**: Full-text search across question/answer
    - **category**: Filter by category name
    """
    public_faq_service = get_public_faq_service(request)

    result = public_faq_service.get_faqs_paginated(
        page=page,
        limit=limit,
        search=search or "",
        category=category or "",
    )

    # Set cache headers
    response.headers["Cache-Control"] = "public, max-age=900"  # 15 minutes

    return result


@router.get("/categories")
async def list_categories(
    request: Request,
    response: Response,
):
    """List all FAQ categories with counts."""
    public_faq_service = get_public_faq_service(request)
    categories = public_faq_service.get_categories()

    # Longer cache for categories (change less frequently)
    response.headers["Cache-Control"] = "public, max-age=1800"  # 30 minutes

    return {"categories": categories}


@router.get("/{slug}")
async def get_faq(
    slug: str,
    request: Request,
    response: Response,
):
    """
    Get single FAQ by slug.

    - **slug**: Human-readable FAQ identifier (e.g., 'how-do-i-trade-abc12345')
    """
    public_faq_service = get_public_faq_service(request)
    faq = public_faq_service.get_faq_by_slug(slug)

    if not faq:
        raise HTTPException(status_code=404, detail="FAQ not found")

    # Set cache headers with ETag
    response.headers["Cache-Control"] = "public, max-age=900"
    if faq.get("updated_at"):
        response.headers["ETag"] = f'"{faq["updated_at"]}"'

    return faq
