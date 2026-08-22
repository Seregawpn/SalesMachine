-- Columns already exist from 0001_init.sql. This migration is a no-op
-- placeholder that reserves version 2 for the LinkedIn feature so future
-- LinkedIn-related schema changes have a clean place to append.
CREATE TABLE IF NOT EXISTS linkedin_state_reference (
    state TEXT PRIMARY KEY
);
INSERT OR IGNORE INTO linkedin_state_reference (state) VALUES
    ('Not started'), ('Pending Connection'), ('Accepted'),
    ('Message Sent'), ('Replied'), ('Not relevant');
