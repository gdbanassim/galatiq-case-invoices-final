from __future__ import annotations

import logging
from pathlib import Path

from .crewai_approval import run_crewai_approval
from .inventory import ensure_inventory_db, validate_invoice
from .llm import LocalReasoner, NIMClient, NIMConfig
from .models import ApprovalResult, InvoiceRecord, StageLog, WorkflowResult
from .parsers import parse_invoice_file

logger = logging.getLogger(__name__)


def mock_payment(vendor: str, amount: float, currency: str = "USD") -> dict[str, object]:
    return {"status": "success", "vendor": vendor, "amount": round(amount, 2), "currency": currency}


def run_workflow(invoice_path: str | Path, db_path: str | Path = "inventory.db") -> WorkflowResult:
    stage_logs: list[StageLog] = []

    ensure_inventory_db(db_path)
    invoice = parse_invoice_file(invoice_path)
    stage_logs.append(
        StageLog(
            stage="ingestion",
            agent="Document Ingestion Agent",
            status="completed",
            summary=f"Extracted invoice {invoice.invoice_number or 'unknown'} from {Path(invoice_path).name}.",
            details={
                "vendor": invoice.vendor,
                "line_item_count": len(invoice.line_items),
                "total": invoice.total,
                "source_type": Path(invoice_path).suffix.lower().lstrip(".") or "text",
            },
        )
    )

    validation = validate_invoice(invoice, db_path)
    stage_logs.append(
        StageLog(
            stage="validation",
            agent="Inventory Validation Agent",
            status="passed" if validation.is_valid else "flagged",
            summary=f"Validation found {len(validation.issues)} issue(s), risk score {validation.risk_score}.",
            details={"issues": [issue.to_dict() for issue in validation.issues]},
        )
    )

    approval = _run_approval(invoice, validation)
    stage_logs.append(
        StageLog(
            stage="approval",
            agent="VP Approval Crew",
            status=approval.decision,
            summary=approval.reason,
            details={
                "needs_human_review": approval.needs_human_review,
                "llm_provider": approval.llm_provider,
                "reflection": approval.reflection,
            },
        )
    )

    payment_status = None
    if approval.decision == "approve":
        amount = invoice.total if invoice.total is not None else invoice.computed_total()
        payment_status = mock_payment(invoice.vendor, amount, invoice.currency)
        stage_logs.append(
            StageLog(
                stage="payment",
                agent="Payment Agent",
                status="paid",
                summary=f"Mock payment sent to {invoice.vendor} for {invoice.currency} {amount:.2f}.",
                details=payment_status,
            )
        )
    else:
        stage_logs.append(
            StageLog(
                stage="payment",
                agent="Payment Agent",
                status="blocked",
                summary="Payment was not executed because approval rejected or escalated the invoice.",
                details={"reason": approval.reason},
            )
        )

    result = WorkflowResult(
        invoice=invoice,
        validation=validation,
        approval=approval,
        payment_status=payment_status,
        stage_logs=stage_logs,
    )
    logger.info(
        "workflow_complete invoice_number=%s decision=%s provider=%s",
        invoice.invoice_number or "unknown",
        approval.decision,
        approval.llm_provider,
    )
    return result


def _run_approval(invoice: InvoiceRecord, validation) -> ApprovalResult:
    nim_client = NIMClient(NIMConfig.from_env())
    if nim_client.available:
        try:
            return run_crewai_approval(invoice, validation, nim_client)
        except Exception as exc:
            logger.warning("CrewAI/NIM approval path failed, falling back to local reasoning: %s", exc)

    local = LocalReasoner()
    summary = local.summarize(invoice.to_dict(), validation.to_dict())
    return ApprovalResult(
        decision=str(summary["decision"]),
        reason=str(summary["reason"]),
        needs_human_review=bool(summary["needs_human_review"]),
        llm_provider=str(summary["llm_provider"]),
        reflection=str(summary["reflection"]),
    )
