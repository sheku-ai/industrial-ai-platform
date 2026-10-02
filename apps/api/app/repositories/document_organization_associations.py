from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import OrganizationNode, OrganizationNodeType
from app.models.documents import (
    DocumentOrganizationAssociation,
    DocumentOrganizationAssociationAggregate,
    DocumentRecord,
)


class DocumentOrganizationAssociationRepository:
    def __init__(self, db: Session, organization_id: uuid.UUID) -> None:
        self.db = db
        self.organization_id = organization_id

    def document(
        self,
        document_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> DocumentRecord | None:
        statement = select(DocumentRecord).where(
            DocumentRecord.organization_id == self.organization_id,
            DocumentRecord.id == document_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.db.scalar(statement)

    def aggregate(
        self,
        document_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> DocumentOrganizationAssociationAggregate | None:
        statement = select(DocumentOrganizationAssociationAggregate).where(
            DocumentOrganizationAssociationAggregate.organization_id
            == self.organization_id,
            DocumentOrganizationAssociationAggregate.document_id == document_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return self.db.scalar(statement)

    def associations(
        self,
        document_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> list[DocumentOrganizationAssociation]:
        statement = (
            select(DocumentOrganizationAssociation)
            .where(
                DocumentOrganizationAssociation.organization_id
                == self.organization_id,
                DocumentOrganizationAssociation.document_id == document_id,
            )
            .order_by(
                DocumentOrganizationAssociation.created_at.asc(),
                DocumentOrganizationAssociation.id.asc(),
            )
        )
        if for_update:
            statement = statement.with_for_update()
        return list(self.db.scalars(statement).all())

    def associations_for_documents(
        self,
        document_ids: list[uuid.UUID],
    ) -> list[DocumentOrganizationAssociation]:
        if not document_ids:
            return []
        return list(
            self.db.scalars(
                select(DocumentOrganizationAssociation)
                .where(
                    DocumentOrganizationAssociation.organization_id
                    == self.organization_id,
                    DocumentOrganizationAssociation.document_id.in_(document_ids),
                )
                .order_by(
                    DocumentOrganizationAssociation.document_id.asc(),
                    DocumentOrganizationAssociation.created_at.asc(),
                    DocumentOrganizationAssociation.id.asc(),
                )
            ).all()
        )

    def nodes(
        self,
        node_ids: set[uuid.UUID] | None = None,
    ) -> list[OrganizationNode]:
        statement = select(OrganizationNode).where(
            OrganizationNode.organization_id == self.organization_id
        )
        if node_ids is not None:
            if not node_ids:
                return []
            statement = statement.where(OrganizationNode.id.in_(node_ids))
        return list(
            self.db.scalars(
                statement.order_by(
                    OrganizationNode.name.asc(),
                    OrganizationNode.code.asc(),
                    OrganizationNode.id.asc(),
                )
            ).all()
        )

    def node_types(self) -> list[OrganizationNodeType]:
        return list(
            self.db.scalars(
                select(OrganizationNodeType).order_by(
                    OrganizationNodeType.display_order.asc(),
                    OrganizationNodeType.code.asc(),
                )
            ).all()
        )

    def add(self, item: object) -> None:
        self.db.add(item)

    def flush(self) -> None:
        self.db.flush()

