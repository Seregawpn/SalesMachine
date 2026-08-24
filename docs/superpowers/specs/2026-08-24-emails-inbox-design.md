# Emails Inbox — Design

**Goal:** Give email a dedicated, browsable home in the UI — a list-plus-detail inbox view over every email interaction the system already knows about — instead of email only being visible piecemeal through Action Center rows and the generic global Interactions feed.

**Non-goals:** No live Apple Mail query on page load (the existing periodic `mail_sync` scheduler job is the only mail-fetching path; this page only reads what it has already written to the DB). No "Regenerate" (AI redraft) or "Not relevant" (dismiss) buttons — deferred, no backend support exists for either today. No new schema, no raw email body storage, no change to the AI mail-checking pipeline (`mail_sync.py`) or the `interactions`/`actions` tables' shape.

## Why no raw body

`interactions` has no `body` column, and `mail_sync.check_for_new_mail`'s AI prompt (`mail_sync.py:15-45`) is deliberately structured to have Codex read the message via its own `list_unread_messages` tool call and return only a summary/intent/draft-reply — the raw message text is never returned to Python, so it's never persisted anywhere. The detail pane therefore shows the AI summary (`interactions.ai_summary`), explicitly labeled as an AI summary, not a full message body. Outbound (sent) interactions have no summary at all today (`routes_action_center.py:115-119` creates them with `ai_summary=None`) — the detail pane shows direction/subject/date only for those.

## Data

**New repository query**, `list_email_interactions(conn) -> list[sqlite3.Row]` in `repositories/interactions.py`:

```sql
SELECT i.*, c.name AS contact_name, p.name AS project_name,
       a.id AS open_action_id, a.suggested_message AS draft_reply
FROM interactions i
JOIN contacts c ON c.id = i.contact_id
JOIN projects p ON p.id = i.project_id
LEFT JOIN actions a ON a.source_interaction_id = i.id AND a.status = 'Open'
WHERE i.channel = 'email'
ORDER BY i.created_at DESC, i.id DESC
```

One row per email interaction, each optionally carrying its still-open reply action (there is at most one open action per interaction in current usage — every `source_interaction_id`-linked action is created once, at sync time, by `sync_mail_replies`).

## Routes

`src/project_os/web/routes_emails.py` (new):

- **`GET /emails`** — renders the list; detail pane shows the most recent email (first row) by default.
- **`GET /emails/{interaction_id}`** — same list, detail pane shows the specified interaction. 404 if the id doesn't exist or isn't a `channel='email'` row.

Both call `list_email_interactions`, then pick the selected row (by id or by default-first) in Python before rendering — one template, `emails_index.html`, handles both.

**Reply/send stays on the existing route.** The detail pane's form posts to the existing `/actions/{action_id}/send` (same route Action Center already uses), plus one new hidden field: `<input type="hidden" name="view" value="emails">`. `send_reply` reads this optional field:

- **`view` absent** (Action Center, today's behavior, unchanged): htmx success → empty-fragment `_BANNER_RESET` (row removed); non-htmx success → 303 redirect to `/action-center`.
- **`view=emails`** (new, additive branch): htmx success → re-renders `_email_detail.html` for that interaction (now with no open action, so the reply form is gone and "No action needed" shows instead) rather than an empty fragment, since an inbox detail pane has nothing to remove; non-htmx success → 303 redirect to `/emails/{interaction_id}` instead of `/action-center`.

Failure handling (empty message, send error) is unchanged for both paths — same flash-banner OOB-swap behavior either way, since the detail pane's form is left open with its draft intact regardless of which page it came from.

## Templates

- `emails_index.html` — extends `base.html`; two-column layout (`grid-template-columns: minmax(280px,340px) 1fr`, matching the Contacts/Messages two-pane pattern already used in the mockup) — left column list of `<a href="/emails/{id}">` rows (contact name, subject truncated, time, direction tag), right column includes `_email_detail.html`.
- `_email_detail.html` — subject, contact + project, date, direction tag; AI summary block (only if `ai_summary` is set); reply form (only if `open_action_id` is set) with the draft textarea + Approve & Send button; otherwise a plain "No action needed" note. This partial is also what the htmx success response re-renders (per the Routes section above).

New CSS needed: none beyond what Task 5 of the prior redesign already defined (`.feed`-style list rows for the left column, `.table-card`-style container for the detail pane, `.tag` for the direction badge) — reused, not extended.

## Navigation

`base.html`'s `.tabs` gains a fifth link: `<a href="/emails">Emails</a>`, positioned after Action Center (its natural place — the mockup puts Emails second, right after the dashboard).

## Testing

- `list_email_interactions`: repo test — seed one inbound-with-open-action, one inbound-already-actioned (action completed), one outbound (no action ever), one non-email interaction (channel='linkedin') to prove the filter; assert ordering and that `open_action_id`/`draft_reply` are correctly null vs populated.
- `GET /emails` and `GET /emails/{id}`: route tests — empty state, default-selects-most-recent, explicit id selects that row, 404 for a non-email or nonexistent id.
- `POST /actions/{id}/send` with `view=emails`: route test — htmx response re-renders the detail partial (no `<html>`, no `<nav>`, contains the interaction's subject and NOT the reply form since the action is now closed); non-htmx fallback redirects to `/emails/{interaction_id}` instead of `/action-center`. Existing Action-Center-originated send tests (no `view` field) must keep passing unmodified — this is an additive, opt-in branch.

## Self-Review Notes

- **Explicitly out of scope:** raw body storage, Regenerate/Not-relevant, live mail fetch, thread grouping (list is flat, one row per interaction, matching the existing global Interactions feed's precedent).
- **Consistency check:** the `send_reply` route's behavior for existing callers (Action Center's htmx/non-htmx paths) is unchanged when `view` is absent — the new branch is strictly additive, gated on an opt-in form field.
