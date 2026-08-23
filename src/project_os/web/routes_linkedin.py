from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse

from project_os.db import get_connection
from project_os.repositories.linkedin import list_linkedin_queue, set_linkedin_state

router = APIRouter()


@router.get("/projects/{project_id}/linkedin")
def linkedin_queue(request: Request, project_id: int):
    conn = get_connection(request.app.state.db_path)
    try:
        queue = list_linkedin_queue(conn, project_id)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request,
        "linkedin_queue.html",
        {"project_id": project_id, "queue": queue},
    )


@router.post("/projects/{project_id}/linkedin/{project_contact_id}/state")
def update_linkedin_state(request: Request, project_id: int, project_contact_id: int, state: str = Form(...)):
    conn = get_connection(request.app.state.db_path)
    try:
        set_linkedin_state(conn, project_contact_id, state, project_id=project_id, actor="user")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()
    return RedirectResponse(url=f"/projects/{project_id}/linkedin", status_code=303)
