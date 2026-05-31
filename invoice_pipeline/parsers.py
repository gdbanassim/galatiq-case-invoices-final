from __future__ import annotations

import csv
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .models import InvoiceRecord, LineItem


def parse_invoice_file(path: str | Path) -> InvoiceRecord:
    source_path = str(path)
    suffix = Path(path).suffix.lower()

    if suffix == ".json":
        return parse_json_invoice(Path(path).read_text(encoding="utf-8"), source_path)
    if suffix == ".csv":
        return parse_csv_invoice(Path(path).read_text(encoding="utf-8"), source_path)
    if suffix == ".xml":
        return parse_xml_invoice(Path(path).read_text(encoding="utf-8"), source_path)
    if suffix == ".pdf":
        return parse_pdf_invoice(Path(path), source_path)
    return parse_text_invoice(Path(path).read_text(encoding="utf-8"), source_path)


def parse_text_invoice(text: str, source_path: str = "") -> InvoiceRecord:
    fields = _extract_text_fields(text)
    line_items = _extract_line_items_from_text(text)
    return _build_invoice(
        invoice_number=fields.get("invoice_number", ""),
        vendor=fields.get("vendor", ""),
        date=fields.get("date"),
        due_date=fields.get("due_date"),
        line_items=line_items,
        subtotal=_parse_float(fields.get("subtotal")),
        tax_rate=_parse_float(fields.get("tax_rate")),
        tax_amount=_parse_float(fields.get("tax_amount")),
        total=_parse_float(fields.get("total")),
        currency=fields.get("currency", "USD"),
        payment_terms=fields.get("payment_terms", ""),
        source_path=source_path,
        raw_text=text,
    )


def parse_json_invoice(text: str, source_path: str = "") -> InvoiceRecord:
    payload = json.loads(text)
    vendor = payload.get("vendor") or {}
    line_items = [
        LineItem(
            item=_normalize_item_name(str(line_item.get("item", ""))),
            quantity=int(line_item.get("quantity", 0) or 0),
            unit_price=_parse_float(line_item.get("unit_price")) or 0.0,
            amount=_parse_float(line_item.get("amount")),
            notes=str(line_item.get("notes", "") or ""),
        )
        for line_item in payload.get("line_items", [])
    ]
    return _build_invoice(
        invoice_number=str(payload.get("invoice_number", "")),
        vendor=str(vendor.get("name") or payload.get("vendor", "")),
        date=str(payload.get("date")) if payload.get("date") else None,
        due_date=str(payload.get("due_date")) if payload.get("due_date") else None,
        line_items=line_items,
        subtotal=_parse_float(payload.get("subtotal")),
        tax_rate=_parse_float(payload.get("tax_rate")),
        tax_amount=_parse_float(payload.get("tax_amount")),
        total=_parse_float(payload.get("total")),
        currency=str(payload.get("currency", "USD")),
        payment_terms=str(payload.get("payment_terms", "") or ""),
        source_path=source_path,
        raw_text=text,
    )


def parse_csv_invoice(text: str, source_path: str = "") -> InvoiceRecord:
    rows = list(csv.reader(text.splitlines()))
    if rows and _looks_like_tabular_csv(rows[0]):
        return _parse_tabular_csv_invoice(rows, text, source_path)

    fields: dict[str, list[str]] = {}
    for row in rows[1:]:
        if len(row) < 2:
            continue
        key = row[0].strip().lower()
        value = row[1].strip()
        fields.setdefault(key, []).append(value)

    invoice_number = _first(fields, "invoice_number")
    vendor = _first(fields, "vendor")
    date = _first(fields, "date")
    due_date = _first(fields, "due_date")
    subtotal = _parse_float(_first(fields, "subtotal"))
    tax_amount = _parse_float(_first(fields, "tax")) or _parse_float(_first(fields, "tax_amount"))
    total = _parse_float(_first(fields, "total"))
    payment_terms = _first(fields, "payment_terms")

    line_items: list[LineItem] = []
    pending_item: dict[str, object] | None = None
    for row in rows[1:]:
        if len(row) < 2:
            continue
        key = row[0].strip().lower()
        value = row[1].strip()
        if key == "item":
            if pending_item and pending_item.get("item"):
                line_items.append(_line_item_from_pending(pending_item))
            pending_item = {"item": value}
        elif key == "quantity" and pending_item is not None:
            pending_item["quantity"] = int(float(value))
        elif key == "unit_price" and pending_item is not None:
            pending_item["unit_price"] = _parse_float(value) or 0.0
    if pending_item and pending_item.get("item"):
        line_items.append(_line_item_from_pending(pending_item))

    return _build_invoice(
        invoice_number=invoice_number,
        vendor=vendor,
        date=date,
        due_date=due_date,
        line_items=line_items,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
        payment_terms=payment_terms,
        source_path=source_path,
        raw_text=text,
    )


