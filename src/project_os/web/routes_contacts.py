from fastapi import APIRouter, Request

from project_os.db import get_connection
from project_os.repositories.contacts import list_companies_with_contacts

router = APIRouter()


@router.get("/contacts")
def contacts_index(request: Request):
    conn = get_connection(request.app.state.db_path)
    try:
        companies = list_companies_with_contacts(conn)
    finally:
        conn.close()
    return request.app.state.templates.TemplateResponse(
        request, "contacts_index.html", {"companies": companies}
    )
