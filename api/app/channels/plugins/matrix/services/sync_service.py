"""Compatibility wrapper for the knowledge ingest Matrix sync service.

The implementation was extracted to the knowledge ingest domain:
``app.services.knowledge.ingest.matrix_sync_service``.
"""

from app.services.knowledge.ingest.matrix_sync_service import (
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
