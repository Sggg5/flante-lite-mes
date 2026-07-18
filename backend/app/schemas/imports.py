from datetime import date
from typing import Any, Literal

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


class UpdateImportOptionsRequest(BaseModel):
    include_hidden_rows: bool = True
    source_date: date | None = None
    master_data_policy: Literal["KEEP_EXISTING", "FILL_EMPTY", "ADMIN_UPDATE"] = "FILL_EMPTY"
    master_data_reason: str | None = Field(default=None, max_length=500)
    force_duplicate: bool = False
    force_reason: str | None = Field(default=None, max_length=500)


class MatchWeeklyPlanRequest(BaseModel):
    action: Literal["MATCH", "IGNORE"] = "MATCH"
    product_id: int | None = None
    reason: str = Field(min_length=2, max_length=500)

    @model_validator(mode="after")
    def validate_match_action(self) -> "MatchWeeklyPlanRequest":
        if self.action == "MATCH" and self.product_id is None:
            raise ValueError("product_id is required for MATCH")
        return self


class RollbackImportRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class ImportListFilters(BaseModel):
    import_type: str | None = None
    status: str | None = None
    created_by: int | None = None
    date_from: date | None = None
    date_to: date | None = None
