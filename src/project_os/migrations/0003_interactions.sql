CREATE TABLE interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    channel TEXT NOT NULL,
    direction TEXT NOT NULL,
    subject TEXT,
    ai_summary TEXT,
    intent TEXT,
    external_message_id TEXT,
    source TEXT NOT NULL DEFAULT 'apple-mail',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_interactions_external_id ON interactions(project_id, external_message_id);
