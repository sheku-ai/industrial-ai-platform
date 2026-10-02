from typing import Literal

from pydantic import BaseModel, Field


class InstallationPasswordPolicyResponse(BaseModel):
    min_length: int
    max_length: int
    block_context: bool
    block_common: bool


class InstallationStatusResponse(BaseModel):
    state: Literal["UNCONFIGURED", "IN_PROGRESS", "READY_TO_COMPLETE", "COMPLETED"]
    token_authorized: bool
    setup_available: bool
    setup_schema_version: int
    steps: dict[str, bool]
    next_step: str | None
    ready_to_complete: bool
    details: dict[str, dict]
    password_policy: InstallationPasswordPolicyResponse


class InstallationOrganizationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=128)


class InstallationAdministratorRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=1, max_length=1_024)


class InstallationPreferencesRequest(BaseModel):
    language: str = Field(min_length=2, max_length=16)
    timezone: str = Field(min_length=1, max_length=128)
