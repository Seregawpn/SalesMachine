from fastapi import APIRouter, Request, HTTPException

from project_os.db import get_connection
from project_os.repositories.projects import get_project
from project_os.repositories.actions import list_open_actions

router = APIRouter()

_HIGH_PRIORITY = {"P0", "P1"}


@router.get("/projects/{project_id}")
def project_overview(request: Request, project_id: int):
    conn = get_connection(request.app.state.db_path)
    project = get_project(conn, project_id)
    if project is None:
        conn.close()
        raise HTTPException(status_code=404, detail=f"No project with id {project_id}")
    actions = list_open_actions(conn, project_id)
    conn.close()

    needs_attention = [a for a in actions if a["priority"] in _HIGH_PRIORITY]

    return request.app.state.templates.TemplateResponse(
        request,
        "project_overview.html",
        {"project": project, "needs_attention": needs_attention},
    )
