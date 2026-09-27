"""Stable page IDs with task-oriented navigation labels."""

PAGE_LABELS = {
    "Dashboard": "Visão geral",
    "Runbooks": "Procedimentos",
    "Editor": "Editor visual",
    "Execute": "Executar",
    "Executions": "Execuções",
    "Approvals": "Aprovações",
    "Audit": "Auditoria",
    "Resources": "Recursos AWS",
    "Catalog": "Catálogo de ações",
    "Guide": "Guia passo a passo",
}

AREAS = {
    "Todas as áreas": tuple(PAGE_LABELS),
    "Criar e editar": ("Dashboard", "Runbooks", "Editor"),
    "Operar": ("Dashboard", "Execute", "Executions", "Approvals"),
    "Consultar": ("Dashboard", "Resources", "Catalog", "Audit", "Guide"),
}


def navigation_pages(area: str) -> list[str]:
    return list(AREAS.get(area, AREAS["Todas as áreas"]))
