from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from invoice_pipeline.reporting import render_dashboard
from invoice_pipeline.workflow import run_workflow

SUPPORTED_EXTENSIONS = {".txt", ".json", ".csv", ".xml", ".pdf"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the invoice processing workflow.")
    parser.add_argument("--invoice_path", help="Path to one invoice file to process.")
    parser.add_argument("--invoice_dir", help="Directory of invoice files to process as a batch.")
    parser.add_argument("--db_path", default="inventory.db", help="Path to the local SQLite inventory database.")
    parser.add_argument("--report_path", help="Write an HTML dashboard for the run.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the final JSON result.")
    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("LiteLLM").setLevel(logging.ERROR)
    logging.getLogger("litellm").setLevel(logging.ERROR)
    args = build_parser().parse_args()
    invoice_paths = _resolve_invoice_paths(args.invoice_path, args.invoice_dir)
    results = [run_workflow(path, Path(args.db_path)) for path in invoice_paths]

    if args.report_path:
        report_path = render_dashboard(results, args.report_path)
        logging.info("dashboard_written path=%s", report_path)

    payload = results[0].to_dict() if len(results) == 1 else [result.to_dict() for result in results]
    if args.pretty:
        print(json.dumps(payload, indent=2))
    else:
        print(json.dumps(payload, separators=(",", ":")))
    return 0


def _resolve_invoice_paths(invoice_path: str | None, invoice_dir: str | None) -> list[Path]:
    if bool(invoice_path) == bool(invoice_dir):
        raise SystemExit("Provide exactly one of --invoice_path or --invoice_dir.")

    if invoice_path:
        path = Path(invoice_path)
        if not path.exists():
            raise SystemExit(f"Invoice path does not exist: {path}")
        return [path]

    directory = Path(invoice_dir or "")
    if not directory.exists() or not directory.is_dir():
        raise SystemExit(f"Invoice directory does not exist: {directory}")

    invoice_paths = sorted(path for path in directory.iterdir() if path.suffix.lower() in SUPPORTED_EXTENSIONS)
    if not invoice_paths:
        raise SystemExit(f"No supported invoice files found in: {directory}")
    return invoice_paths


if __name__ == "__main__":
    raise SystemExit(main())
