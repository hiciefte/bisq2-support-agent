-- Migration: Add staff_answer_rating column to escalations table
-- This column stores user feedback on staff responses (0=unhelpful, 1=helpful)
-- NULL means not yet rated. CHECK constraint allows NULL or 0/1.
--
-- NOTE: This migration targets escalations.db, not feedback.db.
-- It is applied by EscalationRepository.initialize() rather than run_migrations().
ALTER TABLE escalations ADD COLUMN staff_answer_rating INTEGER
    CHECK(staff_answer_rating IS NULL OR staff_answer_rating IN (0, 1));
