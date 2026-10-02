from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.connectors import Connector, ConnectorConfig, ConnectorType


class ConnectorConfigurationRepository:
    def __init__(self, db: Session, organization_id: uuid.UUID) -> None:
        self.db = db
        self.organization_id = organization_id

    def get_connector(
        self,
        connector_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> Connector | None:
        statement = select(Connector).where(
            Connector.id == connector_id,
            Connector.organization_id == self.organization_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.db.scalar(statement)

    def get_connector_by_code(self, code: str) -> Connector | None:
        return self.db.scalar(
            select(Connector).where(
                Connector.organization_id == self.organization_id,
                Connector.code == code,
            )
        )

    def get_connector_type(self, connector_type_id: uuid.UUID) -> ConnectorType | None:
        return self.db.scalar(
            select(ConnectorType).where(ConnectorType.id == connector_type_id)
        )

    def current_configuration(self, connector_id: uuid.UUID) -> ConnectorConfig | None:
        return self.db.scalar(
            select(ConnectorConfig)
            .join(Connector, Connector.id == ConnectorConfig.connector_id)
            .where(
                ConnectorConfig.connector_id == connector_id,
                Connector.organization_id == self.organization_id,
            )
            .order_by(
                ConnectorConfig.is_active.desc(),
                ConnectorConfig.version.desc(),
                ConnectorConfig.created_at.desc(),
                ConnectorConfig.id.desc(),
            )
            .limit(1)
        )

    def deactivate_configurations(self, connector_id: uuid.UUID) -> None:
        self.db.execute(
            update(ConnectorConfig)
            .where(
                ConnectorConfig.connector_id == connector_id,
                ConnectorConfig.is_active.is_(True),
                ConnectorConfig.connector_id.in_(
                    select(Connector.id).where(
                        Connector.organization_id == self.organization_id,
                    )
                ),
            )
            .values(is_active=False)
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
