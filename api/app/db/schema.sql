-- Feedback Database Schema
-- Stores user feedback, conversation history, and metadata for the Bisq 2 Support Assistant

-- Main feedback table
-- Note: sources, sources_used, processed, processed_at, and faq_id columns
-- are added by database migrations (see migrations/ directory)
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,           -- UUID from the chat message
    question TEXT NOT NULL,                     -- User's question
    answer TEXT NOT NULL,                       -- Assistant's answer
    rating INTEGER NOT NULL CHECK(rating IN (0, 1)),  -- 0=negative, 1=positive
    explanation TEXT,                           -- User's feedback explanation (optional)
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for feedback table
-- Note: Indexes for processed, faq_id, sources, and sources_used
-- are created by database migrations (see migrations/ directory)
CREATE INDEX IF NOT EXISTS idx_feedback_message_id ON feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_feedback_timestamp ON feedback(timestamp);
CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating);
CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at);

-- Conversation history table (one-to-many with feedback)
CREATE TABLE IF NOT EXISTS conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),  -- user or assistant
    content TEXT NOT NULL,                      -- Message content
    position INTEGER NOT NULL,                  -- Order in conversation (0-based)
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (feedback_id) REFERENCES feedback(id) ON DELETE CASCADE
);

-- Indexes for conversation_messages table
CREATE INDEX IF NOT EXISTS idx_conv_feedback_id ON conversation_messages(feedback_id);
CREATE INDEX IF NOT EXISTS idx_conv_position ON conversation_messages(feedback_id, position);

-- Metadata table for flexible key-value storage
CREATE TABLE IF NOT EXISTS feedback_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id INTEGER NOT NULL,
    key TEXT NOT NULL,                          -- Metadata key (e.g., "answered_from", "context_fallback")
    value TEXT NOT NULL,                        -- Metadata value (JSON string for complex values)
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (feedback_id) REFERENCES feedback(id) ON DELETE CASCADE,
    UNIQUE(feedback_id, key)                    -- One value per key per feedback entry
);

-- Indexes for feedback_metadata table
CREATE INDEX IF NOT EXISTS idx_meta_feedback_id ON feedback_metadata(feedback_id);
CREATE INDEX IF NOT EXISTS idx_meta_key ON feedback_metadata(key);

-- Issues table for tracking common feedback problems
CREATE TABLE IF NOT EXISTS feedback_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feedback_id INTEGER NOT NULL,
    issue_type TEXT NOT NULL,                   -- e.g., "too_long", "incorrect", "outdated"
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (feedback_id) REFERENCES feedback(id) ON DELETE CASCADE
);

-- Indexes for feedback_issues table
CREATE INDEX IF NOT EXISTS idx_issues_feedback_id ON feedback_issues(feedback_id);
CREATE INDEX IF NOT EXISTS idx_issues_type ON feedback_issues(issue_type);

-- View for easy querying with conversation history
CREATE VIEW IF NOT EXISTS feedback_with_context AS
SELECT
    f.id,
    f.message_id,
    f.question,
    f.answer,
    f.rating,
    f.explanation,
    f.timestamp,
    f.created_at,
    (
        SELECT GROUP_CONCAT(
                   json_object(
                     'role', c.role,
                     'content', c.content,
                     'position', c.position
                   )
               )
        FROM (
            SELECT role, content, position
            FROM conversation_messages
            WHERE feedback_id = f.id
            ORDER BY position
        ) AS c
    ) AS conversation_history_json,
    (SELECT GROUP_CONCAT(fm.key || '=' || fm.value, ';')
     FROM feedback_metadata fm
     WHERE fm.feedback_id = f.id) as metadata_str,
    (SELECT GROUP_CONCAT(fi.issue_type, ',')
     FROM feedback_issues fi
     WHERE fi.feedback_id = f.id) as issues_str
FROM feedback f;
