from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.api.dependencies.authentication import require_full_access_principal
from app.api.routes.auth import router as auth_router
from app.api.routes.installation_setup import router as installation_setup_router
from app.core.config import get_settings
from app.core.platform_metadata import PlatformBuildInfo, build_platform_info
from app.db.session import SessionLocal
from app.identity.db import IdentitySessionLocal
from app.schemas.dependency_health import DependencyHealthResponse, ReadinessResponse
from app.schemas.effective_configuration import EffectivePlatformConfiguration
from app.schemas.platform_health import PlatformHealthResponse
from app.services.configuration_preflight import build_configuration_preflight, production_preflight_required
from app.services.configuration_revision import resolve_configuration_revision
from app.services.correlation_context import CorrelationIdMiddleware
from app.services.database_revision import resolve_database_revision
from app.services.dependency_health import build_readiness, evaluate_dependency_health
from app.services.effective_configuration import resolve_effective_configuration
from app.services.platform_health import evaluate_platform_health
from app.services.runtime_dependency_recovery import RuntimeDependencyRecovery
from app.services.schema_compatibility import assert_database_schema_compatible
from app.security.tenant_session import TenantSessionBoundaryViolation

settings = get_settings()


def validate_database_schema(application: FastAPI) -> None:
    recovery = RuntimeDependencyRecovery(
        initial_delay_seconds=max(0.1, settings.startup_dependency_retry_seconds),
        maximum_delay_seconds=max(0.1, settings.startup_dependency_retry_seconds),
        multiplier=1.0,
    )
    attempts = max(1, settings.startup_dependency_max_attempts)
    for attempt in range(attempts):
        try:
            assert_database_schema_compatible(settings.database_url)
            if production_preflight_required():
                session = SessionLocal()
                try:
                    preflight = build_configuration_preflight("production", db=session, probe_dependencies=True)
                finally:
                    session.close()
                application.state.production_preflight = preflight
                if preflight.status != "passed":
                    raise RuntimeError("production configuration preflight failed")
            return
        except SQLAlchemyError as exc:
            if attempt + 1 >= attempts:
                application.state.platform_startup_error = type(exc).__name__
                return
            recovery.wait()
        except RuntimeError as exc:
            if str(exc) == "database url is not configured":
                application.state.platform_startup_error = type(exc).__name__
                return
            raise


@asynccontextmanager
async def lifespan(application: FastAPI):
    validate_database_schema(application)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/docs" if settings.api_docs_enabled else None,
    redoc_url="/redoc" if settings.api_docs_enabled else None,
    openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    lifespan=lifespan,
)
app.add_middleware(CorrelationIdMiddleware)
if settings.trusted_host_list:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router)
app.include_router(auth_router)
app.include_router(installation_setup_router)


@app.exception_handler(TenantSessionBoundaryViolation)
def handle_tenant_boundary_error(
    _: Request, __: TenantSessionBoundaryViolation
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": "organization_scope_violation"},
    )


@app.exception_handler(SQLAlchemyError)
def handle_persistence_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    if request.url.path.startswith("/auth"):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "identity_service_unavailable"},
        )
    if isinstance(exc, OperationalError):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "platform_service_unavailable"},
        )
    if isinstance(exc, IntegrityError):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "runtime_persistence_conflict"},
        )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "runtime_persistence_error"},
    )


def _platform_info() -> PlatformBuildInfo:
    session = SessionLocal() if SessionLocal is not None else None
    try:
        return build_platform_info(settings).model_copy(
            update={
                "database_revision": resolve_database_revision(session),
                "configuration_revision": resolve_configuration_revision(settings),
            }
        )
    finally:
        if session is not None:
            session.close()


def _effective_configuration() -> EffectivePlatformConfiguration:
    session = SessionLocal() if SessionLocal is not None else None
    try:
        return resolve_effective_configuration(
            settings,
            database_revision=resolve_database_revision(session),
            configuration_revision=resolve_configuration_revision(settings),
        )
    finally:
        if session is not None:
            session.close()


def _dependency_health() -> DependencyHealthResponse:
    session = SessionLocal() if SessionLocal is not None else None
    identity_session = IdentitySessionLocal() if IdentitySessionLocal is not None else None
    try:
        return evaluate_dependency_health(
            session,
            settings,
            identity_session=identity_session,
        )
    finally:
        if session is not None:
            session.close()
        if identity_session is not None:
            identity_session.close()


def _platform_health() -> PlatformHealthResponse:
    session = SessionLocal() if SessionLocal is not None else None
    try:
        return evaluate_platform_health(session)
    finally:
        if session is not None:
            session.close()


@app.get("/health")
@app.get("/health/live")
def health() -> dict[str, str]:
    return {"status": "ok", "lifecycle_state": "alive"}


@app.get("/health/ready", response_model=ReadinessResponse)
def readiness(response: Response) -> ReadinessResponse:
    snapshot = build_readiness(_dependency_health())
    if snapshot.status != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return snapshot


@app.get(
    "/health/dependencies",
    response_model=DependencyHealthResponse,
    dependencies=[Depends(require_full_access_principal)],
)
def dependency_health(response: Response) -> DependencyHealthResponse:
    snapshot = _dependency_health()
    if snapshot.status == "critical":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return snapshot


@app.get(
    "/health/platform",
    response_model=PlatformHealthResponse,
    dependencies=[Depends(require_full_access_principal)],
)
def platform_health(response: Response) -> PlatformHealthResponse:
    snapshot = _platform_health()
    if snapshot.status == "critical":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return snapshot


@app.get("/", dependencies=[Depends(require_full_access_principal)])
def root() -> dict[str, str]:
    return {"service": "industrial-ai-platform-api"}


@app.get(
    "/platform/status",
    response_model=PlatformBuildInfo,
    dependencies=[Depends(require_full_access_principal)],
)
def platform_status() -> PlatformBuildInfo:
    return _platform_info()


@app.get(
    "/platform/configuration",
    response_model=EffectivePlatformConfiguration,
    dependencies=[Depends(require_full_access_principal)],
)
def platform_configuration() -> EffectivePlatformConfiguration:
    return _effective_configuration()


@app.get("/platform/foundation", dependencies=[Depends(require_full_access_principal)])
def platform_foundation() -> dict[str, object]:
    return _platform_info().model_dump(mode="json")
