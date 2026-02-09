DROP TABLE IF EXISTS feedback_reactions;
DROP INDEX IF EXISTS idx_feedback_channel;
DROP INDEX IF EXISTS idx_feedback_method;
-- Note: SQLite does not support DROP COLUMN. To fully rollback the ALTER TABLE
-- additions, a table rebuild would be needed. The new columns with defaults are
-- harmless to leave in place.
