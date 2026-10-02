from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session

from app.security.context import ActorScope, RequestContext


class RepositoryBoundaryError(RuntimeError):
    pass


class TenantContextRequired(RepositoryBoundaryError):
    pass


class PlatformContextRequired(RepositoryBoundaryError):
    pass


class TenantBoundaryViolation(RepositoryBoundaryError):
    pass


def _mapper_for(model: type[object]) -> Any:
    mapper = inspect(model)
    if mapper is None:
        raise RepositoryBoundaryError("model is not SQLAlchemy-mapped")
    return mapper


def _mapped_columns(model: type[object]) -> dict[str, object]:
    mapper = _mapper_for(model)
    return {column.key: column for column in mapper.columns}


def _primary_key_attribute[ModelT](model: type[ModelT]) -> Any:
    mapper = _mapper_for(model)
    primary_keys = list(mapper.primary_key)
    if len(primary_keys) != 1:
        raise RepositoryBoundaryError("repository models require one primary key column")
    return getattr(model, primary_keys[0].key)


class TenantScopedRepository[ModelT]:
    def __init__(self, model: type[ModelT]) -> None:
        columns = _mapped_columns(model)
        if "organization_id" not in columns:
            raise RepositoryBoundaryError("tenant-scoped model requires organization_id")
        self.model = model
        self._primary_key = _primary_key_attribute(model)
        self._organization_id = cast(Any, model).organization_id

    @staticmethod
    def _organization_id_from(context: RequestContext) -> uuid.UUID:
        if context.actor.scope != ActorScope.ORGANIZATION or context.organization is None:
            raise TenantContextRequired("organization-scoped repository requires organization context")
        return context.organization.organization_id

    def list(
        self,
        db: Session,
        context: RequestContext,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ModelT]:
        organization_id = self._organization_id_from(context)
        statement = select(self.model).where(self._organization_id == organization_id).offset(skip).limit(limit)
        return list(db.scalars(statement).all())

    def get(self, db: Session, context: RequestContext, item_id: uuid.UUID) -> ModelT | None:
        organization_id = self._organization_id_from(context)
        statement = select(self.model).where(
            self._primary_key == item_id,
            self._organization_id == organization_id,
        )
        return db.scalar(statement)

    def create(self, db: Session, context: RequestContext, data: dict) -> ModelT:
        organization_id = self._organization_id_from(context)
        supplied = data.get("organization_id")
        if supplied is not None and supplied != organization_id:
            raise TenantBoundaryViolation("organization_id does not match request context")
        item = self.model(**{**data, "organization_id": organization_id})
        db.add(item)
        db.flush()
        return item

    def update(self, db: Session, context: RequestContext, item: ModelT, data: dict) -> ModelT:
        organization_id = self._organization_id_from(context)
        if getattr(item, "organization_id", None) != organization_id:
            raise TenantBoundaryViolation("entity is outside request organization")
        supplied = data.get("organization_id")
        if supplied is not None and supplied != organization_id:
            raise TenantBoundaryViolation("organization_id cannot be changed")
        for key, value in data.items():
            if key != "organization_id":
                setattr(item, key, value)
        db.add(item)
        db.flush()
        return item

    def delete(self, db: Session, context: RequestContext, item: ModelT) -> None:
        organization_id = self._organization_id_from(context)
        if getattr(item, "organization_id", None) != organization_id:
            raise TenantBoundaryViolation("entity is outside request organization")
        db.delete(item)
        db.flush()


