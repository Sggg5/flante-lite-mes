from datetime import date
from typing import Any

from pydantic import BaseModel, Field, model_validator


class AnalyzeImportRequest(BaseModel):
    sheet_name: str
    header_row_start: int | None = Field(default=None, ge=1)
    header_row_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_header_range(self) -> "AnalyzeImportRequest":
        if self.header_row_start and self.header_row_end and self.header_row_start > self.header_row_end:
            raise ValueError("header_row_start cannot exceed header_row_end")
        return self


class UpdateMappingRequest(BaseModel):
    field_mapping: dict[str, int]
    conversion_rules: dict[str, Any] = Field(default_factory=dict)


class RollbackImportRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class ImportListFilters(BaseModel):
    import_type: str | None = None
    status: str | None = None
    created_by: int | None = None
    date_from: date | None = None
    date_to: date | None = None
