# Approve & Send for Mail Replies — Design

**Goal:** Close the loop that `Mail Sync → CRM` opened. `sync_mail_replies` already writes a suggested reply into `actions.suggested_message`, but nothing in Project OS can actually send it — a human has to leave the app, open Apple Mail, and reply by hand. This adds an "Approve & Send" action to the Action Center: review the AI-drafted reply, edit it if needed, and send it through Apple Mail directly from the web UI. The action is then closed and the sent reply is recorded as an outbound interaction, so the CRM's conversation history stays complete in both directions.

**Non-goals:** This does not touch scheduling/calendar, does not add a rich-text editor, does not send anything without an explicit human click, and does not change how `mail_sync` classifies or drafts replies.

## Architecture

`POST /actions/{id}/send` is a new route in `routes_action_center.py`. Sending an already-approved, already-drafted reply needs no AI call — it is a direct call to Apple Mail via JXA, reusing the same `send_via_jxa` function `mail_send_mcp_server.py` already exposes for Codex's `send_message` MCP tool. That function is renamed from `_send_via_jxa` to `send_via_jxa` (dropping the underscore) so both the MCP tool path (for Codex) and this new direct path (for a human's approved click) can call it without going through the MCP JSON-RPC envelope.

Flow: the Action Center form submits the (possibly edited) draft text → the route re-validates the action is still sendable → calls `send_via_jxa` → on success, closes the action and records an outbound `interaction` in one transaction → redirects back to `/action-center`. On failure, the action stays `Open` with its draft intact, and the page shows a flash error so the human can retry.

## Data Model

New migration `0004_action_source_interaction.sql`:

```sql
ALTER TABLE actions ADD COLUMN source_interaction_id INTEGER REFERENCES interactions(id);
```

`actions` currently has no link back to the specific inbound message that prompted it — only `linked_table='contacts'` / `linked_id=<contact_id>`. Without knowing which interaction the draft is replying to, there is no reliable `Re: <subject>` to send. `mail_sync.sync_mail_replies` already creates the inbound `interaction` row before calling `create_action`; it now passes that row's id through as `source_interaction_id`.

`create_action` in `repositories/actions.py` gains an optional `source_interaction_id: int | None = None` parameter, stored alongside the existing columns.

Actions created before this migration, or created by anything other than `mail_sync`, will have `source_interaction_id IS NULL` — for those, "Approve & Send" simply does not appear. No backfill, no fallback subject-guessing.

## Backend

**`repositories/actions.py` — `get_reply_context(conn, action_id) -> dict | None`:**

Joins `actions` → `contacts` (via `linked_id`, requires `linked_table = 'contacts'`) → `interactions` (via `source_interaction_id`). Returns `None` unless all of these hold:
- the action is `Open`
- `linked_table = 'contacts'` and the contact exists
- `suggested_message` is non-empty
- `source_interaction_id` is set and the interaction exists
- the contact's `email` is non-empty

On success, returns `{"to": contact.email, "subject": "Re: " + interaction.subject, "body": action.suggested_message}`.

**`mail_send_mcp_server.py`:** rename `_send_via_jxa` → `send_via_jxa` (public). No behavior change — still takes `{to, subject, body}` and an injectable `runner` for tests, still raises `MailSendError` on non-zero exit.

**`routes_action_center.py` — `POST /actions/{id}/send`:**

- Form field: `message` (the textarea's current content — the human's possibly-edited version of the draft, not necessarily what's still in the DB).
- Re-fetches `get_reply_context` fresh (not trusting hidden form fields) to get `to`/`subject`, and guards against a stale/tampered/already-sent action: 404 if the context is no longer valid (action already completed, or preconditions no longer hold).
- Calls `send_via_jxa(to=context["to"], subject=context["subject"], body=message)`.
- On success, in one transaction: `complete_action(conn, action_id)` and `create_interaction(conn, project_id, contact_id, channel="email", direction="outbound", subject=context["subject"], ai_summary=None, intent=None, external_message_id=None)`. Commit, then `RedirectResponse("/action-center", status_code=303)`.
- On `MailSendError`, no DB write happens (send failed before any commit) — redirect to `/action-center?error=<url-encoded message>` with the action left untouched (still `Open`, draft still there for another attempt).

## UI

**`action_center.html`:** in the existing "Action" table cell, alongside the Done/Snooze forms, actions with a non-`None` `get_reply_context` get a collapsed `<details><summary>Reply draft ▾</summary>…</details>` block (native HTML, no JS) containing:
- a `<textarea name="message">` pre-filled with `context["body"]`, editable before sending
- a submit button "Approve & Send" posting to `/actions/{id}/send`

The route computes `get_reply_context` per row when rendering the list (same N+1-is-fine pattern the rest of this codebase already uses at this data scale — no premature batching).

A flash banner appears at the top of the page when `request.query_params.get("error")` is present, showing the error text and nothing else persistent (it's just a query param, not stored state).

## Testing

- `tests/test_actions_repo.py`: `get_reply_context` — happy path; `source_interaction_id IS NULL`; contact has no email; `suggested_message IS NULL`; action not `Open`.
- `tests/test_action_center_routes.py`: successful send (mocked `send_via_jxa`) closes the action and inserts the outbound interaction, 303 redirect; send failure leaves the action `Open`, writes nothing, redirects with `?error=`; sending an action with no valid reply context 404s.
- `tests/test_mail_send_mcp_server.py`: update the import from `_send_via_jxa` to `send_via_jxa`.
- `tests/test_mail_sync.py`: assert `sync_mail_replies` populates `source_interaction_id` on the created action.

No test spawns real Apple Mail or JXA — `send_via_jxa` is always exercised through its injectable `runner`, matching the existing pattern in `mail_send_mcp_server.py`'s tests.
