ALTER TABLE project_contacts ADD COLUMN role TEXT;
ALTER TABLE project_contacts ADD COLUMN organization_id INTEGER REFERENCES organizations(id);
