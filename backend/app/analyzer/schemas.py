import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

_MODULE_DOC_LIST_FIELDS = ("features", "integrations", "tags", "config_options", "risks", "rejected_tags")


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

    @model_validator(mode="before")
    @classmethod
    def _coerce_bare_string(cls, data: object) -> object:
        # Synthesis occasionally emits tags as bare strings ("payments") instead of
        # the required {name, source, confidence} object, even after a corrective
        # reprompt — seen in ~32 real ModuleDoc validation failures at fleet scale.
        # A bare string is unambiguously AI-sourced (a parser-derived tag is never
        # free-form text) with no confidence signal to anchor to, so default to a
        # mid-point confidence rather than reject a tag the model clearly meant.
        if isinstance(data, str):
            return {"name": data, "source": "ai", "confidence": 0.5}
        return data


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

    @model_validator(mode="before")
    @classmethod
    def _parse_json_string_list_fields(cls, data: object) -> object:
        # Synthesis occasionally stringifies a whole list field ('[{"name": ...}]')
        # instead of emitting it as real nested JSON — seen in production as
        # `features` failing with "Input should be a valid list" even though the
        # string content was itself well-formed JSON. Recover it before field
        # validation runs; leave genuinely malformed strings as-is so the real
        # error still surfaces rather than being silently swallowed here.
        if not isinstance(data, dict):
            return data
        for field_name in _MODULE_DOC_LIST_FIELDS:
            value = data.get(field_name)
            if isinstance(value, str):
                try:
                    data[field_name] = json.loads(value)
                except json.JSONDecodeError:
                    pass
        return data

    @field_validator("rejected_tags", mode="before")
    @classmethod
    def _coerce_rejected_tag_items(cls, value: object) -> object:
        # Synthesis occasionally emits a rejected tag as the same {name, source,
        # confidence} object shape used for `tags`, instead of the bare name string
        # `rejected_tags` actually expects — seen in ~8 real ModuleDoc validation
        # failures at fleet scale. Extract the name rather than reject a tag the
        # model clearly meant to record as rejected.
        if not isinstance(value, list):
            return value
        return [item.get("name", str(item)) if isinstance(item, dict) else item for item in value]

    @model_validator(mode="after")
    def _validate_sources(self, info: ValidationInfo) -> "ModuleDoc":
        # Distinguish "no context passed" (caller didn't opt into validation,
        # e.g. re-validating an already-validated doc read back from the DB)
        # from "context passed with zero known sources" (a module with no
        # PHP classes/file analyses) — the latter must still reject every
        # claimed source, not skip validation, or a config-only module could
        # have any hallucinated source sail through uncontested.
        if info.context is None or "known_sources" not in info.context:
            return self
        known_sources: set[str] = info.context["known_sources"]

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
