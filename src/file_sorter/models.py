"""Validated API inputs and structured application errors."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Problem(Exception):
    """Expected service failure serialized by the API without a traceback."""

    def __init__(self, code: str, message: str, status: int = 422, field: str | None = None):
        """Store the public error code, message, HTTP status, and optional field."""
        super().__init__(message)
        self.code, self.message, self.status, self.field = code, message, status, field

    def payload(self) -> dict:
        """Return the stable API error envelope; conflicts may be retried after refresh."""
        return {"code": self.code, "message": self.message, "field": self.field,
                "retryable": self.status == 409}


class Input(BaseModel):
    """Reject unknown fields instead of silently ignoring misspelled options."""
    model_config = ConfigDict(extra="forbid")


class Rule(Input):
    """A destination mapping with optional filename-stem template."""
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=1, max_length=4096)
    extensions: str = Field(min_length=1, max_length=2000)
    enabled: bool = True
    template: str = Field(default="", max_length=200)


class RulesInput(Input):
    """Revision-checked replacement of the saved rule collection."""
    revision: int = Field(ge=0)
    rules: list[Rule] = Field(max_length=200)


class PreviewInput(Input):
    """Source and scan options frozen into a preview."""
    source: str = Field(min_length=1, max_length=4096)
    recursive: bool = False
    include_hidden: bool = False
    collision: Literal["keep_both", "skip"] = "keep_both"


class JobInput(Input):
    """A confirmed preview and a retry-safe submission identifier."""
    preview_id: str
    idempotency_key: str = Field(min_length=1, max_length=100)
