from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import fitz

from models import (
    AllocationItem,
    InvoiceImageSummary,
    InvoicePayload,
    LineItem,
    ShipToLocation,
    SourceEmail,
    TaxDetail,
    Vendor,
)

def load_email(email_path: Path) -> dict[str, Any]:
    """Load and validate the inbound email JSON file."""

    if not email_path.exists():
        raise FileNotFoundError(f"Email file not found: {email_path}")

    try:
        with email_path.open("r", encoding="utf-8") as file:
            email_data = json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid email JSON: {exc}") from exc

    if "Message" not in email_data:
        raise ValueError("Email JSON does not contain a Message object.")

    return email_data


def get_attachment_path(email_data: dict[str, Any], email_path: Path) -> Path:
    """Resolve the first PDF attachment referenced by the email."""

    attachments = email_data.get("Message", {}).get("Attachments", [])

    if not attachments:
        raise ValueError("No attachments were listed in the email.")

    pdf_attachment = next(
        (
            attachment
            for attachment in attachments
            if attachment.get("ContentType") == "application/pdf"
            or str(attachment.get("Name", "")).lower().endswith(".pdf")
        ),
        None,
    )

    if not pdf_attachment:
        raise ValueError("No PDF attachment was listed in the email.")

    attachment_name = pdf_attachment.get("Name")

    if not attachment_name:
        raise ValueError("The PDF attachment does not have a filename.")

    attachment_path = email_path.parent / attachment_name

    if not attachment_path.exists():
        raise FileNotFoundError(
            f"Attachment referenced by the email was not found: {attachment_path}"
        )

    return attachment_path


def extract_pdf_text(pdf_path: Path) -> tuple[str, int]:
    """Extract searchable text from all PDF pages."""

    try:
        document = fitz.open(pdf_path)
    except Exception as exc:
        raise ValueError(f"Unable to open PDF: {exc}") from exc

    try:
        page_text = [page.get_text("text") for page in document]
        return "\n".join(page_text), document.page_count
    finally:
        document.close()


def first_match(
    pattern: str,
    text: str,
    flags: int = re.IGNORECASE | re.MULTILINE,
) -> str | None:
    """Return the first captured regex group, or None."""

    match = re.search(pattern, text, flags)

    if not match:
        return None

    return match.group(1).strip()


def parse_decimal(value: str | None) -> Decimal | None:
    """Convert formatted monetary text into Decimal."""

    if not value:
        return None

    cleaned = re.sub(r"[^\d.\-]", "", value)

    if not cleaned:
        return None

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def extract_recipient_addresses(recipients: list[dict[str, Any]]) -> list[str]:
    """Extract email addresses from Microsoft Graph recipient objects."""

    addresses: list[str] = []

    for recipient in recipients:
        address = recipient.get("EmailAddress", {}).get("Address")

        if address:
            addresses.append(address)

    return addresses


def extract_source_email(email_data: dict[str, Any]) -> SourceEmail:
    """Extract useful metadata and instructions from the inbound email."""

    message = email_data.get("Message", {})
    sender = message.get("From", {}).get("EmailAddress", {})
    body = message.get("Body", {}).get("Content", "")
    attachments = message.get("Attachments", [])

    body_notes: list[str] = []

    if re.search(r"taxes?.*ship-to jurisdiction", body, re.IGNORECASE):
        body_notes.append("Apply taxes according to the ship-to jurisdiction.")

    if re.search(r"route for approval", body, re.IGNORECASE):
        body_notes.append("Route the invoice using the listed cost centres.")

    if re.search(r"appointment-based", body, re.IGNORECASE):
        body_notes.append("Deliveries require appointment-based scheduling.")

    return SourceEmail(
        subject=message.get("Subject"),
        sender_name=sender.get("Name"),
        sender_address=sender.get("Address"),
        sent_datetime=message.get("SentDateTime"),
        to_recipients=extract_recipient_addresses(
            message.get("ToRecipients", [])
        ),
        cc_recipients=extract_recipient_addresses(
            message.get("CcRecipients", [])
        ),
        attachment_name=attachments[0].get("Name") if attachments else None,
        body_notes=body_notes,
    )


