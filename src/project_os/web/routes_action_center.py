from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from project_os.db import get_connection
from project_os.repositories.actions import list_open_actions, complete_action, snooze_action

router = APIRouter()


@router.get("/action-center")
def action_center(request: Request):
    conn = get_connection(request.app.state.db_path)
    actions = list_open_actions(conn)
    conn.close()
    return request.app.state.templates.TemplateResponse(
        request, "action_center.html", {"actions": actions}
    )


@router.post("/actions/{action_id}/complete")
def complete(request: Request, action_id: int):
    conn = get_connection(request.app.state.db_path)
    complete_action(conn, action_id)
    conn.close()
    return RedirectResponse(url="/action-center", status_code=303)


@router.post("/actions/{action_id}/snooze")
def snooze(request: Request, action_id: int, new_due_date: str):
    conn = get_connection(request.app.state.db_path)
    snooze_action(conn, action_id, new_due_date)
    conn.close()
    return RedirectResponse(url="/action-center", status_code=303)
