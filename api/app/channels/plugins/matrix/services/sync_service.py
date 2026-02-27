"""Compatibility wrapper for the training ingest Matrix sync service.

The implementation was extracted to the training ingest domain:
``app.services.training.ingest.matrix_sync_service``.
"""

from app.services.training.ingest.matrix_sync_service import (
    NIO_AVAILABLE,
    AsyncClient,
    MatrixSyncService,
    RoomMessagesResponse,
)

__all__ = [
    "AsyncClient",
    "MatrixSyncService",
    "NIO_AVAILABLE",
    "RoomMessagesResponse",
]
