from fastapi import APIRouter

from app.api.routes.crud import register_crud_routes
from app.models.ai import Agent, Guardrail, KnowledgeSource, Prompt, RuntimeProfile, Workflow
from app.repositories.base import Repository
from app.schemas.ai import (
    AgentCreate,
    AgentRead,
    AgentUpdate,
    KnowledgeSourceCreate,
    KnowledgeSourceRead,
    KnowledgeSourceUpdate,
    PromptCreate,
    PromptRead,
    PromptUpdate,
    RuleCreate,
    RuleRead,
    RuleUpdate,
    RuntimeProfileCreate,
    RuntimeProfileRead,
    RuntimeProfileUpdate,
    WorkflowCreate,
    WorkflowRead,
    WorkflowUpdate,
)
from app.services.base import CRUDService

router = APIRouter(prefix="/ai", tags=["ai"])

register_crud_routes(
    router, "/prompts", "prompt", CRUDService(Repository(Prompt)), PromptCreate, PromptUpdate, PromptRead
)
register_crud_routes(router, "/agents", "agent", CRUDService(Repository(Agent)), AgentCreate, AgentUpdate, AgentRead)
register_crud_routes(
    router,
    "/knowledge-sources",
    "knowledge source",
    CRUDService(Repository(KnowledgeSource)),
    KnowledgeSourceCreate,
    KnowledgeSourceUpdate,
    KnowledgeSourceRead,
)
register_crud_routes(
    router, "/guardrails", "guardrail", CRUDService(Repository(Guardrail)), RuleCreate, RuleUpdate, RuleRead
)
register_crud_routes(
    router, "/workflows", "workflow", CRUDService(Repository(Workflow)), WorkflowCreate, WorkflowUpdate, WorkflowRead
)
register_crud_routes(
    router,
    "/runtime-profiles",
    "runtime profile",
    CRUDService(Repository(RuntimeProfile)),
    RuntimeProfileCreate,
    RuntimeProfileUpdate,
    RuntimeProfileRead,
)
