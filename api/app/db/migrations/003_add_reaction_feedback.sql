-- Add channel metadata columns to feedback table
ALTER TABLE feedback ADD COLUMN channel TEXT DEFAULT 'web' NOT NULL;
ALTER TABLE feedback ADD COLUMN feedback_method TEXT DEFAULT 'web_dialog' NOT NULL;
ALTER TABLE feedback ADD COLUMN external_message_id TEXT;
ALTER TABLE feedback ADD COLUMN reactor_identity_hash TEXT;
ALTER TABLE feedback ADD COLUMN reaction_emoji TEXT;

CREATE INDEX IF NOT EXISTS idx_feedback_channel ON feedback(channel, timestamp);
CREATE INDEX IF NOT EXISTS idx_feedback_method ON feedback(feedback_method);

-- Reaction tracking table for deduplication and emoji changes
CREATE TABLE IF NOT EXISTS feedback_reactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,
    external_message_id TEXT NOT NULL,
    reactor_identity_hash TEXT NOT NULL,
    reaction_emoji TEXT NOT NULL,
    feedback_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    last_updated_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY (feedback_id) REFERENCES feedback(id) ON DELETE CASCADE,
    UNIQUE(channel, external_message_id, reactor_identity_hash)
);
