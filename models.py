from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class Vendor(BaseModel):
    """Vendor information extracted from the invoice."""

    name: str | None = None
    address: str | None = None
    phone: str | None = None
    accounts_receivable_email: str | None = None
    tax_registration_numbers: list[str] = Field(default_factory=list)


class TaxDetail(BaseModel):
    """Individual tax amount for a jurisdiction."""

    jurisdiction: str | None = None
    taxable_amount: Decimal | None = None
    tax_type: str | None = None
    tax_rate: str | None = None
    tax_amount: Decimal | None = None


class LineItem(BaseModel):
    """A single invoice line item."""

    line_number: int | None = None
    sku: str | None = None
    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None


class AllocationItem(BaseModel):
    """A product or service allocated to a delivery site."""

    sku: str | None = None
    quantity: Decimal | None = None
    notes: str | None = None


class ShipToLocation(BaseModel):
    """Ship-to location and delivery allocation."""

    site_name: str | None = None
    cost_centre: str | None = None
    attention: str | None = None
    address: str | None = None
    receiving_hours: str | None = None
    delivery_window: str | None = None
    delivery_service: str | None = None
    allocations: list[AllocationItem] = Field(default_factory=list)


class SourceEmail(BaseModel):
    """Relevant metadata and instructions from the inbound email."""

    subject: str | None = None
    sender_name: str | None = None
    sender_address: str | None = None
    sent_datetime: str | None = None
    to_recipients: list[str] = Field(default_factory=list)
    cc_recipients: list[str] = Field(default_factory=list)
    attachment_name: str | None = None
    body_notes: list[str] = Field(default_factory=list)


class InvoicePayload(BaseModel):
    """Complete structured invoice-intake payload."""

    vendor: Vendor = Field(default_factory=Vendor)

    invoice_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    payment_terms: str | None = None
    currency: str | None = None
    customer_account: str | None = None
    customer_po: str | None = None
    project_name: str | None = None

    subtotal: Decimal | None = None
    total_tax: Decimal | None = None
    total_due: Decimal | None = None

    taxes: list[TaxDetail] = Field(default_factory=list)
    line_items: list[LineItem] = Field(default_factory=list)
    ship_to_locations: list[ShipToLocation] = Field(default_factory=list)

    cost_centres: list[str] = Field(default_factory=list)
    important_notes: list[str] = Field(default_factory=list)
    duplicate_warning: str | None = None

    source_email: SourceEmail = Field(default_factory=SourceEmail)

    pdf_page_count: int | None = None
    extraction_warnings: list[str] = Field(default_factory=list)
class InvoiceImageSummary(BaseModel):
    """Fields displayed inside the invoice-summary image."""

    invoice_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    total_due: Decimal | None = None
    customer_account: str | None = None
    customer_po: str | None = None

    @field_validator("total_due", mode="before")
    @classmethod
    def normalize_total_due(cls, value: object) -> object:
        """Remove currency symbols and thousands separators before validation."""

        if value is None or isinstance(value, Decimal):
            return value

        if isinstance(value, str):
            return value.replace(",", "").replace("$", "").strip()

        return value