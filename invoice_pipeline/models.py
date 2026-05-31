from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class LineItem:
    item: str
    quantity: int
    unit_price: float
    amount: float | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class InvoiceRecord:
    invoice_number: str
    vendor: str
    date: str | None
    due_date: str | None
    line_items: list[LineItem] = field(default_factory=list)
    subtotal: float | None = None
    tax_rate: float | None = None
    tax_amount: float | None = None
    total: float | None = None
    currency: str = "USD"
    payment_terms: str = ""
    source_path: str = ""
    raw_text: str = ""

    def computed_subtotal(self) -> float:
        return round(
            sum(item.amount if item.amount is not None else item.quantity * item.unit_price for item in self.line_items),
            2,
        )

    def computed_total(self) -> float:
        subtotal = self.subtotal if self.subtotal is not None else self.computed_subtotal()
        tax_amount = self.tax_amount if self.tax_amount is not None else 0.0
        return round(subtotal + tax_amount, 2)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["line_items"] = [item.to_dict() for item in self.line_items]
        data["computed_subtotal"] = self.computed_subtotal()
        data["computed_total"] = self.computed_total()
        return data


@dataclass(slots=True)
class ValidationIssue:
    severity: str
    field: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ValidationResult:
    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    inventory_snapshot: dict[str, int] = field(default_factory=dict)
    risk_score: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["issues"] = [issue.to_dict() for issue in self.issues]
        return data


@dataclass(slots=True)
class ApprovalResult:
    decision: str
    reason: str
    needs_human_review: bool = False
    llm_provider: str = "local"
    reflection: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class StageLog:
    stage: str
    agent: str
    status: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkflowResult:
    invoice: InvoiceRecord
    validation: ValidationResult
    approval: ApprovalResult
    payment_status: dict[str, Any] | None = None
    stage_logs: list[StageLog] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice": self.invoice.to_dict(),
            "validation": self.validation.to_dict(),
            "approval": self.approval.to_dict(),
            "payment_status": self.payment_status,
            "stage_logs": [stage_log.to_dict() for stage_log in self.stage_logs],
        }
