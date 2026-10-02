from typing import Literal

from pydantic import BaseModel, ConfigDict


class OperationalHealthIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    severity: Literal["degraded", "critical"]
    source: str
    resource_type: str
    resource_key: str | None = None
    message: str
    observed_value: int | float | str | None = None
