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