def _looks_like_tabular_csv(header: list[str]) -> bool:
    normalized = {_normalize_header(value) for value in header}
    return {"invoice_number", "vendor", "item"}.issubset(normalized)


def _parse_tabular_csv_invoice(rows: list[list[str]], raw_text: str, source_path: str) -> InvoiceRecord:
    header = [_normalize_header(value) for value in rows[0]]
    index = {name: position for position, name in enumerate(header)}

    invoice_number = ""
    vendor = ""
    date = ""
    due_date = ""
    line_items: list[LineItem] = []
    subtotal = None
    tax_amount = None
    total = None

    for row in rows[1:]:
        padded = row + [""] * (len(header) - len(row))
        item = padded[index.get("item", -1)].strip() if "item" in index else ""
        if item:
            invoice_number = invoice_number or _clean_invoice_number(_cell(padded, index, "invoice_number"))
            vendor = vendor or _clean_vendor(_cell(padded, index, "vendor"))
            date = date or _normalize_date(_cell(padded, index, "date"))
            due_date = due_date or _normalize_date(_cell(padded, index, "due_date"))
            quantity = int(_parse_float(_cell(padded, index, "qty") or _cell(padded, index, "quantity")) or 0)
            unit_price = _parse_float(_cell(padded, index, "unit_price")) or 0.0
            amount = _parse_float(_cell(padded, index, "line_total"))
            line_items.append(
                LineItem(
                    item=_normalize_item_name(item),
                    quantity=quantity,
                    unit_price=unit_price,
                    amount=amount if amount is not None else round(quantity * unit_price, 2),
                )
            )
            continue

        label = " ".join(value.strip().lower() for value in padded if value.strip())
        amount = _parse_float(padded[-1] if padded else "")
        if "subtotal" in label:
            subtotal = amount
        elif "tax" in label:
            tax_amount = amount
        elif "total" in label:
            total = amount

    return _build_invoice(
        invoice_number=invoice_number,
        vendor=vendor,
        date=date,
        due_date=due_date,
        line_items=line_items,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
        source_path=source_path,
        raw_text=raw_text,
    )


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _cell(row: list[str], index: dict[str, int], name: str) -> str:
    position = index.get(name)
    if position is None or position >= len(row):
        return ""
    return row[position].strip()


def parse_xml_invoice(text: str, source_path: str = "") -> InvoiceRecord:
    root = ET.fromstring(text)
    header = root.find("header")
    totals = root.find("totals")
    line_items_node = root.find("line_items")

    line_items: list[LineItem] = []
    for item_node in list(line_items_node or []):
        line_items.append(
            LineItem(
                item=_normalize_item_name(_text(item_node.find("name"))),
                quantity=int(_parse_float(_text(item_node.find("quantity"))) or 0),
                unit_price=_parse_float(_text(item_node.find("unit_price"))) or 0.0,
                amount=_parse_float(_text(item_node.find("amount"))),
            )
        )

    return _build_invoice(
        invoice_number=_text(header.find("invoice_number") if header is not None else None),
        vendor=_text(header.find("vendor") if header is not None else None),
        date=_text(header.find("date") if header is not None else None),
        due_date=_text(header.find("due_date") if header is not None else None),
        line_items=line_items,
        subtotal=_parse_float(_text(totals.find("subtotal") if totals is not None else None)),
        tax_rate=_parse_float(_text(totals.find("tax_rate") if totals is not None else None)),
        tax_amount=_parse_float(_text(totals.find("tax_amount") if totals is not None else None)),
        total=_parse_float(_text(totals.find("total") if totals is not None else None)),
        currency=_text(header.find("currency") if header is not None else None) or "USD",
        payment_terms=_text(root.find("payment_terms")),
        source_path=source_path,
        raw_text=text,
    )


