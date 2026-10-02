from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentOrganizationAssociationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    organization_node_id: uuid.UUID
    intent: Literal["add", "retain", "archive", "restore"]


class DocumentOrganizationAssociationSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    mutation_key: uuid.UUID
    associations: list[DocumentOrganizationAssociationProposal] = Field(
        default_factory=list,
        max_length=100,
    )

    @model_validator(mode="after")
    def validate_unique_nodes(self) -> DocumentOrganizationAssociationSaveRequest:
        node_ids = [item.organization_node_id for item in self.associations]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("document organization association nodes must be unique")
        return self


class DocumentOrganizationAssociationRuntimeResponse(BaseModel):
    document_organization_association_schema_version: str = "1"
    document: dict[str, object]
    revision: int
    active_associations: list[dict[str, object]]
    archived_associations: list[dict[str, object]]
    structure_options: list[dict[str, object]]
    capabilities: dict[str, bool]
    limits: dict[str, int]
    warnings: list[dict[str, object]]
    replayed: bool = False
    postgresql_source_of_truth: bool = True
    association_semantics: Literal["organizational_relation_only"] = (
        "organizational_relation_only"
    )

