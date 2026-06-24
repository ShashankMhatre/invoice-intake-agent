from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from extractor import (
    extract_local_invoice_data,
    extract_pdf_text,
    get_attachment_path,
    load_email,
    merge_image_summary,
)
from models import InvoiceImageSummary
from notifier import send_customer_service_notification


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EMAIL_PATH = PROJECT_ROOT / "data" / "Email.json"


def build_local_payload():
    email_data = load_email(EMAIL_PATH)
    pdf_path = get_attachment_path(email_data, EMAIL_PATH)
    pdf_text, page_count = extract_pdf_text(pdf_path)

    return extract_local_invoice_data(
        email_data=email_data,
        pdf_text=pdf_text,
        page_count=page_count,
    )


def test_local_invoice_extraction() -> None:
    payload = build_local_payload()

    assert payload.vendor.name == "Northbridge Office Furnishings Inc."
    assert payload.customer_po == "MLHG-PO-104772"
    assert payload.currency == "CAD"

    assert payload.subtotal == Decimal("113983.69")
    assert payload.total_tax == Decimal("15166.37")
    assert payload.total_due == Decimal("129150.06")

    assert len(payload.line_items) == 12
    assert len(payload.taxes) == 3
    assert len(payload.ship_to_locations) == 3

    assert [
        len(location.allocations)
        for location in payload.ship_to_locations
    ] == [6, 8, 6]

    assert payload.cost_centres == [
        "MTL-ADM-038",
        "OTT-TRN-114",
        "TOR-OPS-221",
    ]


def test_image_summary_merge() -> None:
    payload = build_local_payload()

    image_summary = InvoiceImageSummary(
        invoice_number="NBX-260126-0174",
        invoice_date="2026-01-26",
        due_date="2026-02-25",
        total_due=Decimal("129150.06"),
        customer_account="004913-MLHG",
        customer_po="MLHG-PO-104772",
    )

    merged = merge_image_summary(payload, image_summary)

    assert merged.invoice_number == "NBX-260126-0174"
    assert str(merged.invoice_date) == "2026-01-26"
    assert str(merged.due_date) == "2026-02-25"
    assert merged.customer_account == "004913-MLHG"
    assert merged.total_due == Decimal("129150.06")

    assert not any(
        warning.startswith("Invoice number was not found")
        for warning in merged.extraction_warnings
    )


def test_notification_outputs(tmp_path: Path) -> None:
    payload = build_local_payload()

    image_summary = InvoiceImageSummary(
        invoice_number="NBX-260126-0174",
        invoice_date="2026-01-26",
        due_date="2026-02-25",
        total_due=Decimal("129150.06"),
        customer_account="004913-MLHG",
        customer_po="MLHG-PO-104772",
    )

    payload = merge_image_summary(payload, image_summary)

    outputs = send_customer_service_notification(
        payload,
        output_directory=tmp_path,
    )

    email_path = Path(outputs["email_output"])
    json_path = Path(outputs["json_output"])

    assert email_path.exists()
    assert json_path.exists()

    email_text = email_path.read_text(encoding="utf-8")

    assert "Northbridge Office Furnishings Inc." in email_text
    assert "NBX-260126-0174" in email_text
    assert "MLHG-PO-104772" in email_text
    assert "129,150.06 CAD" in email_text

    structured_payload = json.loads(
        json_path.read_text(encoding="utf-8")
    )

    assert structured_payload["invoice_number"] == "NBX-260126-0174"
    assert str(structured_payload["total_due"]) == "129150.06"
    assert len(structured_payload["line_items"]) == 12
