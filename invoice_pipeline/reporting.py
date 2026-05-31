from __future__ import annotations

import html
from pathlib import Path

from .models import WorkflowResult


def render_dashboard(results: list[WorkflowResult], report_path: str | Path) -> Path:
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    approved = sum(1 for result in results if result.approval.decision == "approve")
    rejected = len(results) - approved
    paid = sum(1 for result in results if result.payment_status)
    risk_total = sum(result.validation.risk_score for result in results)
    avg_risk = round(risk_total / len(results), 1) if results else 0
    total_amount = sum(float(result.invoice.total or result.invoice.computed_total()) for result in results)

    rows = "\n".join(_invoice_row(result) for result in results)
    issue_cards = "\n".join(_issue_card(result) for result in results if result.validation.issues)
    if not issue_cards:
        issue_cards = '<div class="empty">No validation issues found in this run.</div>'

    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Acme Invoice Automation</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17202a;
      --muted: #5d6978;
      --line: #d8dee6;
      --paper: #f7f9fb;
      --panel: #ffffff;
      --green: #13795b;
      --red: #b42318;
      --amber: #9a6700;
      --blue: #2454a6;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: var(--ink); background: var(--paper); }}
    header {{ padding: 28px 32px 20px; background: #ffffff; border-bottom: 1px solid var(--line); }}
    h1 {{ margin: 0 0 8px; font-size: 30px; letter-spacing: 0; }}
    header p {{ margin: 0; color: var(--muted); max-width: 860px; line-height: 1.45; }}
    main {{ padding: 24px 32px 36px; }}
    .metrics {{ display: grid; grid-template-columns: repeat(5, minmax(130px, 1fr)); gap: 12px; margin-bottom: 22px; }}
    .metric {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; }}
    .value {{ margin-top: 8px; font-size: 24px; font-weight: 700; }}
    section {{ margin-top: 24px; }}
    h2 {{ font-size: 18px; margin: 0 0 12px; }}
    table {{ width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }}
    th, td {{ padding: 11px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ color: var(--muted); background: #eef2f6; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; }}
    tr:last-child td {{ border-bottom: 0; }}
    .status {{ display: inline-block; min-width: 72px; padding: 3px 8px; border-radius: 999px; font-size: 12px; font-weight: 700; text-align: center; }}
    .approve {{ color: var(--green); background: #e7f5ef; }}
    .reject {{ color: var(--red); background: #fdecec; }}
    .review {{ color: var(--amber); background: #fff5d6; }}
    .issues {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
    .issue {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }}
    .issue strong {{ display: block; margin-bottom: 8px; }}
    .issue ul {{ margin: 8px 0 0; padding-left: 18px; color: var(--muted); }}
    .trace {{ color: var(--muted); font-size: 13px; line-height: 1.4; }}
    .empty {{ padding: 16px; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; color: var(--muted); }}
    @media (max-width: 900px) {{
      header, main {{ padding-left: 16px; padding-right: 16px; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      table {{ display: block; overflow-x: auto; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>Acme Invoice Automation</h1>
    <p>End-to-end multi-agent run with document ingestion, SQLite inventory validation, VP approval critique, and mock payment execution.</p>
  </header>
  <main>
    <div class="metrics">
      <div class="metric"><div class="label">Invoices</div><div class="value">{len(results)}</div></div>
      <div class="metric"><div class="label">Approved</div><div class="value">{approved}</div></div>
      <div class="metric"><div class="label">Rejected</div><div class="value">{rejected}</div></div>
      <div class="metric"><div class="label">Paid</div><div class="value">{paid}</div></div>
      <div class="metric"><div class="label">Avg Risk</div><div class="value">{avg_risk}</div></div>
    </div>
    <section>
      <h2>Processing Queue</h2>
      <table>
        <thead>
          <tr><th>Invoice</th><th>Vendor</th><th>Amount</th><th>Risk</th><th>Decision</th><th>Agent Trace</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </section>
    <section>
      <h2>Exceptions</h2>
      <div class="issues">{issue_cards}</div>
    </section>
    <section>
      <h2>Business Impact Snapshot</h2>
      <div class="empty">Processed ${total_amount:,.2f} in invoice value with structured exception routing and zero manual data re-entry for this run.</div>
    </section>
  </main>
</body>
</html>
""",
        encoding="utf-8",
    )
    return path


def _invoice_row(result: WorkflowResult) -> str:
    invoice = result.invoice
    decision_class = "approve" if result.approval.decision == "approve" else "reject"
    if result.approval.needs_human_review and result.approval.decision == "approve":
        decision_class = "review"
    trace = " -> ".join(f"{log.agent}: {log.status}" for log in result.stage_logs)
    amount = float(invoice.total or invoice.computed_total())
    return (
        "<tr>"
        f"<td>{_e(invoice.invoice_number or 'unknown')}</td>"
        f"<td>{_e(invoice.vendor or 'missing')}</td>"
        f"<td>{_e(invoice.currency)} {amount:,.2f}</td>"
        f"<td>{result.validation.risk_score}</td>"
        f"<td><span class=\"status {decision_class}\">{_e(result.approval.decision)}</span></td>"
        f"<td class=\"trace\">{_e(trace)}</td>"
        "</tr>"
    )


def _issue_card(result: WorkflowResult) -> str:
    invoice_id = result.invoice.invoice_number or Path(result.invoice.source_path).name
    items = "".join(f"<li>{_e(issue.severity)}: {_e(issue.message)}</li>" for issue in result.validation.issues)
    return (
        '<div class="issue">'
        f"<strong>{_e(invoice_id)}</strong>"
        f"<div class=\"trace\">{_e(result.approval.reason)}</div>"
        f"<ul>{items}</ul>"
        "</div>"
    )


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)
