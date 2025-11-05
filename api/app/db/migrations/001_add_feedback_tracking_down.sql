-- Migration Rollback: Remove feedback tracking fields
-- This is the DOWN migration for 001_add_feedback_tracking.sql

-- Drop indexes first
DROP INDEX IF EXISTS idx_feedback_faq_id;
DROP INDEX IF EXISTS idx_feedback_processed;

-- Remove columns (SQLite doesn't support DROP COLUMN directly)
-- We need to recreate the table without these columns
-- This is a destructive operation and should be used with caution

-- Note: SQLite's ALTER TABLE is limited. To drop columns, we need to:
-- 1. Create new table without the columns
-- 2. Copy data
-- 3. Drop old table
-- 4. Rename new table

-- For safety, we'll document the rollback procedure but not implement automatic column removal
-- Manual rollback procedure:
-- 1. Backup database first
-- 2. Create new table without processed, processed_at, faq_id columns
-- 3. Copy data: INSERT INTO feedback_new SELECT id, message_id, question, answer, rating, explanation, timestamp, created_at FROM feedback
-- 4. DROP TABLE feedback
-- 5. ALTER TABLE feedback_new RENAME TO feedback

-- WARNING: This rollback will lose data in processed, processed_at, and faq_id columns
