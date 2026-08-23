ALTER TABLE actions ADD COLUMN source_interaction_id INTEGER REFERENCES interactions(id);
