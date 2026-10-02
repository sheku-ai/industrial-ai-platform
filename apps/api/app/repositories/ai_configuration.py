from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.models.ai import (
    Agent,
    Model,
    ModelProviderValidationEvidence,
    Provider,
    RuntimeProfile,
)


class AIConfigurationRepository:
    def __init__(self, db: Session, organization_id: uuid.UUID) -> None:
        self.db = db
        self.organization_id = organization_id

    def list_providers(
        self,
        *,
        enabled: bool | None = None,
        lifecycle_status: str | None = None,
    ) -> list[Provider]:
        statement = select(Provider).where(Provider.organization_id == self.organization_id)
        if enabled is not None:
            statement = statement.where(Provider.enabled.is_(enabled))
        if lifecycle_status is not None:
            statement = statement.where(Provider.lifecycle_status == lifecycle_status)
        return list(
            self.db.scalars(
                statement.order_by(Provider.display_name, Provider.provider_key)
            ).all()
        )

    def get_provider(
        self,
        provider_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> Provider | None:
        statement = select(Provider).where(
            Provider.id == provider_id,
            Provider.organization_id == self.organization_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.db.scalar(statement)

    def get_provider_by_key(self, provider_key: str) -> Provider | None:
        return self.db.scalar(
            select(Provider).where(
                Provider.organization_id == self.organization_id,
                Provider.provider_key == provider_key,
            )
        )

    def list_models(
        self,
        *,
        provider_id: uuid.UUID | None = None,
        capability: str | None = None,
        enabled: bool | None = None,
        lifecycle_status: str | None = None,
    ) -> list[Model]:
        statement = select(Model).where(
            Model.organization_id == self.organization_id,
            Model.provider_id.is_not(None),
            Model.model_key.is_not(None),
        )
        if provider_id is not None:
            statement = statement.where(Model.provider_id == provider_id)
        if capability is not None:
            statement = statement.where(Model.model_type == capability)
        if enabled is not None:
            statement = statement.where(Model.enabled.is_(enabled))
        if lifecycle_status is not None:
            statement = statement.where(Model.lifecycle_status == lifecycle_status)
        return list(
            self.db.scalars(
                statement.order_by(Model.display_name, Model.name, Model.model_key)
            ).all()
        )

    def get_model(
        self,
        model_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> Model | None:
        statement = select(Model).where(
            Model.id == model_id,
            Model.organization_id == self.organization_id,
            Model.provider_id.is_not(None),
            Model.model_key.is_not(None),
        )
        if for_update:
            statement = statement.with_for_update()
        return self.db.scalar(statement)

    def get_model_by_key(self, model_key: str) -> Model | None:
        return self.db.scalar(
            select(Model).where(
                Model.organization_id == self.organization_id,
                Model.model_key == model_key,
                Model.provider_id.is_not(None),
            )
        )

    def active_models_for_provider(self, provider_id: uuid.UUID) -> list[Model]:
        return list(
            self.db.scalars(
                select(Model).where(
                    Model.organization_id == self.organization_id,
                    Model.provider_id == provider_id,
                    Model.lifecycle_status == "active",
                )
            ).all()
        )

    def model_reference_count(self, model_id: uuid.UUID) -> int:
        agent_count = int(
            self.db.scalar(
                select(func.count(Agent.id)).where(
                    Agent.model_id == model_id,
                )
            )
            or 0
        )
        profile_count = int(
            self.db.scalar(
                select(func.count(RuntimeProfile.id)).where(
                    RuntimeProfile.model_id == model_id,
                )
            )
            or 0
        )
        return agent_count + profile_count

    def latest_evidence(
        self,
        *,
        provider_id: uuid.UUID | None = None,
        model_id: uuid.UUID | None = None,
    ) -> ModelProviderValidationEvidence | None:
        statement = select(ModelProviderValidationEvidence).where(
            ModelProviderValidationEvidence.organization_id == self.organization_id
        )
        if provider_id is not None:
            statement = statement.where(
                ModelProviderValidationEvidence.provider_id == provider_id
            )
        elif model_id is not None:
            statement = statement.where(
                ModelProviderValidationEvidence.model_id == model_id
            )
        else:
            raise ValueError("provider_id or model_id is required")
        return self.db.scalar(
            statement.order_by(
                ModelProviderValidationEvidence.evaluated_at.desc(),
                ModelProviderValidationEvidence.created_at.desc(),
                ModelProviderValidationEvidence.id.desc(),
            ).limit(1)
        )

    def clear_other_defaults(
        self,
        *,
        capability: str,
        default_scope: str,
        except_model_id: uuid.UUID | None = None,
    ) -> None:
        statement = (
            update(Model)
            .where(
                Model.organization_id == self.organization_id,
                Model.model_type == capability,
                Model.default_scope == default_scope,
                Model.is_default.is_(True),
            )
            .values(is_default=False)
        )
        if except_model_id is not None:
            statement = statement.where(Model.id != except_model_id)
        self.db.execute(statement)

    def lock_default_scope(self, *, capability: str, default_scope: str) -> None:
        digest = hashlib.sha256(
            f"{self.organization_id}|{capability}|{default_scope}".encode()
        ).digest()
        lock_key = int.from_bytes(digest[:8], byteorder="big", signed=True)
        self.db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": lock_key},
        )

    def add(self, item: object) -> None:
        self.db.add(item)

    def flush(self) -> None:
        self.db.flush()

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()

    def refresh(self, item: object) -> None:
        self.db.refresh(item)
