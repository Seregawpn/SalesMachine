from fastapi import APIRouter, Request

from project_os.db import get_connection
from project_os.repositories.interactions import list_interactions

router = APIRouter()


@router.get("/interactions")
def interactions_index(request: Request):
    conn = get_connection(request.app.state.db_path)
    try:
        interactions = list_interactions(conn)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request, "interactions_index.html", {"interactions": interactions}
    )