class GlobalPlatformRepository[ModelT]:
    def __init__(self, model: type[ModelT]) -> None:
        columns = _mapped_columns(model)
        if "organization_id" in columns:
            raise RepositoryBoundaryError("global model must not contain organization_id")
        self.model = model
        self._primary_key = _primary_key_attribute(model)

    @staticmethod
    def _require_platform_scope(context: RequestContext) -> None:
        if context.actor.scope != ActorScope.PLATFORM or context.organization is not None:
            raise PlatformContextRequired("global repository requires platform-scoped context")

    def list(self, db: Session, context: RequestContext, *, skip: int = 0, limit: int = 100) -> list[ModelT]:
        self._require_platform_scope(context)
        return list(db.scalars(select(self.model).offset(skip).limit(limit)).all())

    def get(self, db: Session, context: RequestContext, item_id: uuid.UUID) -> ModelT | None:
        self._require_platform_scope(context)
        return db.scalar(select(self.model).where(self._primary_key == item_id))

    def create(self, db: Session, context: RequestContext, data: dict) -> ModelT:
        self._require_platform_scope(context)
        item = self.model(**data)
        db.add(item)
        db.flush()
        return item


class SharedSystemRepository[ModelT]:
    def __init__(self, model: type[ModelT]) -> None:
        columns = _mapped_columns(model)
        organization_column = columns.get("organization_id")
        if organization_column is None:
            raise RepositoryBoundaryError("shared-system model requires organization_id")
        if not getattr(organization_column, "nullable", False):
            raise RepositoryBoundaryError("shared-system organization_id must be nullable")
        self.model = model
        self._primary_key = _primary_key_attribute(model)
        self._organization_id = cast(Any, model).organization_id

    def list(self, db: Session, context: RequestContext, *, skip: int = 0, limit: int = 100) -> list[ModelT]:
        if context.actor.scope == ActorScope.PLATFORM:
            predicate = self._organization_id.is_(None)
        else:
            if context.organization is None:
                raise TenantContextRequired("shared repository requires resolved organization context")
            predicate = or_(
                self._organization_id.is_(None),
                self._organization_id == context.organization.organization_id,
            )
        return list(db.scalars(select(self.model).where(predicate).offset(skip).limit(limit)).all())

    def get(self, db: Session, context: RequestContext, item_id: uuid.UUID) -> ModelT | None:
        if context.actor.scope == ActorScope.PLATFORM:
            predicate = self._organization_id.is_(None)
        else:
            if context.organization is None:
                raise TenantContextRequired("shared repository requires resolved organization context")
            predicate = or_(
                self._organization_id.is_(None),
                self._organization_id == context.organization.organization_id,
            )
        return db.scalar(select(self.model).where(self._primary_key == item_id, predicate))

    def create(self, db: Session, context: RequestContext, data: dict) -> ModelT:
        expected_organization_id = None
        if context.actor.scope == ActorScope.ORGANIZATION:
            if context.organization is None:
                raise TenantContextRequired("shared repository requires resolved organization context")
            expected_organization_id = context.organization.organization_id
        supplied = data.get("organization_id")
        if supplied is not None and supplied != expected_organization_id:
            raise TenantBoundaryViolation("organization_id does not match repository scope")
        item = self.model(**{**data, "organization_id": expected_organization_id})
        db.add(item)
        db.flush()
        return item

    def update(self, db: Session, context: RequestContext, item: ModelT, data: dict) -> ModelT:
        expected_organization_id = None
        if context.actor.scope == ActorScope.ORGANIZATION:
            if context.organization is None:
                raise TenantContextRequired("shared repository requires resolved organization context")
            expected_organization_id = context.organization.organization_id
        if getattr(item, "organization_id", None) != expected_organization_id:
            raise TenantBoundaryViolation("entity is outside repository write scope")
        supplied = data.get("organization_id")
        if supplied is not None and supplied != expected_organization_id:
            raise TenantBoundaryViolation("organization_id cannot be changed")
        for key, value in data.items():
            if key != "organization_id":
                setattr(item, key, value)
        db.add(item)
        db.flush()
        return item

    def delete(self, db: Session, context: RequestContext, item: ModelT) -> None:
        expected_organization_id = None
        if context.actor.scope == ActorScope.ORGANIZATION:
            if context.organization is None:
                raise TenantContextRequired("shared repository requires resolved organization context")
            expected_organization_id = context.organization.organization_id
        if getattr(item, "organization_id", None) != expected_organization_id:
            raise TenantBoundaryViolation("entity is outside repository write scope")
        db.delete(item)
        db.flush()
