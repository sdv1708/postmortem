from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Severity = Literal["sev0", "sev1", "sev2", "sev3", "sev4"]
IncidentStatus = Literal["open", "investigating", "mitigated", "resolved", "closed"]
ArtifactSourceType = Literal["incident_notes", "logs", "stack_trace", "deployment_notes", "other"]


class IncidentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    summary: str | None = None
    severity: Severity | None = None
    status: IncidentStatus = "open"
    started_at: datetime | None = None
    detected_at: datetime | None = None
    resolved_at: datetime | None = None


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workspace_id: str
    title: str
    summary: str | None
    severity: str | None
    status: str
    started_at: datetime | None
    detected_at: datetime | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ArtifactLine(BaseModel):
    number: int
    text: str


class ArtifactCreate(BaseModel):
    source_type: ArtifactSourceType
    source_name: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1)


class ArtifactReplace(BaseModel):
    source_type: ArtifactSourceType | None = None
    source_name: str | None = Field(default=None, min_length=1, max_length=255)
    body: str = Field(min_length=1)


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    incident_id: str
    source_type: str
    source_name: str
    body: str
    line_count: int
    included_in_analysis_run: bool
    created_at: datetime
    updated_at: datetime
    lines: list[ArtifactLine]
