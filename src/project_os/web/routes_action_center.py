from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse

from project_os.db import get_connection
from project_os.repositories.actions import list_open_actions, complete_action, snooze_action

router = APIRouter()


@router.get("/action-center")
def action_center(request: Request):
    conn = get_connection(request.app.state.db_path)
    try:
        actions = list_open_actions(conn)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request, "action_center.html", {"actions": actions}
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
    return RedirectResponse(url="/action-center", status_code=303)


@router.post("/actions/{action_id}/snooze")
def snooze(request: Request, action_id: int, new_due_date: str = Form(...)):
    conn = get_connection(request.app.state.db_path)
    try:
        snooze_action(conn, action_id, new_due_date)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()
    return RedirectResponse(url="/action-center", status_code=303)
