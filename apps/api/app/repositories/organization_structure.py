from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import (
    Organization,
    OrganizationNode,
    OrganizationNodeType,
    OrganizationRelationship,
    OrganizationStructureAggregate,
)


class OrganizationStructureRepository:
    def __init__(self, db: Session, organization_id: uuid.UUID) -> None:
        self.db = db
        self.organization_id = organization_id

    def organization(
        self,
        *,
        for_update: bool = False,
        for_share: bool = False,
    ) -> Organization | None:
        statement = select(Organization).where(Organization.id == self.organization_id)
        if for_update:
            statement = statement.with_for_update()
        elif for_share:
            statement = statement.with_for_update(read=True)
        return self.db.scalar(statement)

    def aggregate(
        self,
        *,
        for_update: bool = False,
    ) -> OrganizationStructureAggregate | None:
        statement = select(OrganizationStructureAggregate).where(
            OrganizationStructureAggregate.organization_id == self.organization_id
        )
        if for_update:
            statement = statement.with_for_update()
        return self.db.scalar(statement)

    def node_types(
        self,
        *,
        for_share: bool = False,
    ) -> list[OrganizationNodeType]:
        statement = select(OrganizationNodeType).order_by(
            OrganizationNodeType.display_order.asc(),
            OrganizationNodeType.code.asc(),
        )
        if for_share:
            statement = statement.with_for_update(read=True)
        return list(
            self.db.scalars(statement).all()
        )

    def nodes(self, *, for_update: bool = False) -> list[OrganizationNode]:
        statement = (
            select(OrganizationNode)
            .where(OrganizationNode.organization_id == self.organization_id)
            .order_by(OrganizationNode.code.asc(), OrganizationNode.id.asc())
        )
        if for_update:
            statement = statement.with_for_update()
        return list(self.db.scalars(statement).all())

    def relationships(
        self,
        *,
        for_update: bool = False,
    ) -> list[OrganizationRelationship]:
        statement = (
            select(OrganizationRelationship)
            .where(OrganizationRelationship.organization_id == self.organization_id)
            .order_by(
                OrganizationRelationship.relationship_type.asc(),
                OrganizationRelationship.id.asc(),
            )
        )
        if for_update:
            statement = statement.with_for_update()
        return list(self.db.scalars(statement).all())

    def add(self, item: object) -> None:
        self.db.add(item)

    def flush(self) -> None:
        self.db.flush()
