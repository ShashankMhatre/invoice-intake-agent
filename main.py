from __future__ import annotations

import argparse
from pathlib import Path

from agent_workflow import run_invoice_agent
from extractor import (
    extract_local_invoice_data,
    extract_pdf_text,
    get_attachment_path,
    load_email,
)


def run_local_extraction(email_path: Path) -> Path:
    """Run deterministic extraction without calling the OpenAI API."""

    email_data = load_email(email_path)
    attachment_path = get_attachment_path(email_data, email_path)
    pdf_text, page_count = extract_pdf_text(attachment_path)

    payload = extract_local_invoice_data(
        email_data=email_data,
        pdf_text=pdf_text,
        page_count=page_count,
    )

    output_directory = Path("outputs")
    output_directory.mkdir(parents=True, exist_ok=True)

    output_path = output_directory / "local_extraction.json"
    output_path.write_text(
        payload.model_dump_json(indent=2),
        encoding="utf-8",
    )

    print("\nLocal invoice extraction completed.")
    print(f"Vendor: {payload.vendor.name}")
    print(f"Invoice number: {payload.invoice_number}")
    print(f"Invoice date: {payload.invoice_date}")
    print(f"Due date: {payload.due_date}")
    print(f"Customer PO: {payload.customer_po}")
    print(f"Subtotal: {payload.subtotal}")
    print(f"Total tax: {payload.total_tax}")
    print(f"Total due: {payload.total_due}")
    print(f"Line items: {len(payload.line_items)}")
    print(f"Tax records: {len(payload.taxes)}")
    print(f"Ship-to locations: {len(payload.ship_to_locations)}")
    print(f"Output: {output_path}")

    if payload.extraction_warnings:
        print("\nWarnings:")

        for warning in payload.extraction_warnings:
            print(f"- {warning}")

    return output_path


def run_agent_workflow(email_path: Path) -> None:
    """Run the complete OpenAI Agents SDK workflow."""

    print("Running OpenAI Agents SDK invoice workflow...")

    final_output, context = run_invoice_agent(email_path)

    print("\nAgent workflow completed.")
    print(f"Agent response: {final_output}")

    print("\nGenerated files:")

    for output_name, output_path in context.notification_outputs.items():
        print(f"- {output_name}: {output_path}")

    if context.payload is not None:
        print("\nExtracted invoice:")
        print(f"- Vendor: {context.payload.vendor.name}")
        print(f"- Invoice number: {context.payload.invoice_number}")
        print(f"- Customer PO: {context.payload.customer_po}")
        print(f"- Total due: {context.payload.total_due}")
        print(f"- Line items: {len(context.payload.line_items)}")
        print(f"- Ship-to locations: {len(context.payload.ship_to_locations)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Process an inbound email and invoice PDF using "
            "the OpenAI Agents SDK."
        )
    )

    parser.add_argument(
        "--email",
        required=True,
        type=Path,
        help="Path to the inbound email JSON file.",
    )

    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Run local PDF/email parsing without OpenAI API requests.",
    )

    args = parser.parse_args()

    try:
        if args.local_only:
            run_local_extraction(args.email)
        else:
            run_agent_workflow(args.email)

    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"\nError: {exc}")
        raise SystemExit(1) from exc

    except Exception as exc:
        print(f"\nUnexpected error: {type(exc).__name__}: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()