def extract_vendor_name(pdf_text: str) -> str | None:
    """Find a likely legal vendor name in the PDF text."""

    patterns = [
        r"(?m)^([^\n]{2,100}\bInc\.)\s*$",
        r"(?m)^([^\n]{2,100}\bLtd\.)\s*$",
        r"(?m)^([^\n]{2,100}\bCorporation)\s*$",
        r"(?m)^([^\n]{2,100}\bLLC)\s*$",
    ]

    for pattern in patterns:
        value = first_match(pattern, pdf_text)

        if value:
            return value

    return None

def clean_pdf_value(value: str | None) -> str | None:
    """Clean common character artifacts introduced during PDF extraction."""

    if value is None:
        return None

    return (
        value.replace("ò", ":")
        .replace("\u00a0", " ")
        .strip()
    )


def extract_line_items(pdf_text: str) -> list[LineItem]:
    """Extract the itemized charge table from the searchable PDF text."""

    section_match = re.search(
        r"Itemized Charges \(Contract Pricing — CAD\)"
        r"(.*?)"
        r"(?=Subtotal \(before tax\):)",
        pdf_text,
        re.DOTALL,
    )

    if not section_match:
        return []

    raw_lines = [
        line.strip()
        for line in section_match.group(1).splitlines()
        if line.strip()
    ]

    table_headers = {
        "Line",
        "SKU",
        "Description",
        "Qty",
        "Unit",
        "Price",
        "Line Total",
        "Assignment.md",
    }

    lines = [
        line
        for line in raw_lines
        if line not in table_headers
        and not re.fullmatch(r"\d+\s*/\s*\d+", line)
        and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", line)
    ]

    money_pattern = re.compile(r"^\d[\d,]*\.\d{2}$")
    sku_part_pattern = re.compile(r"^[A-Z0-9-]+$")

    line_items: list[LineItem] = []
    index = 0
    expected_line_number = 1

    while index < len(lines):
        if lines[index] != str(expected_line_number):
            index += 1
            continue

        line_number = expected_line_number
        index += 1

        sku_parts: list[str] = []

        while (
            index < len(lines)
            and sku_part_pattern.fullmatch(lines[index])
            and not lines[index].isdigit()
        ):
            sku_parts.append(lines[index])
            index += 1

        sku = "".join(sku_parts)
        description_parts: list[str] = []
        row_completed = False

        while index + 2 < len(lines):
            quantity_candidate = lines[index]
            unit_price_candidate = lines[index + 1]
            line_total_candidate = lines[index + 2]

            if (
                re.fullmatch(r"\d+", quantity_candidate)
                and money_pattern.fullmatch(unit_price_candidate)
                and money_pattern.fullmatch(line_total_candidate)
            ):
                line_items.append(
                    LineItem(
                        line_number=line_number,
                        sku=sku,
                        description=" ".join(description_parts),
                        quantity=parse_decimal(quantity_candidate),
                        unit_price=parse_decimal(unit_price_candidate),
                        line_total=parse_decimal(line_total_candidate),
                    )
                )

                index += 3
                expected_line_number += 1
                row_completed = True
                break

            description_parts.append(lines[index])
            index += 1

        if not row_completed:
            break

    return line_items


