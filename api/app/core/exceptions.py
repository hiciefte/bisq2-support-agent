"""
Custom exception hierarchy for the Bisq Support API.

This module defines a standardized exception hierarchy for consistent
error handling across the application.
"""

from typing import Any, Dict, Optional

from fastapi import HTTPException, status


class BaseAppException(HTTPException):
    """Base exception for all application errors."""

    def __init__(
        self,
        detail: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        headers: Optional[Dict[str, Any]] = None,
        error_code: Optional[str] = None,
    ):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.error_code = error_code or self.__class__.__name__


# Authentication Exceptions


class AuthenticationError(BaseAppException):
    """Raised when authentication fails."""

    def __init__(
        self, detail: str = "Authentication failed", error_code: Optional[str] = None
    ):
        super().__init__(
            detail, status.HTTP_401_UNAUTHORIZED, error_code=error_code or "AUTH_ERROR"
        )


class InvalidAPIKeyError(AuthenticationError):
    """Raised when API key is invalid."""

    def __init__(self):
        super().__init__("Invalid API key", error_code="INVALID_API_KEY")


class MissingAPIKeyError(AuthenticationError):
    """Raised when API key is missing."""

    def __init__(self):
        super().__init__(
            "API key is required for this operation", error_code="MISSING_API_KEY"
        )


# Resource Exceptions


class ResourceNotFoundError(BaseAppException):
    """Raised when a resource is not found."""

    def __init__(self, resource_type: str, resource_id: str):
        detail = f"{resource_type} with ID '{resource_id}' not found"
        super().__init__(
            detail, status.HTTP_404_NOT_FOUND, error_code="RESOURCE_NOT_FOUND"
        )


class ResourceAlreadyExistsError(BaseAppException):
    """Raised when attempting to create a duplicate resource."""

    def __init__(self, resource_type: str, identifier: str):
        detail = f"{resource_type} with identifier '{identifier}' already exists"
        super().__init__(detail, status.HTTP_409_CONFLICT, error_code="RESOURCE_EXISTS")


# Data Validation Exceptions


class ValidationError(BaseAppException):
    """Raised when data validation fails."""

    def __init__(self, detail: str, field: Optional[str] = None):
        error_code = (
            f"VALIDATION_ERROR_{field.upper()}" if field else "VALIDATION_ERROR"
        )
        super().__init__(
            detail, status.HTTP_422_UNPROCESSABLE_ENTITY, error_code=error_code
        )


# Storage Exceptions


class StorageError(BaseAppException):
    """Raised when storage operations fail."""

    def __init__(self, detail: str, operation: str):
        # Map to controlled vocabulary to prevent high cardinality
        operation_map = {
            "read": "READ",
            "write": "WRITE",
            "delete": "DELETE",
            "create": "CREATE",
            "update": "UPDATE",
        }
        normalized_op = operation_map.get(operation.lower(), "UNKNOWN")
        super().__init__(
            f"Storage {operation} failed: {detail}",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_code=f"STORAGE_{normalized_op}_ERROR",
        )


class FilePermissionError(BaseAppException):
    """Raised when file permission issues occur."""

    def __init__(self, file_path: str, operation: str):
        detail = f"Permission denied for {operation} on '{file_path}'"
        super().__init__(
            detail, status.HTTP_500_INTERNAL_SERVER_ERROR, error_code="PERMISSION_ERROR"
        )


# Service Exceptions


class RAGServiceError(BaseAppException):
    """Raised when RAG service operations fail."""

    def __init__(self, detail: str):
        super().__init__(
            f"RAG service error: {detail}",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            error_code="RAG_SERVICE_ERROR",
        )


class ExternalAPIError(BaseAppException):
    """Raised when external API calls fail."""

    def __init__(self, service: str, detail: str):
        # Map to controlled vocabulary to prevent high cardinality
        service_map = {
            "openai": "OPENAI",
            "wikipedia": "WIKIPEDIA",
            "github": "GITHUB",
            "external": "EXTERNAL",
        }
        normalized_service = service_map.get(service.lower(), "EXTERNAL")
        super().__init__(
            f"{service} API error: {detail}",
            status.HTTP_502_BAD_GATEWAY,
            error_code=f"{normalized_service}_API_ERROR",
        )


# FAQ Exceptions


class FAQNotFoundError(ResourceNotFoundError):
    """Raised when FAQ is not found."""

    def __init__(self, faq_id: str):
        super().__init__("FAQ", faq_id)


class FAQAlreadyExistsError(ResourceAlreadyExistsError):
    """Raised when FAQ already exists."""

    def __init__(self, faq_id: str):
        super().__init__("FAQ", faq_id)


# Feedback Exceptions


class FeedbackNotFoundError(ResourceNotFoundError):
    """Raised when feedback is not found."""

    def __init__(self, message_id: str):
        super().__init__("Feedback", message_id)


class FeedbackAlreadyProcessedError(ResourceAlreadyExistsError):
    """Raised when feedback has already been processed."""

    def __init__(self, message_id: str):
        detail = f"Feedback with message_id '{message_id}' has already been processed"
        super().__init__("Processed Feedback", message_id)
        self.detail = detail  # Override the default message
