# Paper Redesign & Nexy Data Import — Design

**Goal:** Replace the current "Charcoal & White" visual system with the warm/paper design validated in the standalone mockup (`~/Desktop/Project OS CRM - standalone.html`), applied to the six pages that exist today, and load the real Nexy outreach spreadsheet (~638 usable rows) into the "Nexy" project so the redesigned UI shows real data instead of an empty DB.

**Non-goals (deferred to a later phase, no backend exists for these today):** unified email inbox UI, LinkedIn message-thread view, an Outreach kanban, a Tasks board/list/Gantt, the notifications bell, global search. This pass only restyles and re-populates what's already built: Action Center, Projects, Contacts, Pipeline, LinkedIn Queue, Interactions.

## Part 1 — Visual System

**Palette & tokens** (`style.css` rewritten, same CSS-custom-property approach as today):
- Background: `#F5F5F4` (paper), cards/table surfaces: `#FFFFFF`, borders: `#E5E4E1`
- Accent: `oklch(43% 0.12 258)` (the mockup's blue), hover-darker `oklch(36% 0.12 258)`
- Text: primary `#1A1A19`, secondary `#78776F`, muted `#A3A29B`
- Priority badges keep today's 4-tier semantics (P0 red / P1 amber / P2 indigo / P3 gray) but restyled to the mockup's pill shape (monospace, uppercase, `border-radius: 3px`)
- Font: same system stack as today (`-apple-system, Helvetica Neue, sans-serif`), no webfont — keeps zero-build-step
- Monospace (`ui-monospace, SFMono-Regular, Menlo`) used for metadata labels/dates/badges, matching the mockup's convention of serif-body / mono-metadata contrast

**Structural change — sidebar → top nav:** the mockup has no left sidebar; it's a top header bar (logo, project name, search placeholder, avatar) plus a tab row below it. `base.html` changes from `.sidebar` + `.content` flex layout to a header (`<div class="topbar">`) + tab nav (`<nav class="tabs">`) + content area, stacked vertically. The 4 nav links (Action Center, Projects, Contacts, Interactions) become the tab row. Search box and notification bell in the mockup are **static/decorative in this pass** — no backend, not wired to anything (added because the mockup calls for the chrome, but functionality is out of scope per the non-goals above).

**Per-page treatment:**
- **Action Center** → mockup's "Priority queue" table styling: pill badges for priority, inline Open/Snooze/Done buttons styled as the mockup's small bordered/filled buttons.
- **Projects** → mockup's project-card list (name, description, stat row) instead of a bare `<ul>`.
- **Pipeline** → mockup's pipeline table styling (org/contact/stage-select/amount/blocker/next/due columns) — same columns as today, restyled only.
- **LinkedIn Queue** → the mockup has no direct equivalent, but its 4-column "Outreach" board (grouped cards by status) maps naturally onto the queue's existing 4 sections (to connect / pending / awaiting message / awaiting reply) — restyle as a 4-column card board instead of 4 stacked tables.
- **Interactions** (global feed) → mockup's activity-feed row styling (tag badge for channel/direction, name, timestamp, one-line preview) instead of a plain table.
- **Contacts** (global) → the one page getting a **structural**, not just visual, change — see Part 1a.

### 1a. Contacts: company-grouped, expandable

The mockup's Contacts screen groups people under their company (expand/collapse row revealing an inline people table + AI-summary-style blurb + correspondence feed). The real app's schema already supports this (`organizations` ← `project_organizations` ← `project_contacts` → `contacts`), but `list_contacts()` today is a flat, ungrouped, cross-project query.

Change: `GET /contacts` groups by organization. New repository query `list_companies_with_contacts(conn) -> list[dict]`: one row per organization (across all projects, since this is the global page) with a nested list of its contacts (name, email, linkedin_url, role — note: no `role` column exists on `contacts` or `project_contacts` today; the mockup shows role per-person, so add `project_contacts.role TEXT` in a new migration `0005_project_contacts_role.sql`, populated during import). Contacts with **no organization** (the B2C individuals) get a single synthetic "Individuals" group at the top, not a fabricated organization row in the `organizations` table.

Expand/collapse uses `<details>/<summary>` per company row — zero JS, keeps the progressive-enhancement approach already used for htmx (this works with or without JS/htmx present).

## Part 2 — Nexy Data Import

**Source:** `data/imports/nexy_outreach.csv` (gitignored — real names/emails, not committed), a snapshot export of the Google Sheet. One-time/idempotent script, not a live sync.

**Script:** `src/project_os/import_nexy.py`, run via `python -m project_os.import_nexy data/imports/nexy_outreach.csv`. Targets the existing "Nexy" project (`project_id=1`, looked up by name, fails loudly if not found — no auto-create).

**Row handling** (638 non-blank rows out of 1005 raw lines; blank separator rows skipped):

| Sheet column(s) | Target |
|---|---|
| `Account Name` (fallback `Company`) | `organizations.name` — get-or-create by case-insensitive name match (new repo fn `get_organization_by_name`) |
| `Category` + `Subcategory` | `project_organizations.segment` (joined `"Work / Workplace Accessibility"`) |
| `Organization Type` | `project_organizations.relevance` |
| `Account Control` | `project_organizations.status`, mapped: `RESEARCH ACCOUNT`→`Research`, `CONTACTED ACCOUNT`→`Contacted`, `ACTIVE ACCOUNT`→`Engaged`, `ARCHIVE / SKIP`→`Closed`, blank→`Research` |
| `Contact Name` | `contacts.name` — **only when present**; rows with no named contact (359 of them — companies still in pure research, generic inbox only) create/link the organization only, no contact/opportunity/interaction |
| `Email` (first address if semicolon-separated) | `contacts.email` — get-or-create by case-insensitive email match when present, else by (name, org) pair |
| `LinkedIn` | `contacts.linkedin_url` |
| `Contact Role` (fallback `Role / Title`) | new `project_contacts.role` |
| `Stage` | `project_contacts.status`, passed through as-is when it's one of the sheet's own recognizable values, else `Research` |
| `Priority` | `project_contacts.priority`, default `Medium` if blank |
| `What Was Sent` (truncated ~500 chars) | `project_contacts.pitch` |
| `Type` = `B2B` or `Partner` **and** a contact exists | also create an `opportunities` row: `offer` = Subcategory, `stage` mapped from sheet `Stage` into the app's canonical `pipeline.STAGES` list (mapping table below), `blocker` = sheet `Response / Context` (truncated), `next_action` = `Next Step`, `next_action_due` = `Follow-up Date` only if it parses as `YYYY-MM-DD`, else null |
| `Type` = `B2C` | contact + `project_contacts` only, no opportunity (consumer testers aren't sales-pipeline deals) |
| `Last Communication` (only if `YYYY-MM-DD`) + `Channel` + `What Was Sent`/`Response / Context` | one `interactions` row: `direction='outbound'`, `subject` = first ~120 chars of `What Was Sent`, `ai_summary` = `Response / Context`, `source='import-nexy-sheet'` |

**Stage mapping table** (sheet → `pipeline.STAGES`):
`Research`→`Research`, `Ready to Contact`→`Ready to contact`, `Contacted`→`Contacted`, `Follow-up`→`Contacted`, `Engaged`→`Interested`, `Meeting Scheduled`→`Meeting booked`, `Installed / Active Tester`→`Pilot`, `Paused / External Dependency`→`Interested` (note preserved in `blocker`), `Closed Lost / Not Target`→`Closed`; anything unrecognized falls back to `Research` with the original text preserved in `blocker`.

**Idempotency:** every insert is get-or-create keyed on the natural key (org name, contact email/name+org, project_contacts unique on `(project_id, contact_id)`, project_organizations unique on `(project_id, organization_id)`). Re-running the script updates nothing and creates nothing new for rows already imported — safe to re-run after fixing a mapping bug. Interactions are the one exception (no natural uniqueness in the schema); the script guards against duplicate interaction rows by checking `(contact_id, subject, created_at)` before inserting.

Whole import runs in a single transaction; prints a summary (`N organizations, N contacts, N opportunities, N interactions created`).

## Testing

- **Visual/structural:** no automated visual assertions (per the existing design system's own precedent) — verified live via the Browser tool against the running daemon, each of the 6 pages compared to the mockup.
- **Contacts grouping:** repository test for `list_companies_with_contacts` — two orgs each with contacts across two different projects, assert grouping and the synthetic "Individuals" bucket for org-less contacts.
- **Migration:** `0005_project_contacts_role.sql` gets a schema-version assertion test matching the existing pattern (`test_db.py`).
- **Import script:** a small fixture CSV (~10 rows covering: B2B with contact, B2B without contact, B2C, a row with a bad/unparseable date, a duplicate email) in `tests/fixtures/`; test asserts correct row counts after one run, and **unchanged** counts after running twice (idempotency). Does not test against the full real sheet.

## Self-Review Notes

- **Explicitly out of scope:** everything in the Non-goals list at the top; also no change to `mail_sync`/`unipile_sync` logic, no new `Account Control`/`Stage` values invented beyond the mapping tables above, no attempt to parse the sheet's inconsistent free-text date fields beyond strict `YYYY-MM-DD` matching (anything else is left as null rather than guessed).
- **Consistency check:** the new `project_contacts.role` column is additive (migration 0005), doesn't change existing route behavior for any row where it's null; the Contacts page structural change is scoped to the read query + template, no write routes change.
- **PII handling:** the source CSV lives only in the gitignored `data/` directory, never committed.
