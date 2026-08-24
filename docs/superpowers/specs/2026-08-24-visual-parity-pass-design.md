# Visual Parity Pass — Design

**Goal:** Close the specific gaps between the current app and the standalone mockup (`~/Desktop/Project OS CRM - standalone.html`) that were skipped in the first redesign pass: header chrome, a pipeline funnel on the dashboard, richer company detail on Contacts, and closer visual match on the LinkedIn board.

**Non-goals:** The mockup's right-side AI assistant panel (chat history, sessions, AI-drafted "send email" action cards) — that's a real feature requiring an AI backend integration, not a styling task; explicitly out of scope here, to be designed separately if wanted. No fabricated content anywhere — every visual element added must be either purely decorative (matching the mockup's own non-functional chrome) or backed by real data already in the database.

## 1. Header chrome (decorative, matches the mockup exactly)

The mockup's search box and notification bell are themselves non-functional placeholders in the source (`onClick="{{ toggleNotifs }}"` bound to nothing real, the search box is a plain `<div>` with an icon and static placeholder text, not an `<input>`). We match that honestly:

- **Search**: a plain `<div>` styled like a search field, containing a magnifying-glass glyph and the static text "Search people, deals, mail" — not a real `<input>`, so there's no false affordance of a working search.
- **Notification bell**: a plain `<span>` (not a `<button>`) styled as a circular icon — no `onclick`, no dropdown, since there is nothing to notify about yet.

Both added to `base.html`'s `.topbar`, between the brand and the tabs, matching the mockup's layout order.

## 2. Dashboard funnel (Action Center) — real pipeline data

**New repository query**, `count_opportunities_by_stage(conn) -> list[dict]` in `repositories/opportunities.py`: `SELECT stage, COUNT(*) AS count FROM opportunities GROUP BY stage`, then reordered in Python into `pipeline.STAGES` canonical order, **stages with zero opportunities omitted** (no fake empty bars). Each dict: `{"stage": str, "count": int, "width_pct": int}` — `width_pct` computed against the max count in the result set (the largest bar is 100%, others scaled relative to it), matching the mockup's proportional-bar visual.

Rendered as a new section at the top of `action_center.html`, above "Priority queue" (unchanged), styled with the same `.table-card` + bar-row pattern the mockup uses for its funnel (new small CSS additions: `.funnel-row`, `.funnel-track`, `.funnel-fill` — same token variables as everything else, no new colors).

This is global (all projects, matching Action Center's existing global scope) — with one real project in the database today, that's the same as project-scoped, but the query doesn't hardcode a project id.

## 3. Contacts — company detail: real activity feed + factual summary line

The mockup shows a hand-written "AI summary" paragraph per company. We have no such data (no per-company AI summarization exists anywhere in the codebase) and won't fabricate one. Instead:

- **Factual summary line**, computed in Python, not stored: `"{open_opportunities} open opportunit{y|ies} · last activity {relative date or 'none yet'}"`. Replaces the mockup's prose blurb with something true.
- **Recent activity feed**: the 5 most recent `interactions` rows across every contact belonging to that company, reusing the existing `.feed`/`.feed-row` styling from the Interactions page — this is the same data the mockup's "activity" array represents, just pulled from real rows instead of hand-authored.

**Extend `list_companies_with_contacts`** (`repositories/contacts.py`) to add, per company **except** the synthetic "Individuals" bucket (`id is None` — there's no single organization to aggregate against):
- `open_opportunities: int` — `SELECT COUNT(*) FROM opportunities WHERE organization_id = ? AND stage != 'Closed'`
- `activity: list[sqlite3.Row]` — the 5 most recent interactions from contacts linked to that org: `SELECT i.*, c.name AS contact_name FROM interactions i JOIN contacts c ON c.id = i.contact_id JOIN project_contacts pc ON pc.contact_id = c.id AND pc.organization_id = ? ORDER BY i.created_at DESC, i.id DESC LIMIT 5`

Both are per-company queries (already an N+1 pattern before this change, measured at ~6ms for ~190 companies in production — adding two more per-company queries stays well within acceptable latency for a single-user internal tool; not worth restructuring into a single join for this scale). The summary line itself is built in the route/template from `open_opportunities` + `activity[0]["created_at"]` if present, not stored.

## 4. LinkedIn board — closer to the mockup's card style

Two additive, no-backend-change template tweaks to `linkedin_queue.html`:
- Show each contact's `role` (from `project_contacts.role`, already selected via `pc.*` in `list_linkedin_queue` — no repository change needed) under their name, matching the mockup's name+role card pattern.
- Show a count next to each column header (`{{ queue["to_connect"] | length }}`, etc.), matching the mockup's per-column count badge.

## Testing

- `count_opportunities_by_stage`: repo test — seed opportunities across 3 stages plus one `Closed`, assert zero-count stages excluded, assert `width_pct` scaling (largest count → 100).
- `list_companies_with_contacts`: extend existing tests — assert `open_opportunities` count excludes `Closed`, assert `activity` ordering and 5-row cap, assert the "Individuals" bucket dict has no `open_opportunities`/`activity` keys at all (not present in the dict, not `None` — the template guards on `company["id"]` before ever reading them).
- Route tests for Action Center: funnel section renders with real stage labels; empty-DB case shows no funnel section (not an empty one).
- No test needed for the decorative header elements or the LinkedIn role/count additions — pure template output, covered implicitly by existing route tests still passing (they don't assert against exact HTML byte-count, only specific substrings).

## Self-Review Notes

- **Explicitly out of scope:** the AI assistant panel (separate feature, needs its own design), any global search backend, any real notification system, any AI-generated company summaries.
- **No fabrication:** every new visual element is either literally decorative in the same way the mockup's own placeholder chrome is, or computed from real rows already in the database.
- **Consistency check:** the "Individuals" bucket's lack of `open_opportunities`/`activity` is intentional (there's no single organization to aggregate against for a bucket of unrelated individuals) and must be reflected in both the repository function and its template guard.
