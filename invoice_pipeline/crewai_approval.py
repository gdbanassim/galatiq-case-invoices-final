from __future__ import annotations

import json
import os

from .llm import NIMClient
from .models import ApprovalResult, InvoiceRecord, ValidationResult


def run_crewai_approval(invoice: InvoiceRecord, validation: ValidationResult, nim_client: NIMClient) -> ApprovalResult:
    _disable_crewai_tracing_prompts()
    try:
        from crewai import Agent, Crew, LLM, Process, Task
        from crewai.events.listeners.tracing.utils import set_suppress_tracing_messages
    except Exception as exc:
        raise RuntimeError(
            "CrewAI is not installed in this Python environment. "
            "Install project dependencies with: python -m pip install -r requirements.txt"
        ) from exc

    set_suppress_tracing_messages(True)

    llm = LLM(
        model=f"nvidia_nim/{nim_client.config.model}",
        api_key=nim_client.config.api_key,
        base_url=nim_client.config.base_url,
        temperature=nim_client.config.temperature,
    )

    reviewer = Agent(
        role="Invoice Risk Reviewer",
        goal="Approve or reject invoices using only the provided parsed invoice and validation findings.",
        backstory=(
            "You are a careful AP analyst. Clean invoices under the VP threshold should be approved. "
            "High-severity validation issues should be rejected."
        ),
        llm=llm,
        verbose=False,
    )
    critic = Agent(
        role="Approval Critic",
        goal="Challenge the first recommendation and correct any overconfident conclusion.",
        backstory="You are the skeptical final gatekeeper for high-value invoices.",
        llm=llm,
        verbose=False,
    )

    review_task = Task(
        description=(
            "Review this invoice and validation packet. Return a JSON object with keys: "
            "decision, reason, needs_human_review, reflection.\n"
            "Rules: decision must be exactly approve or reject. Do not use pending, escalate, or review as a decision. "
            "Set needs_human_review=true for rejected invoices or invoices >= 10000. "
            "Approve invoices when validation is valid, risk_score < 30, and total < 10000.\n\n"
            f"Invoice: {json.dumps(invoice.to_dict(), indent=2)}\n\n"
            f"Validation: {json.dumps(validation.to_dict(), indent=2)}"
        ),
        expected_output="A JSON object with decision, reason, needs_human_review, and reflection.",
        agent=reviewer,
    )
    critique_task = Task(
        description=(
            "Critique the earlier decision. Confirm it if sound, or revise the decision if the evidence supports "
            "a different outcome. Return only JSON with: decision, reason, needs_human_review, reflection. "
            "The final decision must be exactly approve or reject. If validation is valid, risk_score < 30, "
            "and total < 10000, the final decision should be approve."
        ),
        expected_output="A JSON object with decision, reason, needs_human_review, and reflection.",
        agent=critic,
    )

    crew = Crew(
        agents=[reviewer, critic],
        tasks=[review_task, critique_task],
        process=Process.sequential,
        verbose=False,
        tracing=False,
    )
    crew_output = crew.kickoff()
    approval_data = _extract_json_object(str(crew_output))
    if approval_data is None:
        raise RuntimeError("CrewAI returned output that could not be parsed as JSON.")

    normalized = _normalize_approval_data(approval_data, invoice, validation)
    return ApprovalResult(
        decision=str(normalized["decision"]),
        reason=str(normalized["reason"]),
        needs_human_review=bool(normalized["needs_human_review"]),
        llm_provider="nvidia_nim/crewai",
        reflection=str(normalized["reflection"]),
    )


def _disable_crewai_tracing_prompts() -> None:
    os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")
    os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
    os.environ.setdefault("CREWAI_DISABLE_TRACKING", "true")
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")


def _normalize_approval_data(
    approval_data: dict[str, object],
    invoice: InvoiceRecord,
    validation: ValidationResult,
) -> dict[str, object]:
    raw_decision = str(approval_data.get("decision", "reject")).strip().lower()
    total = float(invoice.total if invoice.total is not None else invoice.computed_total())
    clean_low_value = validation.is_valid and validation.risk_score < 30 and total < 10000

    if raw_decision not in {"approve", "reject"}:
        decision = "approve" if clean_low_value else "reject"
        normalization_note = f"CrewAI returned unsupported decision '{raw_decision}', normalized by policy."
    else:
        decision = raw_decision
        normalization_note = ""

    if clean_low_value and decision == "approve":
        needs_human_review = False
    else:
        needs_human_review = bool(approval_data.get("needs_human_review", False))
        needs_human_review = needs_human_review or decision == "reject" or total >= 10000

    reason = str(approval_data.get("reason", "")).strip()
    if normalization_note and decision == "approve":
        reason = "Invoice passes validation, has no high-severity issues, and is below the VP scrutiny threshold."
    elif normalization_note and decision == "reject":
        reason = "Invoice is blocked by validation risk or approval policy."
    elif not reason:
        if decision == "approve":
            reason = "Invoice passes validation and is below the VP scrutiny threshold."
        else:
            reason = "Invoice requires rejection due to validation risk or approval policy."

    reflection = str(approval_data.get("reflection", "CrewAI critic confirmed the final decision.")).strip()
    if normalization_note:
        reflection = f"{normalization_note} {reflection}"

    return {
        "decision": decision,
        "reason": reason,
        "needs_human_review": needs_human_review,
        "reflection": reflection,
    }


def _extract_json_object(text: str) -> dict[str, object] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
