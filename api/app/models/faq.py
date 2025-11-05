from typing import List, Optional

from pydantic import BaseModel, Field


class FAQItem(BaseModel):
    question: str
    answer: str
    category: Optional[str] = "General"
    source: Optional[str] = "Manual"  # Default for manually added/edited
    verified: Optional[bool] = False  # Whether FAQ has been verified by admin


class FAQIdentifiedItem(FAQItem):
    id: str  # A temporary ID, like index or hash, for frontend to identify


class FAQUpdateRequest(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = None
    source: Optional[str] = None
    verified: Optional[bool] = None


class FAQListResponse(BaseModel):
    faqs: List[FAQIdentifiedItem]
    total_count: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_pages: int = Field(ge=1)


class BulkFAQRequest(BaseModel):
    """Request model for bulk FAQ operations."""

    faq_ids: List[str] = Field(
        ..., min_length=1, description="List of FAQ IDs to process"
    )


class BulkFAQResponse(BaseModel):
    """Response model for bulk FAQ operations."""

    success_count: int = Field(
        ge=0, description="Number of successfully processed FAQs"
    )
    failed_count: int = Field(ge=0, description="Number of failed operations")
    failed_ids: List[str] = Field(
        default_factory=list, description="IDs of failed operations"
    )
    message: str = Field(..., description="Summary message")
