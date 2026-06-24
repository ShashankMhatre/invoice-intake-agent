from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from models import InvoicePayload


def format_money(value: Decimal | None, currency: str | None = None) -> str:
    """Format a monetary value for human-readable output."""

    if value is None:
        return "Not available"

    formatted = f"{value:,.2f}"
    return f"{formatted} {currency}" if currency else formatted


def build_customer_service_message(payload: InvoicePayload) -> str:
    """Create the human-readable Customer Service notification."""

    tax_lines = "\n".join(
        (
            f"- {tax.jurisdiction}: {tax.tax_type} {tax.tax_rate or ''} — "
            f"{format_money(tax.tax_amount, payload.currency)}"
        ).strip()
        for tax in payload.taxes
    ) or "- No tax breakdown available"

    location_lines = "\n".join(
        (
            f"- {location.site_name} ({location.cost_centre})\n"
            f"  Delivery window: {location.delivery_window or 'Not available'}\n"
            f"  Receiving hours: {location.receiving_hours or 'Not available'}"
        )
        for location in payload.ship_to_locations
    ) or "- No ship-to locations available"

    note_lines = "\n".join(
        f"- {note}" for note in payload.important_notes
    ) or "- No additional notes"

    duplicate_warning = payload.duplicate_warning or "No duplicate warning identified."

    return f"""Subject: Invoice Intake Summary — {payload.vendor.name or 'Unknown Vendor'} / {payload.customer_po or 'No PO'}

Hi Customer Service team,

Please process the following vendor invoice.

Invoice Summary
- Vendor: {payload.vendor.name or 'Not available'}
- Invoice Number: {payload.invoice_number or 'Not available'}
- Invoice Date: {payload.invoice_date or 'Not available'}
- Due Date: {payload.due_date or 'Not available'}
- Payment Terms: {payload.payment_terms or 'Not available'}
- Customer PO: {payload.customer_po or 'Not available'}
- Customer Account: {payload.customer_account or 'Not available'}
- Project: {payload.project_name or 'Not available'}
- Currency: {payload.currency or 'Not available'}
- Subtotal: {format_money(payload.subtotal, payload.currency)}
- Total Tax: {format_money(payload.total_tax, payload.currency)}
- Total Due: {format_money(payload.total_due, payload.currency)}
- Number of Line Items: {len(payload.line_items)}

Tax Breakdown
{tax_lines}

Ship-To Locations
{location_lines}

Approval Cost Centres
{chr(10).join(f"- {cost_centre}" for cost_centre in payload.cost_centres)}

Important Notes
{note_lines}

Duplicate Review
- {duplicate_warning}

A structured JSON payload has also been generated for downstream processing.
"""


def send_customer_service_notification(
    payload: InvoicePayload,
    output_directory: Path = Path("outputs"),
) -> dict[str, str]:
    """
    Simulate sending a Customer Service notification by writing output files.
    """

    output_directory.mkdir(parents=True, exist_ok=True)

    email_path = output_directory / "outbound_email.txt"
    payload_path = output_directory / "outbound_payload.json"

    email_path.write_text(
        build_customer_service_message(payload),
        encoding="utf-8",
    )

    payload_path.write_text(
        json.dumps(
            payload.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return {
        "email_output": str(email_path),
        "json_output": str(payload_path),
    }