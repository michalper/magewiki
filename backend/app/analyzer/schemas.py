from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, model_validator


class FileSummary(BaseModel):
    file_summary: str = Field(..., min_length=1, max_length=1000)
    notable_behavior: str | None = Field(None, max_length=500)


class Feature(BaseModel):
    name: str
    description: str
    source: str


class Integration(BaseModel):
    name: str
    description: str
    source: str | None = None


class Tag(BaseModel):
    name: str
    source: Literal["parser", "ai"]
    confidence: float = Field(ge=0, le=1)


class ConfigOption(BaseModel):
    path: str
    label: str | None = None


class Risk(BaseModel):
    description: str
    severity: Literal["low", "medium", "high"] = "low"


class ModuleDoc(BaseModel):
    summary: str
    description: str
    features: list[Feature] = []
    integrations: list[Integration] = []
    tags: list[Tag] = []
    config_options: list[ConfigOption] = []
    risks: list[Risk] = []
    confidence: float = Field(ge=0, le=1)
    pm_text: str
    dev_text: str
    rejected_tags: list[str] = []

    @model_validator(mode="after")
    def _validate_sources(self, info: ValidationInfo) -> "ModuleDoc":
        known_sources = (info.context or {}).get("known_sources") if info.context else None
        if not known_sources:
            return self

        for feature in self.features:
            if feature.source not in known_sources:
                raise ValueError(
                    f"feature {feature.name!r}: source {feature.source!r} is not a known file/class of this module"
                )
        for integration in self.integrations:
            if integration.source is not None and integration.source not in known_sources:
                raise ValueError(
                    f"integration {integration.name!r}: source {integration.source!r} is not a known "
                    "file/class of this module"
                )
        return self
