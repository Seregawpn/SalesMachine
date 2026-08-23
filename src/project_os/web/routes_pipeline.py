from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import RedirectResponse

from project_os.db import get_connection
from project_os.repositories.opportunities import list_pipeline, update_stage
from project_os.pipeline import STAGES

router = APIRouter()


@router.get("/projects/{project_id}/pipeline")
def pipeline(request: Request, project_id: int):
    conn = get_connection(request.app.state.db_path)
    try:
        opportunities = list_pipeline(conn, project_id)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request,
        "pipeline.html",
        {"project_id": project_id, "opportunities": opportunities, "stages": STAGES},
    )


@router.post("/projects/{project_id}/pipeline/{opportunity_id}/stage")
def change_stage(request: Request, project_id: int, opportunity_id: int, stage: str = Form(...)):
    conn = get_connection(request.app.state.db_path)
    try:
        update_stage(conn, opportunity_id, stage, project_id=project_id, actor="user")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        conn.close()
    return RedirectResponse(url=f"/projects/{project_id}/pipeline", status_code=303)