def extract_tax_details(pdf_text: str) -> list[TaxDetail]:
    """Extract jurisdiction-level tax details."""

    section_match = re.search(
        r"Tax Summary \(Based on Ship-To Jurisdiction\)"
        r"(.*?)"
        r"(?=Total Tax:)",
        pdf_text,
        re.DOTALL,
    )

    if not section_match:
        return []

    raw_lines = [
        line.strip()
        for line in section_match.group(1).splitlines()
        if line.strip()
    ]

    table_headers = {
        "Jurisdiction",
        "Taxable Amount",
        "Tax Type",
        "Tax Amount",
        "Assignment.md",
    }

    lines = [
        line
        for line in raw_lines
        if line not in table_headers
        and not re.fullmatch(r"\d+\s*/\s*\d+", line)
        and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", line)
    ]

    taxes: list[TaxDetail] = []

    for index in range(0, len(lines), 4):
        row = lines[index:index + 4]

        if len(row) != 4:
            break

        jurisdiction, taxable_amount, tax_type_with_rate, tax_amount = row

        rate_match = re.search(
            r"(\d+(?:\.\d+)?%)",
            tax_type_with_rate,
        )

        tax_rate = rate_match.group(1) if rate_match else None
        tax_type = (
            tax_type_with_rate.replace(tax_rate, "").strip()
            if tax_rate
            else tax_type_with_rate
        )

        taxes.append(
            TaxDetail(
                jurisdiction=jurisdiction,
                taxable_amount=parse_decimal(taxable_amount),
                tax_type=tax_type,
                tax_rate=tax_rate,
                tax_amount=parse_decimal(tax_amount),
            )
        )

    return taxes


def extract_ship_to_locations(pdf_text: str) -> list[ShipToLocation]:
    """Extract receiving addresses and site-level product allocations."""

    address_by_site: dict[str, dict[str, str | None]] = {}

    address_section_match = re.search(
        r"Ship To \(Multi-Site Delivery\)"
        r"(.*?)"
        r"(?=Primary Project:)",
        pdf_text,
        re.DOTALL,
    )

    if address_section_match:
        address_section = address_section_match.group(1)

        address_headers = list(
            re.finditer(
                r"(?m)^Site ([A-Z]) — (.+)$",
                address_section,
            )
        )

        for index, header in enumerate(address_headers):
            site_letter = header.group(1)
            site_name = header.group(2).strip()

            block_start = header.end()
            block_end = (
                address_headers[index + 1].start()
                if index + 1 < len(address_headers)
                else len(address_section)
            )

            block_lines = [
                line.strip()
                for line in address_section[block_start:block_end].splitlines()
                if line.strip()
            ]

            attention = None
            receiving_hours = None
            address_lines: list[str] = []

            for line in block_lines:
                if line.startswith("Attn:"):
                    attention = line.split(":", 1)[1].strip()
                elif (
                    line.startswith("Receiving Hours:")
                    or line.startswith("Heures de réception:")
                ):
                    receiving_hours = line.split(":", 1)[1].strip()
                else:
                    address_lines.append(line)

            address_by_site[site_letter] = {
                "site_name": site_name,
                "attention": attention,
                "address": "\n".join(address_lines),
                "receiving_hours": clean_pdf_value(receiving_hours),
            }

    allocation_section_match = re.search(
        r"Delivery Allocation by Site \(Operational Breakdown\)"
        r"(.*?)"
        r"(?=Packing List Summary)",
        pdf_text,
        re.DOTALL,
    )

    if not allocation_section_match:
        return []

    allocation_section = allocation_section_match.group(1)

    allocation_section = re.sub(
        r"(?m)^(?:Assignment\.md|\d{4}-\d{2}-\d{2}|\d+\s*/\s*\d+)\s*$",
        "",
        allocation_section,
    )

    allocation_headers = list(
        re.finditer(
            r"(?m)^Site ([A-Z]) — "
            r"(.+?) "
            r"\(([A-Z]{3}-[A-Z]{3}-\d{3})\)\s*$",
            allocation_section,
        )
    )

    locations: list[ShipToLocation] = []

    for index, header in enumerate(allocation_headers):
        site_letter = header.group(1)
        allocation_site_name = header.group(2).strip()
        cost_centre = header.group(3)

        block_start = header.end()
        block_end = (
            allocation_headers[index + 1].start()
            if index + 1 < len(allocation_headers)
            else len(allocation_section)
        )

        block_lines = [
            line.strip()
            for line in allocation_section[block_start:block_end].splitlines()
            if line.strip()
        ]

        allocations: list[AllocationItem] = []
        delivery_service = None
        delivery_window = None

        for line in block_lines:
            if line.startswith("Delivery Service:"):
                delivery_service = line.split(":", 1)[1].strip()
                continue

            if line.startswith("Preferred Delivery Window:"):
                delivery_window = line.split(":", 1)[1].strip()
                continue

            allocation_match = re.match(
                r"^([A-Z0-9-]+)\s+Qty\s+(\d+)(?:\s+(.*))?$",
                line,
            )

            if allocation_match:
                sku, quantity, notes = allocation_match.groups()

                allocations.append(
                    AllocationItem(
                        sku=sku,
                        quantity=parse_decimal(quantity),
                        notes=notes,
                    )
                )

        address_information = address_by_site.get(site_letter, {})

        locations.append(
            ShipToLocation(
                site_name=(
                    address_information.get("site_name")
                    or allocation_site_name
                ),
                cost_centre=cost_centre,
                attention=address_information.get("attention"),
                address=address_information.get("address"),
                receiving_hours=address_information.get("receiving_hours"),
                delivery_window=clean_pdf_value(delivery_window),
                delivery_service=delivery_service,
                allocations=allocations,
            )
        )

    return locations


