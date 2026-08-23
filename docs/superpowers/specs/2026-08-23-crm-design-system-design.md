# CRM Design System & Navigation — Design

**Goal:** Project OS's web UI has no design system — `style.css` is 6 lines, the header nav only links to Action Center, and every page fully reloads for every action. This replaces it with a real, dense, functional visual design (validated with the user via mockups), adds the missing global navigation (Projects, Contacts, Interactions), and makes key actions update in place via htmx instead of a full page reload — without abandoning the existing server-rendered, no-build-step architecture.

**Non-goals:** No SPA rewrite, no new backend data model beyond two new read-only listing queries (global contacts, global interactions feed), no new project-scoped pages beyond what already exists (Pipeline and LinkedIn Queue stay project-scoped, not promoted to global nav items).

## Visual Direction (validated with mockups)

- **Layout: Dense & Functional** — compact rows, real information density (Airtable/HubSpot-inspired), not the sparse "Clean & Minimal" alternative. Priority is shown as a colored badge (P0 red, P1 amber, P2 indigo/blue, P3 neutral gray), consistent everywhere a priority appears.
- **Color: Charcoal & White** — a dark neutral sidebar (`#18181b`-family, no blue tint) against a light content area (white/`#f4f4f5` alternating table rows), not navy-tinted and not fully light. This becomes the CSS custom-property palette (`--sidebar-bg`, `--sidebar-active-bg`, `--text-primary`, `--border`, `--badge-p0-bg`/`--badge-p0-fg`, etc.) defined once in `style.css` and reused everywhere — no per-page inline styles.
- Typography: system font stack (`-apple-system, sans-serif`), no webfont loading (keeps the zero-build-step property).

## Architecture

**htmx**, not a JS framework: a single `<script src="/static/vendor/htmx.min.js">` (vendored, not CDN-loaded, so the app has no runtime dependency on an external network call) added to `base.html`. FastAPI routes stay FastAPI routes; Jinja2 stays Jinja2. No `npm`, no build step, no new Python dependency.

**Progressive enhancement, not a hard requirement:** every mutating route keeps its existing full-page-redirect behavior as the default. When the request carries the `HX-Request: true` header (htmx sets this automatically), the route instead returns a small HTML fragment for htmx to swap in — the same feature works identically with JS disabled, just with a full page reload instead of an in-place update.

`style.css` moves from 6 lines to a real token-based stylesheet: CSS custom properties for color/spacing/typography, a `.sidebar` + `.content` layout shell used by `base.html`, and reusable classes for tables, badges, and cards so individual page templates don't hand-roll styles.

## Navigation

Global sidebar (in `base.html`, replacing the current single Action Center link):

- **Action Center** (`/action-center`) — unchanged as the app's home page/landing view; this was deliberately kept over promoting a metrics dashboard, since surfacing "what needs action right now" is the tool's actual daily job.
- **Projects** (`/projects`) — already exists (added in the earlier nav-fix commit), lists every project.
- **Contacts** (`/contacts`, new) — every contact across every project, not scoped to one project. Backed by a new `list_contacts(conn) -> list[sqlite3.Row]` in `repositories/contacts.py` (`SELECT * FROM contacts ORDER BY name`).
- **Interactions** (`/interactions`, new) — a chronological feed of inbound/outbound communication across every project (the same rows `mail_sync` and the Approve & Send route already write to the `interactions` table, just not visible anywhere in the UI yet). Backed by a new `list_interactions(conn, limit: int = 50) -> list[sqlite3.Row]` in `repositories/interactions.py`, joining `contacts` for the display name and ordered by `created_at DESC`.

**Pipeline and LinkedIn Queue are explicitly NOT promoted to the global sidebar.** They stay reachable only from a project's own overview page (`project_overview.html`'s existing "Open Sales Pipeline"/"Open LinkedIn Queue" links), because they are genuinely project-scoped in the data model (`list_pipeline(conn, project_id)`, `list_linkedin_queue(conn, project_id)`) — a global "Pipeline" nav item would need an implicit "current project" concept that doesn't exist anywhere else in this app, and inventing one is out of scope here.

## htmx Interactivity

Pattern applied uniformly: a mutating route checks `request.headers.get("hx-request") == "true"`. If true, it returns a `TemplateResponse` rendering a small partial template (no `base.html` wrapping) instead of a `RedirectResponse`. If false (no JS, or a non-htmx client), behavior is completely unchanged from today.

Applied to these five existing routes:

| Route | Non-htmx (today) | htmx response |
|---|---|---|
| `POST /actions/{id}/complete` | 303 redirect to `/action-center` | Empty fragment — htmx removes the row (`hx-target="closest tr"`, `hx-swap="outerHTML swap:0.2s"`) |
| `POST /actions/{id}/snooze` | 303 redirect | The updated `<tr>` partial (new due date) |
| `POST /actions/{id}/send` (success) | 303 redirect | Empty fragment — row removed, same as complete |
| `POST /actions/{id}/send` (failure) | 303 redirect with `?error=` | The flash-error banner markup via `hx-swap-oob="true"` (updates the banner region out-of-band) while the row itself is left untouched, still open with its draft intact, for another attempt |
| `POST /projects/{id}/pipeline/{opp_id}/stage` | 303 redirect | The updated pipeline row/card partial reflecting the new stage |
| `POST /projects/{id}/linkedin/{pc_id}/state` | 303 redirect | The updated queue row partial reflecting the new state |

Each partial is its own small template file (e.g. `_action_row.html`, `_pipeline_row.html`, `_linkedin_row.html`) that the full page template also includes when rendering the initial list — so the row markup is defined once, not duplicated between the full-page render and the htmx partial response.

## New Pages

**`GET /contacts`** (new route in `routes_contacts.py`) — table of all contacts (name, email, LinkedIn URL if present), dense-table style matching the visual direction. No filtering/search in this pass (YAGNI — add if it turns out to be needed once there's enough contact volume to matter).

**`GET /interactions`** (new route in `routes_interactions.py`) — reverse-chronological list of the 50 most recent interactions across all projects: contact name, project name, channel, direction (inbound/outbound), subject, date. Read-only, no actions on this page.

## Testing

- Existing route tests keep passing unmodified — they don't send `HX-Request`, so they exercise the unchanged redirect path.
- New tests for each htmx-enabled route: send `client.post(..., headers={"HX-Request": "true"})` and assert the response is a fragment (status 200, body does NOT contain `<html>` or `<nav>`) rather than a redirect.
- `list_contacts`/`list_interactions`: standard repository tests — create rows across two different projects, assert both come back in one global query, assert ordering.
- No test asserts on CSS/visual appearance — verified live against the running daemon, the same way prior work in this session was verified (curl / browser).

## Self-Review Notes

- **Explicitly out of scope:** promoting Pipeline/LinkedIn Queue to global nav (would require inventing a "current project" concept not present elsewhere in the app); search/filtering on the new Contacts/Interactions pages; a metrics dashboard as the home page (Action Center stays home, per explicit choice above); any change to `mail_sync`'s classification logic or the `interactions`/`contacts` schema — this design only adds read queries over existing tables.
- **Consistency check:** every htmx response format (empty fragment vs. partial vs. OOB swap) is tied to a specific existing route and existing repository function — no route in this design invents new backend logic beyond the two new listing queries.
