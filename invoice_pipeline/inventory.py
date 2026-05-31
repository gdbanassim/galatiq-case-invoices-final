from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import InvoiceRecord, ValidationIssue, ValidationResult


DEFAULT_INVENTORY = {
    "WidgetA": 15,
    "WidgetB": 10,
    "GadgetX": 5,
    "FakeItem": 0,
}


def ensure_inventory_db(db_path: str | Path) -> None:
    db_file = Path(db_path)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_file) as connection:
        cursor = connection.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS inventory (item TEXT PRIMARY KEY, stock INTEGER NOT NULL)")
        for item, stock in DEFAULT_INVENTORY.items():
            cursor.execute(
                "INSERT INTO inventory(item, stock) VALUES (?, ?) ON CONFLICT(item) DO UPDATE SET stock=excluded.stock",
                (item, stock),
            )
        connection.commit()


def load_inventory(db_path: str | Path) -> dict[str, int]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT item, stock FROM inventory ORDER BY item").fetchall()
    return {item: int(stock) for item, stock in rows}


def validate_invoice(invoice: InvoiceRecord, db_path: str | Path) -> ValidationResult:
    inventory = load_inventory(db_path)
    issues: list[ValidationIssue] = []
    risk_score = 0

    if not invoice.invoice_number:
        issues.append(ValidationIssue("high", "invoice_number", "Missing invoice number."))
        risk_score += 30
    if not invoice.vendor:
        issues.append(ValidationIssue("high", "vendor", "Missing vendor name."))
        risk_score += 30
    if not invoice.date:
        issues.append(ValidationIssue("medium", "date", "Missing invoice date."))
        risk_score += 10
    if not invoice.due_date:
        issues.append(ValidationIssue("medium", "due_date", "Missing due date."))
        risk_score += 10
    if invoice.total is not None and invoice.total < 0:
        issues.append(ValidationIssue("high", "total", "Invoice total is negative."))
        risk_score += 50

    for line_item in invoice.line_items:
        if line_item.quantity <= 0:
            issues.append(ValidationIssue("high", f"line_items.{line_item.item}.quantity", "Quantity must be positive."))
            risk_score += 35
        stock = inventory.get(line_item.item)
        if stock is None:
            issues.append(ValidationIssue("high", f"line_items.{line_item.item}", "Item not found in inventory."))
            risk_score += 35
        elif line_item.quantity > stock:
            issues.append(
                ValidationIssue(
                    "high",
                    f"line_items.{line_item.item}",
                    f"Requested quantity {line_item.quantity} exceeds stock {stock}.",
                )
            )
            risk_score += 25
        elif stock == 0:
            issues.append(ValidationIssue("high", f"line_items.{line_item.item}", "Item is out of stock."))
            risk_score += 20

    expected_subtotal = invoice.computed_subtotal() if invoice.line_items else 0.0
    if invoice.subtotal is not None and abs(invoice.subtotal - expected_subtotal) > 0.05:
        issues.append(
            ValidationIssue(
                "medium",
                "subtotal",
                f"Subtotal mismatch: extracted {invoice.subtotal:.2f} vs computed {expected_subtotal:.2f}.",
            )
        )
        risk_score += 10

    if invoice.total is not None:
        expected_total = round((invoice.subtotal if invoice.subtotal is not None else expected_subtotal) + (invoice.tax_amount or 0.0), 2)
        if abs(invoice.total - expected_total) > 0.05:
            issues.append(
                ValidationIssue(
                    "medium",
                    "total",
                    f"Total mismatch: extracted {invoice.total:.2f} vs computed {expected_total:.2f}.",
                )
            )
            risk_score += 10

    is_valid = not any(issue.severity == "high" for issue in issues)
    return ValidationResult(is_valid=is_valid, issues=issues, inventory_snapshot=inventory, risk_score=risk_score)
