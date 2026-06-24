from __future__ import annotations

import base64
import os
import ssl
from pathlib import Path

import fitz
import truststore
from dotenv import load_dotenv
from openai import DefaultHttpxClient, OpenAI

from models import InvoiceImageSummary


def render_first_page(pdf_path: Path) -> bytes:
    """Render the first PDF page as a high-resolution PNG image."""

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    try:
        document = fitz.open(pdf_path)
    except Exception as exc:
        raise ValueError(f"Unable to open PDF: {exc}") from exc

    try:
        if document.page_count == 0:
            raise ValueError("The PDF contains no pages.")

        page = document.load_page(0)

        # Render at approximately 144 DPI so small invoice text is readable.
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(2, 2),
            alpha=False,
        )

        return pixmap.tobytes("png")
    finally:
        document.close()


def save_first_page_preview(
    pdf_path: Path,
    output_path: Path,
) -> Path:
    """Render page one locally and save it for inspection."""

    png_bytes = render_first_page(pdf_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(png_bytes)

    return output_path


def extract_invoice_image_summary(
    pdf_path: Path,
) -> InvoiceImageSummary:
    """
    Extract the invoice-summary fields displayed in the page-one image.

    This function makes one targeted OpenAI API request.
    """

    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-5-mini")

    if not api_key or api_key == "PASTE_THE_PROVIDED_KEY_HERE":
        raise ValueError(
            "OPENAI_API_KEY is missing or still contains the placeholder value."
        )

    if model not in {"gpt-5-mini", "gpt-5-nano"}:
        raise ValueError(
            "OPENAI_MODEL must be either gpt-5-mini or gpt-5-nano."
        )

    png_bytes = render_first_page(pdf_path)
    encoded_image = base64.b64encode(png_bytes).decode("utf-8")
    image_data_url = f"data:image/png;base64,{encoded_image}"

    ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    client = OpenAI(
        api_key=api_key,
        http_client=DefaultHttpxClient(
            verify=ssl_context,
            timeout=60.0,
        ),
    )

    response = client.responses.parse(
        model=model,
        input=[
            {
                "role": "system",
                "content": (
                    "You extract invoice fields exactly as displayed. "
                    "Do not calculate, infer, correct, or invent values. "
                    "Use null when a field is unreadable or absent."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Read the invoice summary section on page one. "
                            "Extract only the invoice number, invoice date, "
                            "due date, total due, customer account, and "
                            "customer PO. Preserve identifiers exactly."
                        ),
                    },
                    {
                        "type": "input_image",
                        "image_url": image_data_url,
                        "detail": "high",
                    },
                ],
            },
        ],
        text_format=InvoiceImageSummary,
        max_output_tokens=1200,
    )

    if response.output_parsed is None:
        raise ValueError(
            "The model did not return a structured invoice summary. "
            f"Status: {response.status}; "
            f"Incomplete details: {response.incomplete_details}; "
            f"Output text: {response.output_text!r}"
        )

    return response.output_parsed