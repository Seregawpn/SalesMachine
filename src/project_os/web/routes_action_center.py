from urllib.parse import quote

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from project_os.db import get_connection
from project_os.repositories.actions import list_open_actions, complete_action, snooze_action, get_reply_context
from project_os.repositories.opportunities import count_opportunities_by_stage
from project_os.repositories.interactions import create_interaction
from project_os.ai.mail_send_mcp_server import send_via_jxa, MailSendError
from project_os.web.routes_emails import render_email_detail

router = APIRouter()


def _is_hx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def _render_action_row(request: Request, conn, action_id: int):
    action_row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
    reply = get_reply_context(conn, action_id)
    return request.app.state.templates.get_template("_action_row.html").render(
        {"action": action_row, "reply_contexts": {action_id: reply}}
    )


def _render_flash_banner(request: Request, error_message: str) -> str:
    return request.app.state.templates.get_template("_flash_banner.html").render({"error": error_message})


_BANNER_RESET = '<p id="flash-banner" role="alert" class="flash-error" hx-swap-oob="true" hidden></p>'


@router.get("/action-center")
def action_center(request: Request):
    conn = get_connection(request.app.state.db_path)
    try:
        actions = list_open_actions(conn)
        reply_contexts = {action["id"]: get_reply_context(conn, action["id"]) for action in actions}
        funnel = count_opportunities_by_stage(conn)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request, "action_center.html",
        {
            "actions": actions,
            "reply_contexts": reply_contexts,
            "error": request.query_params.get("error"),
            "funnel": funnel,
        },
    )


@router.post("/actions/{action_id}/complete")
def complete(request: Request, action_id: int):
    conn = get_connection(request.app.state.db_path)
    try:
        complete_action(conn, action_id)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()
    if _is_hx(request):
        return HTMLResponse(_BANNER_RESET)
    return RedirectResponse(url="/action-center", status_code=303)


@router.post("/actions/{action_id}/snooze")
def snooze(request: Request, action_id: int, new_due_date: str = Form(...)):
    conn = get_connection(request.app.state.db_path)
    try:
        snooze_action(conn, action_id, new_due_date)
        if _is_hx(request):
            return HTMLResponse(_render_action_row(request, conn, action_id))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()
    return RedirectResponse(url="/action-center", status_code=303)


@router.post("/actions/{action_id}/send")
def send_reply(request: Request, action_id: int, message: str = Form(...), view: str | None = Form(None)):
    conn = get_connection(request.app.state.db_path)
    is_hx = _is_hx(request)
    from_emails = view == "emails"
    try:
        context = get_reply_context(conn, action_id)
        if context is None:
            raise HTTPException(status_code=404, detail=f"No sendable reply for action {action_id}")

        action_row = conn.execute(
            "SELECT project_id, linked_id, source_interaction_id FROM actions WHERE id = ?", (action_id,)
        ).fetchone()
        redirect_url = f"/emails/{action_row['source_interaction_id']}" if from_emails else "/action-center"

        if not message.strip():
            if is_hx:
                response = HTMLResponse(_render_flash_banner(request, "Reply text cannot be empty."))
                response.headers["HX-Reswap"] = "none"
                return response
            return RedirectResponse(
                url=f"{redirect_url}?error=Reply text cannot be empty.", status_code=303
            )

        try:
            send_via_jxa({"to": context["to"], "subject": context["subject"], "body": message})
        except Exception as error:
            if is_hx:
                response = HTMLResponse(_render_flash_banner(request, str(error)))
                response.headers["HX-Reswap"] = "none"
                return response
            return RedirectResponse(
                url=f"{redirect_url}?error={quote(str(error))}", status_code=303
            )

        conn.execute("BEGIN")
        try:
            complete_action(conn, action_id)
            create_interaction(
                conn, action_row["project_id"], action_row["linked_id"],
                channel="email", direction="outbound", subject=context["subject"],
                ai_summary=None, intent=None, external_message_id=None,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        if is_hx:
            if from_emails:
                return HTMLResponse(render_email_detail(request, conn, action_row["source_interaction_id"]))
            return HTMLResponse(_BANNER_RESET)
    finally:
        conn.close()
    return RedirectResponse(url=redirect_url, status_code=303)
