from fastapi import APIRouter, HTTPException, Request

from project_os.db import get_connection
from project_os.repositories.interactions import list_email_interactions

router = APIRouter()


def _select(interactions: list, interaction_id: int | None):
    if interaction_id is None:
        return interactions[0] if interactions else None
    selected = next((i for i in interactions if i["id"] == interaction_id), None)
    if selected is None:
        raise HTTPException(status_code=404, detail=f"No email interaction with id {interaction_id}")
    return selected


def render_email_detail(request: Request, conn, interaction_id: int) -> str:
    interactions = list_email_interactions(conn)
    selected = _select(interactions, interaction_id)
    return request.app.state.templates.get_template("_email_detail.html").render(
        {"selected": selected}
    )


@router.get("/emails")
def emails_index(request: Request):
    conn = get_connection(request.app.state.db_path)
    try:
        interactions = list_email_interactions(conn)
        selected = _select(interactions, None)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request, "emails_index.html",
        {"interactions": interactions, "selected": selected, "error": request.query_params.get("error")},
    )


@router.get("/emails/{interaction_id}")
def emails_show(request: Request, interaction_id: int):
    conn = get_connection(request.app.state.db_path)
    try:
        interactions = list_email_interactions(conn)
        selected = _select(interactions, interaction_id)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request, "emails_index.html",
        {"interactions": interactions, "selected": selected, "error": request.query_params.get("error")},
    )
