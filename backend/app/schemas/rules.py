"""Input validation for decision-rule management."""
from pydantic import BaseModel, Field


class RuleCreateIn(BaseModel):
    rule_name: str = Field(min_length=3, max_length=100, pattern=r"^[a-z0-9_]+$")
    description: str | None = Field(default=None, max_length=1000)
    rule_configuration: dict
    activate: bool = False


class RuleUpdateIn(BaseModel):
    rule_configuration: dict
    description: str | None = Field(default=None, max_length=1000)