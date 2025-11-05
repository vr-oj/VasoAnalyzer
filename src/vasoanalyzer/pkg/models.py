from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from typing import Final, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

SchemaURI = Literal["https://vaso.dev/schemas/vaso-package-v1.json"]
SCHEMA_MANIFEST: Final[SchemaURI] = "https://vaso.dev/schemas/vaso-package-v1.json"


class GeneratorInfo(BaseModel):
    app: str
    version: str


class ManifestSummary(BaseModel):
    title: str = ""
    datasets: int = 0
    events: int = 0
    has_embedded_blobs: bool = False


class Manifest(BaseModel):
    model_config = ConfigDict(protected_namespaces=(), populate_by_name=True)

    schema_uri: SchemaURI = Field(default=SCHEMA_MANIFEST, alias="schema")
    format_version: str = "1.0.0"
    package_id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    created_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    modified_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    generator: GeneratorInfo = Field(
        default_factory=lambda: GeneratorInfo(app="VasoAnalyzer", version="2.0.0")
    )
    summary: ManifestSummary = Field(default_factory=ManifestSummary)


class ChannelSpec(BaseModel):
    key: str
    unit: str
    source: str | None = None


class Sampling(BaseModel):
    rate_hz: float
    time_zero: datetime | None = None

    @field_validator("rate_hz")
    def _rate_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("rate_hz must be > 0")
        return value


class DatasetMeta(BaseModel):
    id: str = Field(default_factory=lambda: str(_uuid.uuid4()))
    name: str
    modality: str
    sampling: Sampling
    channels: list[ChannelSpec]
    roi_version: int = 0
    provenance: dict[str, str] = Field(default_factory=dict)


class RefEntry(BaseModel):
    sha256: str
    size: int
    mime: str
    role: str
    uri: str
    rel_hint: str | None = None
    created: datetime | None = None


class Event(BaseModel):
    id: str
    dataset_id: str
    t: float
    label: str
    lane: str | None = None
    style: dict[str, object] = Field(default_factory=dict)


class ProjectMeta(BaseModel):
    title: str = ""
    subject: str | None = None
    timezone: str | None = None
    tags: list[str] = Field(default_factory=list)
