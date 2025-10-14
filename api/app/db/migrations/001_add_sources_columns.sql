-- Migration 001: Add sources and sources_used columns to feedback table
-- This migration adds source tracking capabilities to support analytics on source effectiveness

-- Add sources column (JSON string array of source dictionaries)
ALTER TABLE feedback ADD COLUMN sources TEXT;

-- Add sources_used column (JSON string array of source dictionaries actually used in response)
ALTER TABLE feedback ADD COLUMN sources_used TEXT;

-- Create index for faster source-based queries
CREATE INDEX IF NOT EXISTS idx_feedback_sources ON feedback(sources) WHERE sources IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_feedback_sources_used ON feedback(sources_used) WHERE sources_used IS NOT NULL;
