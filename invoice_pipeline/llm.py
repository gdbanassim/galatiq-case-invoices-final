from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class NIMConfig:
    api_key: str | None
    base_url: str
    model: str
    temperature: float = 0.1

    @classmethod
    def from_env(cls) -> "NIMConfig":
        env_values = _load_dotenv_values()
        return cls(
            api_key=_first_value(
                os.getenv("NVIDIA_NIM_API_KEY"),
                os.getenv("NVIDIA_NIM_API"),
                os.getenv("NVIDIA_API_KEY"),
                os.getenv("OPENAI_API_KEY"),
                env_values.get("NVIDIA_NIM_API_KEY"),
                env_values.get("NVIDIA_NIM_API"),
                env_values.get("NVIDIA_API_KEY"),
                env_values.get("OPENAI_API_KEY"),
            ),
            base_url=_first_value(
                os.getenv("NVIDIA_NIM_BASE_URL"),
                env_values.get("NVIDIA_NIM_BASE_URL"),
                default="https://integrate.api.nvidia.com/v1",
            ),
            model=_first_value(
                os.getenv("NVIDIA_NIM_MODEL"),
                env_values.get("NVIDIA_NIM_MODEL"),
                default="meta/llama-3.1-70b-instruct",
            ),
            temperature=float(_first_value(
                os.getenv("NVIDIA_NIM_TEMPERATURE"),
                env_values.get("NVIDIA_NIM_TEMPERATURE"),
                default="0.1",
            )),
        )

    def is_configured(self) -> bool:
        return bool(self.api_key)


class NIMClient:
    def __init__(self, config: NIMConfig | None = None) -> None:
        self.config = config or NIMConfig.from_env()

    @property
    def available(self) -> bool:
        return self.config.is_configured()

    def chat(self, messages: list[dict[str, str]], *, response_format: str | None = None) -> str:
        if not self.available:
            raise RuntimeError("NVIDIA NIM is not configured.")

        payload: dict[str, object] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}

        request = urllib.request.Request(
            url=f"{self.config.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"NIM request failed with HTTP {exc.code}: {exc.read().decode('utf-8', errors='ignore')}") from exc

        payload = json.loads(raw)
        return payload["choices"][0]["message"]["content"]


class LocalReasoner:
    """Deterministic fallback that mirrors the approval rubric."""

    def summarize(self, invoice: dict, validation: dict) -> dict:
        initial_decision = "approve" if validation["is_valid"] and validation["risk_score"] < 30 else "reject"
        initial_reason = self._reason_from_validation(invoice, validation, initial_decision)
        critique = self._critique(invoice, validation, initial_decision)
        decision = str(critique["decision"])
        reason = str(critique["reason"] or initial_reason)
        needs_human_review = decision != "approve" or validation["risk_score"] >= 30 or self._requires_additional_scrutiny(invoice)
        return {
            "decision": decision,
            "reason": reason,
            "needs_human_review": needs_human_review,
            "llm_provider": "local_nim_simulated_crewai",
            "reflection": str(critique["reflection"]),
        }

    def _reason_from_validation(self, invoice: dict, validation: dict, decision: str) -> str:
        if validation["issues"]:
            issue_summary = "; ".join(issue["message"] for issue in validation["issues"][:3])
        else:
            issue_summary = "No validation issues detected."
        if decision == "approve" and self._requires_additional_scrutiny(invoice):
            return f"Invoice passes validation, but requires additional scrutiny because the total is high or vendor risk is elevated. {issue_summary}"
        if decision == "approve":
            return f"Invoice passes validation and matches inventory expectations. {issue_summary}"
        return f"Invoice is not safe to approve. {issue_summary}"

    def _requires_additional_scrutiny(self, invoice: dict) -> bool:
        total = float(invoice.get("total") or 0.0)
        return total >= 10000.0

    def _critique(self, invoice: dict, validation: dict, decision: str) -> dict:
        high_issues = [issue for issue in validation["issues"] if issue["severity"] == "high"]
        total = float(invoice.get("total") or 0.0)

        if high_issues and decision == "approve":
            return {
                "decision": "reject",
                "reason": self._reason_from_validation(invoice, validation, "reject"),
                "reflection": "Critic overturned approval because high-severity validation issues were present.",
            }
        if total >= 10000 and decision == "approve":
            return {
                "decision": "approve",
                "reason": self._reason_from_validation(invoice, validation, "approve"),
                "reflection": "Critic confirmed approval but marked the invoice for VP scrutiny because it exceeds the 10000 threshold.",
            }
        if not invoice.get("vendor"):
            return {
                "decision": "reject",
                "reason": self._reason_from_validation(invoice, validation, "reject"),
                "reflection": "Critic confirmed rejection because payment cannot proceed without a vendor identity.",
            }
        return {
            "decision": decision,
            "reason": "",
            "reflection": "Critic confirmed the recommendation after checking validation severity, vendor identity, and approval threshold.",
        }


def _load_dotenv_values() -> dict[str, str]:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def _first_value(*values: str | None, default: str | None = None) -> str:
    for value in values:
        if value:
            return value
    if default is not None:
        return default
    return ""
