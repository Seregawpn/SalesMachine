from fastapi import APIRouter, Request, HTTPException

from project_os.db import get_connection
from project_os.repositories.projects import get_project, list_projects
from project_os.repositories.actions import list_open_actions

router = APIRouter()

_HIGH_PRIORITY = {"P0", "P1"}


@router.get("/projects")
def projects_index(request: Request):
    conn = get_connection(request.app.state.db_path)
    try:
        projects = list_projects(conn)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request, "projects_index.html", {"projects": projects}
    )


@router.get("/projects/{project_id}")
def project_overview(request: Request, project_id: int):
    conn = get_connection(request.app.state.db_path)
    try:
        project = get_project(conn, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"No project with id {project_id}")
        actions = list_open_actions(conn, project_id)
    finally:
        conn.close()

    needs_attention = [a for a in actions if a["priority"] in _HIGH_PRIORITY]

    return request.app.state.templates.TemplateResponse(
        request,
        "project_overview.html",
        {"project": project, "needs_attention": needs_attention},
    )
