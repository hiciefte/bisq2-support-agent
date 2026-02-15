-- Rollback: Remove staff_answer_rating column from escalations table
-- SQLite doesn't support DROP COLUMN before 3.35.0, so we recreate the table.
CREATE TABLE escalations_backup AS SELECT
    id, message_id, channel, user_id, username, channel_metadata,
    question, ai_draft_answer, confidence_score, routing_action, routing_reason,
    sources, staff_answer, staff_id, delivery_status, delivery_error,
    delivery_attempts, last_delivery_at, generated_faq_id, status, priority,
    created_at, claimed_at, responded_at, closed_at
FROM escalations;

DROP TABLE escalations;

ALTER TABLE escalations_backup RENAME TO escalations;