def parse_pdf_invoice(path: Path, source_path: str = "") -> InvoiceRecord:
    text = _extract_pdf_text(path)
    return parse_text_invoice(text, source_path=source_path)


def _extract_pdf_text(path: Path) -> str:
    try:
        import fitz  # type: ignore

        document = fitz.open(str(path))
        return "\n".join(page.get_text() for page in document)
    except Exception:
        pass

    try:
        import pdfplumber  # type: ignore

        with pdfplumber.open(str(path)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception as exc:
        raise RuntimeError(f"Unable to extract text from PDF {path}: {exc}") from exc


def _extract_text_fields(text: str) -> dict[str, str]:
    normalized = text.replace("\r", "")
    patterns = {
        "invoice_number": [
            r"invoice number\s*[:#]\s*([A-Za-z0-9\- ]+)",
            r"invoice\s*[:#]\s*([A-Za-z0-9\- ]+)",
            r"inv\s*no\.?\s*[:#]?\s*([A-Za-z0-9\- ]+)",
            r"inv\s*#\s*:?\s*([A-Za-z0-9\- ]+)",
        ],
        "vendor": [r"vendor\s*[:#]\s*(.+)", r"from\s*[:#]\s*(.+)", r"vndr\s*[:#]\s*(.+)"],
        "date": [r"date\s*[:#]\s*([^\n]+)", r"dt\s*[:#]\s*([^\n]+)"],
        "due_date": [r"due date\s*[:#]\s*([^\n]+)", r"due dt\s*[:#]\s*([^\n]+)", r"due\s*[:#]\s*([^\n]+)"],
        "subtotal": [r"subtotal\s*[:#]\s*\$?([\d,]+(?:\.\d+)?)"],
        "tax_rate": [r"tax\s*\(([-\d.]+)%\)"],
        "tax_amount": [r"tax(?: amount)?\s*[:#]\s*\$?([\d,]+(?:\.\d+)?)"],
        "total": [r"total(?: amount)?\s*[:#]\s*\$?([\d,]+(?:\.\d+)?)", r"amt\s*[:#]\s*\$?([\d,]+(?:\.\d+)?)"],
        "payment_terms": [r"payment terms\s*[:#]\s*(.+)", r"terms\s*[:#]\s*(.+)", r"pymnt terms\s*[:#]\s*(.+)"],
        "currency": [r"currency\s*[:#]\s*([A-Z]{3})"],
    }

    extracted: dict[str, str] = {}
    for field_name, field_patterns in patterns.items():
        for pattern in field_patterns:
            match = re.search(pattern, normalized, flags=re.IGNORECASE | re.MULTILINE)
            if match:
                extracted[field_name] = match.group(1).strip()
                break

    if "vendor" in extracted:
        extracted["vendor"] = _clean_vendor(extracted["vendor"])
    if "invoice_number" in extracted:
        extracted["invoice_number"] = _clean_invoice_number(extracted["invoice_number"])
    if "date" in extracted:
        extracted["date"] = _normalize_date(extracted["date"])
    if "due_date" in extracted:
        extracted["due_date"] = _normalize_date(extracted["due_date"])
    if "tax_rate" in extracted and extracted["tax_rate"].endswith("%"):
        extracted["tax_rate"] = extracted["tax_rate"].replace("%", "")
    return extracted


def _extract_line_items_from_text(text: str) -> list[LineItem]:
    items: list[LineItem] = []
    seen: set[tuple[str, int, float]] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = _parse_line_item(line)
        if parsed is None:
            continue
        key = (parsed.item, parsed.quantity, parsed.unit_price)
        if key in seen:
            continue
        seen.add(key)
        items.append(parsed)
    return items


def _parse_line_item(line: str) -> LineItem | None:
    compact = re.sub(r"\s+", " ", line.strip())
    patterns = [
        r"^(?:[-*]\s*)?(?P<item>[A-Za-z][A-Za-z0-9\s\-./&]+?)\s+(?:qty|quantity|x)\s*[:=]?\s*(?P<qty>-?\d+)\s*(?:@|at|unit price|price)?\s*[:=]?\s*\$?(?P<price>[\d,]+(?:\.\d+)?)",
        r"^(?:[-*]\s*)?(?P<item>[A-Za-z][A-Za-z0-9\s\-./&]+?)\s+x(?P<qty>-?\d+)\s*\$?(?P<price>[\d,]+(?:\.\d+)?)\s*(?:each|ea|per item)?$",
        r"^(?P<item>[A-Za-z][A-Za-z0-9\s\-./&]+?)\s+(?P<qty>-?\d+)\s+\$?(?P<price>[\d,]+(?:\.\d+)?)\s*(?:each|ea)?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact, flags=re.IGNORECASE)
        if match:
            item = _normalize_item_name(match.group("item"))
            quantity = int(match.group("qty"))
            unit_price = _parse_float(match.group("price")) or 0.0
            amount = round(quantity * unit_price, 2)
            return LineItem(item=item, quantity=quantity, unit_price=unit_price, amount=amount)
    return None


def _build_invoice(
    *,
    invoice_number: str,
    vendor: str,
    date: str | None,
    due_date: str | None,
    line_items: list[LineItem],
    subtotal: float | None = None,
    tax_rate: float | None = None,
    tax_amount: float | None = None,
    total: float | None = None,
    currency: str = "USD",
    payment_terms: str = "",
    source_path: str = "",
    raw_text: str = "",
) -> InvoiceRecord:
    invoice = InvoiceRecord(
        invoice_number=invoice_number,
        vendor=vendor,
        date=date,
        due_date=due_date,
        line_items=line_items,
        subtotal=subtotal,
        tax_rate=tax_rate,
        tax_amount=tax_amount,
        total=total,
        currency=currency or "USD",
        payment_terms=payment_terms,
        source_path=source_path,
        raw_text=raw_text,
    )
    if invoice.line_items and invoice.subtotal is None:
        invoice = replace(invoice, subtotal=invoice.computed_subtotal())
    if invoice.total is None and invoice.subtotal is not None:
        invoice = replace(invoice, total=invoice.computed_total())
    return invoice


def _line_item_from_pending(pending_item: dict[str, object]) -> LineItem:
    return LineItem(
        item=_normalize_item_name(str(pending_item.get("item", ""))),
        quantity=int(pending_item.get("quantity", 0) or 0),
        unit_price=float(pending_item.get("unit_price", 0.0) or 0.0),
        amount=round(int(pending_item.get("quantity", 0) or 0) * float(pending_item.get("unit_price", 0.0) or 0.0), 2),
    )


def _normalize_item_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9\s]", "", value).strip()
    if not cleaned:
        return cleaned
    parts = re.split(r"[\s_-]+", cleaned)
    if len(parts) == 1:
        return parts[0]
    normalized = parts[0]
    for part in parts[1:]:
        normalized += part[:1].upper() + part[1:]
    return normalized


def _clean_vendor(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().rstrip(".,")


def _clean_invoice_number(value: str) -> str:
    compact = re.sub(r"\s+", "", value).upper()
    if compact.isdigit():
        return f"INV-{compact}"
    if compact.startswith("INV") and not compact.startswith("INV-") and len(compact) > 3:
        return f"INV-{compact[3:]}"
    return compact


def _normalize_date(value: str) -> str:
    value = value.strip()
    formats = ["%Y-%m-%d", "%d-%b-%Y", "%d-%b-%y", "%b %d %Y", "%m/%d/%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return value


def _parse_float(value: object | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("$", "").replace(",", "")
    text = text.replace("O", "0").replace("o", "0")
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _text(node: ET.Element | None) -> str:
    return (node.text or "").strip() if node is not None else ""


def _first(mapping: dict[str, list[str]], key: str) -> str:
    values = mapping.get(key, [])
    return values[0] if values else ""
