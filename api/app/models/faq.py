from typing import Optional, List

from pydantic import BaseModel


class FAQItem(BaseModel):
    question: str
    answer: str
    category: Optional[str] = "General"
    source: Optional[str] = "Manual"  # Default for manually added/edited


class FAQIdentifiedItem(FAQItem):
    id: str  # A temporary ID, like index or hash, for frontend to identify


class FAQUpdateRequest(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = None
    source: Optional[str] = None


class FAQListResponse(BaseModel):
    faqs: List[FAQIdentifiedItem]
    total_count: int
    page: int
    page_size: int
    total_pages: int
