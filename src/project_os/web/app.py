from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from project_os.db import get_connection, run_migrations

WEB_DIR = Path(__file__).parent
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


def create_app(db_path: str) -> FastAPI:
    app = FastAPI(title="Project OS")
    app.state.db_path = db_path
    app.state.templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    conn = get_connection(db_path)
    run_migrations(conn, MIGRATIONS_DIR)
    conn.close()

    from project_os.web.routes_action_center import router as action_center_router
    app.include_router(action_center_router)

    from project_os.web.routes_projects import router as projects_router
    from project_os.web.routes_pipeline import router as pipeline_router
    app.include_router(projects_router)
    app.include_router(pipeline_router)

    return app


def get_db(request):
    return get_connection(request.app.state.db_path)
