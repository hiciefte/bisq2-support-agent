"""Compatibility wrapper for the training ingest Bisq2 sync service.

The implementation was extracted to the training ingest domain:
``app.services.training.ingest.bisq2_sync_service``.
"""

from app.services.training.ingest.bisq2_sync_service import Bisq2SyncService

__all__ = ["Bisq2SyncService"]
