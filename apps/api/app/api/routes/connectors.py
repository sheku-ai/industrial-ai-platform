from fastapi import APIRouter

from app.api.routes.crud import register_crud_routes
from app.models.connectors import Connector, ConnectorConfig, ConnectorRun, ConnectorType
from app.repositories.base import Repository
from app.schemas.connectors import (
    ConnectorConfigCreate,
    ConnectorConfigRead,
    ConnectorConfigUpdate,
    ConnectorCreate,
    ConnectorRead,
    ConnectorRunCreate,
    ConnectorRunRead,
    ConnectorRunUpdate,
    ConnectorTypeCreate,
    ConnectorTypeRead,
    ConnectorTypeUpdate,
    ConnectorUpdate,
)
from app.services.base import CRUDService

router = APIRouter(prefix="/connectors", tags=["connectors"])

register_crud_routes(
    router,
    "/connector-types",
    "connector type",
    CRUDService(Repository(ConnectorType)),
    ConnectorTypeCreate,
    ConnectorTypeUpdate,
    ConnectorTypeRead,
)
register_crud_routes(
    router,
    "/connectors",
    "connector",
    CRUDService(Repository(Connector)),
    ConnectorCreate,
    ConnectorUpdate,
    ConnectorRead,
)
register_crud_routes(
    router,
    "/connector-configs",
    "connector config",
    CRUDService(Repository(ConnectorConfig)),
    ConnectorConfigCreate,
    ConnectorConfigUpdate,
    ConnectorConfigRead,
)
register_crud_routes(
    router,
    "/connector-runs",
    "connector run",
    CRUDService(Repository(ConnectorRun)),
    ConnectorRunCreate,
    ConnectorRunUpdate,
    ConnectorRunRead,
)
