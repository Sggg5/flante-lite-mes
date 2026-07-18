from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


Algorithm = Literal[
    "SIX_MONTH_MAX", "SIX_MONTH_AVG", "THREE_MONTH_AVG",
    "SIX_MONTH_WEIGHTED", "FIXED_TARGET", "ORDER_BASED",
]
RoundingMode = Literal["NONE", "CEIL_TO_INTEGER", "CEIL_TO_MIN_BATCH"]


class PolicyUpsertRequest(BaseModel):
    algorithm: Algorithm
    rounding_mode: RoundingMode = "NONE"
    fixed_target_qty: Decimal | None = Field(default=None, ge=0)
    six_month_weights: list[Decimal] | None = None
    min_batch_qty: Decimal | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=500)
    reason: str = Field(min_length=2, max_length=500)

    @model_validator(mode="after")
    def validate_algorithm_config(self):
        if self.algorithm == "FIXED_TARGET" and self.fixed_target_qty is None:
            raise ValueError("FIXED_TARGET 必须设置 fixed_target_qty")
        if self.algorithm == "SIX_MONTH_WEIGHTED":
            if self.six_month_weights is None or len(self.six_month_weights) != 6:
                raise ValueError("SIX_MONTH_WEIGHTED 必须提供六个权重")
            if any(weight < 0 for weight in self.six_month_weights) or abs(sum(self.six_month_weights) - Decimal("1")) > Decimal("0.000001"):
                raise ValueError("权重必须非负且合计等于 1")
        if self.rounding_mode == "CEIL_TO_MIN_BATCH" and self.min_batch_qty is None:
            raise ValueError("按最小批量取整必须设置 min_batch_qty")
        return self


class BulkPolicyRequest(BaseModel):
    product_ids: list[int] = Field(min_length=1, max_length=5000)
    policy: PolicyUpsertRequest


class OrderInputRequest(BaseModel):
    product_id: int
    quantity: Decimal = Field(ge=0)
    reason: str = Field(min_length=2, max_length=500)
    source_document_no: str | None = Field(default=None, max_length=100)


class CreateRunRequest(BaseModel):
    calculation_date: date
    shipment_batch_id: int
    inventory_batch_id: int
    pipe_wip_batch_id: int
    fitting_wip_batch_id: int
    regular_product_batch_id: int
    weekly_plan_batch_id: int | None = None
    default_algorithm: Algorithm = "SIX_MONTH_MAX"
    default_weight_config: list[Decimal] | None = None
    default_fixed_target_qty: Decimal | None = Field(default=None, ge=0)
    rounding_mode: RoundingMode = "NONE"
    default_min_batch_qty: Decimal | None = Field(default=None, gt=0)
    order_inputs: list[OrderInputRequest] = Field(default_factory=list)
    force_duplicate: bool = False
    force_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_default_config(self):
        if self.default_algorithm == "SIX_MONTH_WEIGHTED":
            if self.default_weight_config is None or len(self.default_weight_config) != 6:
                raise ValueError("默认加权算法必须提供六个权重")
            if any(weight < 0 for weight in self.default_weight_config) or abs(sum(self.default_weight_config) - Decimal("1")) > Decimal("0.000001"):
                raise ValueError("默认权重必须非负且合计等于 1")
        if self.default_algorithm == "FIXED_TARGET" and self.default_fixed_target_qty is None:
            raise ValueError("默认固定目标算法必须设置 default_fixed_target_qty")
        if self.rounding_mode == "CEIL_TO_MIN_BATCH" and self.default_min_batch_qty is None:
            raise ValueError("默认按最小批量取整必须设置 default_min_batch_qty")
        return self


class ScheduledOverrideRequest(BaseModel):
    scheduled_override_qty: Decimal = Field(ge=0)
    reason: str = Field(min_length=2, max_length=500)


class ApproveRunRequest(BaseModel):
    allow_no_replenishment: bool = False
    reason: str = Field(min_length=2, max_length=500)


class CalculateRunRequest(BaseModel):
    override_blocking_checks: bool = False
    override_reason: str | None = Field(default=None, max_length=500)


class ReviewSuggestionRequest(BaseModel):
    action: Literal["APPROVE", "REJECT", "RETURN"]
    confirmed_qty: Decimal | None = Field(default=None, ge=0)
    reason: str = Field(min_length=2, max_length=500)


class BulkReviewRequest(ReviewSuggestionRequest):
    suggestion_ids: list[int] = Field(min_length=1, max_length=5000)


class ConvertSuggestionsRequest(BaseModel):
    suggestion_ids: list[int] = Field(min_length=1, max_length=5000)
    reason: str = Field(min_length=2, max_length=500)


class ResolveIssueRequest(BaseModel):
    action: Literal["RESOLVE", "IGNORE"]
    reason: str = Field(min_length=2, max_length=500)


class CancelRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=500)
