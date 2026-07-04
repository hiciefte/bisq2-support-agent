-- Migration: Add learning_state table for persisted learning artifacts
-- Stores JSON-serialized learning state (e.g. feedback-derived source weights
-- and prompt guidance) so it survives process boundaries and restarts.
-- Written by the weekly feedback-processing cron and the live API server,
-- read back by the live server on startup and via TTL refresh.

CREATE TABLE IF NOT EXISTS learning_state (
    key TEXT PRIMARY KEY,                       -- e.g. "source_weights", "prompt_guidance"
    value TEXT NOT NULL,                        -- JSON-serialized state value
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
