from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


UploadSurface = Literal["shared_file", "large_input"]
UploadConflictStrategy = Literal["fail", "keep_both", "overwrite"]
UploadPurpose = Literal["workspace_shared_file", "task_input", "agent_input", "workflow_input"]
UploadOwnerType = Literal["message", "message_draft", "task", "workflow", "agent_run", "none"]
UploadRetentionPolicy = Literal["owner_lifecycle", "expires_at", "manual"]


class UploadSessionCreateRequest(BaseModel):
    surface: UploadSurface
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="application/octet-stream", max_length=128)
    expected_size: int = Field(ge=0)
    checksum: str | None = Field(default=None, max_length=96)
    parent_path: str = Field(default="/", max_length=1024)
    purpose: UploadPurpose | None = None
    owner_type: UploadOwnerType = "none"
    owner_id: str | None = Field(default=None, max_length=36)
    retention_policy: UploadRetentionPolicy = "expires_at"
    conflict_strategy: UploadConflictStrategy = "fail"
    expected_existing_file_id: str | None = Field(default=None, max_length=36)
    client_request_id: str | None = Field(default=None, max_length=128)


class UploadPartInfo(BaseModel):
    part_number: int
    size: int
    checksum: str
    etag: str
    status: str
    uploaded_at: datetime


class UploadSessionInfo(BaseModel):
    session_id: str
    upload_mode: str
    backend: str
    part_size_bytes: int
    part_count: int
    expires_at: datetime
    complete_required: bool = True
    effective_filename: str
    conflict_strategy: str
    status: str
    received_size: int
    expected_size: int
    surface: str
    status_url: str
    complete_url: str
    parts: list[UploadPartInfo] = []


class UploadPartUploadResponse(BaseModel):
    session_id: str
    part: UploadPartInfo
    received_size: int
    status: str


class UploadPartSignResponse(BaseModel):
    part_number: int
    upload_url: str | None = None
    expires_at: datetime | None = None
    required_headers: dict[str, str] = {}
    upload_mode: str


class UploadCompletePartInput(BaseModel):
    part_number: int = Field(ge=1)
    etag: str | None = None
    size: int | None = Field(default=None, ge=0)
    checksum: str | None = None


class UploadCompleteRequest(BaseModel):
    parts: list[UploadCompletePartInput] | None = None
    checksum: str | None = Field(default=None, max_length=96)


class UploadCancelResponse(BaseModel):
    session_id: str
    status: str
    released: bool
