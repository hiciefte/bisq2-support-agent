-- Rollback: Remove staff_answer_rating column from escalations table
-- SQLite doesn't support DROP COLUMN before 3.35.0, so we recreate the table
-- with the full schema to preserve constraints, indexes, and AUTOINCREMENT.

BEGIN TRANSACTION;

CREATE TABLE escalations_backup (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT,
    channel_metadata TEXT,
    question TEXT NOT NULL,
    ai_draft_answer TEXT NOT NULL,
    confidence_score REAL NOT NULL,
    routing_action TEXT NOT NULL,
    routing_reason TEXT,
    sources TEXT,
    staff_answer TEXT,
    staff_id TEXT,
    delivery_status TEXT NOT NULL DEFAULT 'not_required'
        CHECK(delivery_status IN ('not_required', 'pending', 'delivered', 'failed')),
    delivery_error TEXT,
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    last_delivery_at TEXT,
    generated_faq_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'in_review', 'responded', 'closed')),
    priority TEXT NOT NULL DEFAULT 'normal'
        CHECK(priority IN ('normal', 'high')),
    created_at TEXT NOT NULL,
    claimed_at TEXT,
    responded_at TEXT,
    closed_at TEXT,
    CHECK(LENGTH(question) <= 4000),
    CHECK(LENGTH(ai_draft_answer) <= 10000),
    CHECK(LENGTH(staff_answer) <= 10000)
);

INSERT INTO escalations_backup
    SELECT id, message_id, channel, user_id, username, channel_metadata,
           question, ai_draft_answer, confidence_score, routing_action, routing_reason,
           sources, staff_answer, staff_id, delivery_status, delivery_error,
           delivery_attempts, last_delivery_at, generated_faq_id, status, priority,
           created_at, claimed_at, responded_at, closed_at
    FROM escalations;

DROP TABLE escalations;

ALTER TABLE escalations_backup RENAME TO escalations;

CREATE INDEX IF NOT EXISTS idx_escalations_status ON escalations(status);
CREATE INDEX IF NOT EXISTS idx_escalations_channel ON escalations(channel);
CREATE INDEX IF NOT EXISTS idx_escalations_priority ON escalations(priority, created_at);
CREATE INDEX IF NOT EXISTS idx_escalations_message_id ON escalations(message_id);
CREATE INDEX IF NOT EXISTS idx_escalations_responded_at ON escalations(responded_at);

COMMIT;
