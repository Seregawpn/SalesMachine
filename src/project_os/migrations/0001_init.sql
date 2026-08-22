CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    website TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT,
    linkedin_url TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE project_organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    segment TEXT,
    relevance TEXT,
    status TEXT NOT NULL DEFAULT 'Research',
    UNIQUE(project_id, organization_id)
);

CREATE TABLE project_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    contact_id INTEGER NOT NULL REFERENCES contacts(id),
    status TEXT NOT NULL DEFAULT 'Research',
    priority TEXT NOT NULL DEFAULT 'Medium',
    pitch TEXT,
    linkedin_state TEXT NOT NULL DEFAULT 'Not started',
    linkedin_last_action_at TEXT,
    linkedin_next_action_due TEXT,
    UNIQUE(project_id, contact_id)
);

CREATE TABLE opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    contact_id INTEGER REFERENCES contacts(id),
    organization_id INTEGER REFERENCES organizations(id),
    stage TEXT NOT NULL DEFAULT 'Research',
    offer TEXT,
    value REAL,
    blocker TEXT,
    next_action TEXT,
    next_action_due TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    module TEXT NOT NULL,
    linked_table TEXT,
    linked_id INTEGER,
    reason TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'P2',
    due_date TEXT,
    suggested_message TEXT,
    status TEXT NOT NULL DEFAULT 'Open',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    actor TEXT NOT NULL,
    entity_table TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    reason TEXT
);