def extract_local_invoice_data(
    email_data: dict[str, Any],
    pdf_text: str,
    page_count: int,
) -> InvoicePayload:
    """
    Extract invoice data using deterministic local parsing.

    Image-only fields may remain empty and will be handled in the
    later vision-model checkpoint.
    """

    message = email_data.get("Message", {})
    email_body = message.get("Body", {}).get("Content", "")

    invoice_number = first_match(
        r"Invoice\s*Number\s*:?\s*([A-Z0-9\-]+)",
        pdf_text,
    )

    invoice_date = first_match(
        r"Invoice\s*Date\s*:?\s*(\d{4}-\d{2}-\d{2})",
        pdf_text,
    )

    due_date = first_match(
        r"Due\s*Date\s*:?\s*(\d{4}-\d{2}-\d{2})",
        pdf_text,
    )

    payment_terms = first_match(
        r"\bterms?\s*:?\s*(Net\s+\d+)\b",
        f"{email_body}\n{pdf_text}",
    )

    customer_account = first_match(
        r"Customer\s*Account\s*:?\s*([A-Z0-9\-]+)",
        pdf_text,
    )

    customer_po = first_match(
        r"(MLHG-PO-\d+)",
        f"{email_body}\n{pdf_text}",
    )

    project_name = first_match(
        r'Primary\s*Project\s*:?\s*[“"]([^”"]+)[”"]',
        pdf_text,
    )

    subtotal = parse_decimal(
        first_match(
            r"Subtotal\s*\(before tax\)\s*:?\s*([\d,]+\.\d{2})",
            pdf_text,
        )
    )

    total_tax = parse_decimal(
        first_match(
            r"Total\s*Tax\s*:?\s*([\d,]+\.\d{2})",
            pdf_text,
        )
    )

    total_due = parse_decimal(
        first_match(
            r"Total\s*Due(?:\s*\(CAD\))?\s*:?\s*([\d,]+\.\d{2})",
            pdf_text,
        )
    )

    currency = (
        "CAD"
        if re.search(r"\bCAD\b|Total\s*Due\s*\(CAD\)", pdf_text, re.IGNORECASE)
        else None
    )

    cost_centres = sorted(
        set(
            re.findall(
                r"\b[A-Z]{3}-[A-Z]{3}-\d{3}\b",
                f"{email_body}\n{pdf_text}",
            )
        )
    )

    important_notes: list[str] = []

    if re.search(r"appointment required", pdf_text, re.IGNORECASE):
        important_notes.append(
            "Receiving appointments are required for one or more delivery sites."
        )

    if re.search(
        r"Report any freight damage within\s*48 hours",
        pdf_text,
        re.IGNORECASE,
    ):
        important_notes.append(
            "Freight damage must be reported within 48 hours of delivery."
        )

    if re.search(r"retain all packaging", pdf_text, re.IGNORECASE):
        important_notes.append(
            "Retain packaging until inventory verification is complete."
        )

    duplicate_warning = None

    if re.search(
        r"Potential duplicates|preliminary quote|duplication",
        email_body,
        re.IGNORECASE,
    ):
        duplicate_warning = (
            "A preliminary quote was previously received. "
            "Check the system for a possible duplicate before processing."
        )

    warnings: list[str] = []

    if not invoice_number:
        warnings.append(
            "Invoice number was not found in searchable PDF text; "
            "page-image extraction is required."
        )

    if not invoice_date:
        warnings.append(
            "Invoice date was not found in searchable PDF text."
        )

    if not due_date:
        warnings.append(
            "Due date was not found in searchable PDF text."
        )

    line_items = extract_line_items(pdf_text)
    taxes = extract_tax_details(pdf_text)
    ship_to_locations = extract_ship_to_locations(pdf_text)

    if not line_items:
        warnings.append("No invoice line items were extracted.")

    if not taxes:
        warnings.append("No tax breakdown was extracted.")

    if not ship_to_locations:
        warnings.append("No ship-to locations were extracted.")

    if line_items and subtotal is not None:
        calculated_subtotal = sum(
            (
                item.line_total
                for item in line_items
                if item.line_total is not None
            ),
            Decimal("0"),
        )

        if calculated_subtotal != subtotal:
            warnings.append(
                "The sum of extracted line totals does not match the subtotal."
            )

    if taxes and total_tax is not None:
        calculated_tax = sum(
            (
                tax.tax_amount
                for tax in taxes
                if tax.tax_amount is not None
            ),
            Decimal("0"),
        )

        if calculated_tax != total_tax:
            warnings.append(
                "The sum of extracted tax amounts does not match total tax."
            )

    payload = InvoicePayload(
        vendor=Vendor(name=extract_vendor_name(pdf_text)),
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        due_date=due_date,
        payment_terms=payment_terms,
        currency=currency,
        customer_account=customer_account,
        customer_po=customer_po,
        project_name=project_name,
        subtotal=subtotal,
        total_tax=total_tax,
        total_due=total_due,
        taxes=taxes,
        line_items=line_items,
        ship_to_locations=ship_to_locations,
        cost_centres=cost_centres,
        important_notes=important_notes,
        duplicate_warning=duplicate_warning,
        source_email=extract_source_email(email_data),
        pdf_page_count=page_count,
        extraction_warnings=warnings,
    )

    return payload


def merge_image_summary(
    payload: InvoicePayload,
    image_summary: InvoiceImageSummary,
) -> InvoicePayload:
    """Merge page-image fields into the locally extracted invoice payload."""

    fields_to_merge = [
        "invoice_number",
        "invoice_date",
        "due_date",
        "total_due",
        "customer_account",
        "customer_po",
    ]

    updates: dict[str, object] = {}

    for field_name in fields_to_merge:
        image_value = getattr(image_summary, field_name)
        local_value = getattr(payload, field_name)

        if image_value is None:
            continue

        if local_value is not None and local_value != image_value:
            payload.extraction_warnings.append(
                f"Image value for {field_name} differed from the local "
                f"PDF-text value. Image value was used."
            )

        updates[field_name] = image_value

    merged_payload = payload.model_copy(update=updates)

    resolved_warning_prefixes = {
        "Invoice number was not found",
        "Invoice date was not found",
        "Due date was not found",
    }

    merged_payload.extraction_warnings = [
        warning
        for warning in merged_payload.extraction_warnings
        if not any(
            warning.startswith(prefix)
            for prefix in resolved_warning_prefixes
        )
    ]

    return merged_payload
