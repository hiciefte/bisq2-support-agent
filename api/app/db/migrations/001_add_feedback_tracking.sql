-- Migration: Add feedback tracking for FAQ creation
-- This migration adds tracking fields to know which feedback items have been processed into FAQs

-- Add processed flag (default FALSE for existing records)
ALTER TABLE feedback ADD COLUMN processed INTEGER DEFAULT 0 CHECK(processed IN (0, 1));

-- Add timestamp when feedback was processed into FAQ
ALTER TABLE feedback ADD COLUMN processed_at DATETIME;

-- Add reference to the created FAQ (if applicable)
ALTER TABLE feedback ADD COLUMN faq_id TEXT;

-- Add index for efficient filtering by processed status
CREATE INDEX IF NOT EXISTS idx_feedback_processed ON feedback(processed);

-- Add index for FAQ lookups
CREATE INDEX IF NOT EXISTS idx_feedback_faq_id ON feedback(faq_id);
