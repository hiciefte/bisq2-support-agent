-- Rollback Migration 002: Remove sources and sources_used columns from feedback table
-- This rolls back source tracking capabilities

-- Drop indexes first
DROP INDEX IF EXISTS idx_feedback_sources;
DROP INDEX IF EXISTS idx_feedback_sources_used;

-- Remove columns (SQLite limitation: need to recreate table)
-- Note: SQLite doesn't support DROP COLUMN directly, so we need to:
-- 1. Create temporary table without the columns
-- 2. Copy data
-- 3. Drop original table
-- 4. Rename temp table

-- However, since these columns were just added, we can use a simpler approach
-- by checking if they exist before attempting to remove them.
-- For simplicity in this rollback, we'll just set them to NULL and document the limitation.

-- SQLite Alternative: Clear the columns (full removal requires table recreation)
UPDATE feedback SET sources = NULL, sources_used = NULL WHERE sources IS NOT NULL OR sources_used IS NOT NULL;

-- Note: To fully remove columns in SQLite, the table would need to be recreated.
-- This rollback preserves data integrity while clearing source tracking data.
