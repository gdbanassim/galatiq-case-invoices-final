# Galatiq Case: Invoice Processing Automation

Working prototype for Acme Corp's invoice processing workflow. It ingests messy invoice files, validates line items against SQLite inventory, runs a VP-style approval loop, and executes or blocks a mock payment.

## What Ships

- Multi-format ingestion for TXT, JSON, CSV, XML, and PDF invoices in `data/invoices/`
- SQLite inventory setup and validation against known stock
- CrewAI approval path using NVIDIA NIM when credentials are configured
- Offline deterministic NIM/CrewAI simulation when no API key or internet is available
- Structured JSON output with per-agent stage logs
- Batch processing and an HTML operations dashboard for reviewer-friendly demos

## Architecture

The pipeline is intentionally small and observable:

1. `Document Ingestion Agent` extracts invoice number, vendor, due date, line items, totals, and source metadata.
2. `Inventory Validation Agent` uses SQLite as a tool to flag unknown items, out-of-stock items, stock overages, negative quantities, and total mismatches.
3. `VP Approval Crew` runs a reviewer plus critic loop. With NIM credentials, this uses CrewAI and NVIDIA NIM. Offline, it uses a deterministic local reasoner that mirrors the same decision rubric.
4. `Payment Agent` calls the mock payment function only after approval, otherwise it records the rejection reason.

## Setup

From the project folder, create and activate a local virtual environment:

```cmd
python -m venv venv
venv\Scripts\activate
```

Your terminal prompt should now start with `(venv)`.

Install the dependencies into that same environment:

```cmd
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Verify CrewAI is installed in the active venv:

```cmd
python -c "import crewai; print(crewai.__file__)"
```

`litellm` is included because CrewAI uses it to route NVIDIA NIM model names such as `nvidia_nim/meta/llama-3.1-70b-instruct`.

The app seeds `inventory.db` automatically on each run with the required starter stock:

```text
WidgetA: 15
WidgetB: 10
GadgetX: 5
FakeItem: 0
```

## NVIDIA NIM + CrewAI

The approval stage uses CrewAI with NVIDIA NIM when these variables are present:

```cmd
set NVIDIA_NIM_API_KEY=your_key
set NVIDIA_NIM_MODEL=meta/llama-3.1-70b-instruct
set NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1
```

If they are absent, the prototype still runs fully offline using `local_nim_simulated_crewai` reasoning. That keeps the demo reliable in no-internet environments while preserving the same reviewer/critic approval semantics.

To confirm the real CrewAI + NIM path is active, run an invoice and check the `llm_provider` field:

```cmd
python main.py --invoice_path data/invoices/invoice_1001.txt --pretty
```

Expected provider when NIM is configured:

```json
"llm_provider": "nvidia_nim/crewai"
```

If you see `local_nim_simulated_crewai`, the app is still working offline, but CrewAI/NIM did not run. Check the NIM key and dependency install.

## Run One Invoice

```cmd
python main.py --invoice_path data/invoices/invoice_1001.txt --pretty
```

The JSON result includes:

- `invoice`: structured extracted data
- `validation`: SQLite inventory findings and risk score
- `approval`: decision, reason, human review flag, provider, and reflection
- `payment_status`: mock payment result when approved
- `stage_logs`: end-to-end agent trace

## Run the Full Batch

```cmd
python main.py --invoice_dir data/invoices --report_path reports/invoice_dashboard.html --pretty
```

Open `reports/invoice_dashboard.html` to review the run as an AP operations dashboard.

## Expected Scenarios

| Scenario | Invoice | Expected behavior |
|---|---|---|
| Normal order within stock | INV-1001, INV-1004, INV-1006 | Pass validation and approve |
| Quantity exceeds stock | INV-1002 | Flag requested GadgetX quantity above stock |
| Zero-stock suspicious item | INV-1003 | Flag FakeItem as out of stock |
| Unknown products | INV-1008, INV-1016 | Flag items not found in inventory |
| Invalid data | INV-1009 | Reject for negative quantity, missing vendor, missing due date, and negative total |
| High-value review | INV-1005, INV-1007 | Apply additional scrutiny through the approval reflection loop |

## Business Framing

This MVP reduces the manual workflow to exception handling. Clean invoices move through extraction, validation, approval, and mock payment in seconds. Risky invoices are blocked with structured reasons that an AP team or VP can review without digging through email chains.
