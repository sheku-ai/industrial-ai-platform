from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import event, or_
from sqlalchemy.orm import Session, with_loader_criteria

from app.db.base import Base
from app.models.core import Organization

TENANT_SCOPE_KEY = "authorized_organization_id"
TENANT_BOUNDARY_CONFIGURED = False


class TenantSessionBoundaryViolation(RuntimeError):
    pass


def authorize_session_organization(session: Session, organization_id: UUID | None) -> None:
    if organization_id is None:
        session.info.pop(TENANT_SCOPE_KEY, None)
    else:
        session.info[TENANT_SCOPE_KEY] = organization_id


def _criterion_for(model: type[Any], organization_id: UUID):
    if model is Organization:
        return model.id == organization_id
    column = model.organization_id
    mapped_column = model.__mapper__.columns.get("organization_id")
    if mapped_column is not None and mapped_column.nullable:
        return or_(column == organization_id, column.is_(None))
    return column == organization_id


def configure_tenant_session_boundary() -> None:
    global TENANT_BOUNDARY_CONFIGURED
    if TENANT_BOUNDARY_CONFIGURED:
        return

    @event.listens_for(Session, "do_orm_execute")
    def _apply_organization_boundary(execute_state) -> None:
        organization_id = execute_state.session.info.get(TENANT_SCOPE_KEY)
        if organization_id is None:
            return
        if not execute_state.is_orm_statement:
            return

        if execute_state.is_select:
            statement = execute_state.statement
            for mapper in tuple(Base.registry.mappers):
                model = mapper.class_
                if model is not Organization and not hasattr(model, "organization_id"):
                    continue
                statement = statement.options(
                    with_loader_criteria(
                        model,
                        _criterion_for(model, organization_id),
                        include_aliases=True,
                    )
                )
            execute_state.statement = statement
            return

        if execute_state.is_update or execute_state.is_delete:
            mapper = execute_state.bind_arguments.get("mapper")
            model = mapper.class_ if mapper is not None else None
            if model is Organization or (model is not None and hasattr(model, "organization_id")):
                execute_state.statement = execute_state.statement.where(_criterion_for(model, organization_id))

    @event.listens_for(Session, "before_flush")
    def _enforce_organization_writes(session, _flush_context, _instances) -> None:
        organization_id = session.info.get(TENANT_SCOPE_KEY)
        if organization_id is None:
            return
        for item in tuple(session.new):
            if isinstance(item, Organization):
                raise TenantSessionBoundaryViolation("organization creation requires platform scope")
            if not hasattr(item, "organization_id"):
                continue
            current = item.organization_id
            if current is None:
                item.organization_id = organization_id
            elif current != organization_id:
                raise TenantSessionBoundaryViolation("entity organization does not match authenticated scope")
        for item in tuple(session.dirty) + tuple(session.deleted):
            if isinstance(item, Organization):
                if item.id != organization_id:
                    raise TenantSessionBoundaryViolation("organization is outside authenticated scope")
                continue
            if not hasattr(item, "organization_id"):
                continue
            if item.organization_id != organization_id:
                raise TenantSessionBoundaryViolation("entity is outside authenticated write scope")

    TENANT_BOUNDARY_CONFIGURED = True
