from __future__ import annotations

import argparse
import json
from pathlib import Path

import fitz


def load_email(email_path: Path) -> dict:
    if not email_path.exists():
        raise FileNotFoundError(f"Email file not found: {email_path}")

    try:
        with email_path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid email JSON: {exc}") from exc


def get_attachment_path(email_data: dict, email_path: Path) -> Path:
    attachments = email_data.get("Message", {}).get("Attachments", [])

    if not attachments:
        raise ValueError("No attachments were listed in the email.")

    attachment_name = attachments[0].get("Name")

    if not attachment_name:
        raise ValueError("The email attachment does not have a filename.")

    attachment_path = email_path.parent / attachment_name

    if not attachment_path.exists():
        raise FileNotFoundError(
            f"Attachment referenced by the email was not found: {attachment_path}"
        )

    return attachment_path


def extract_pdf_text(pdf_path: Path) -> tuple[str, int]:
    try:
        document = fitz.open(pdf_path)
    except Exception as exc:
        raise ValueError(f"Unable to open PDF: {exc}") from exc

    try:
        page_text = [page.get_text("text") for page in document]
        return "\n".join(page_text), document.page_count
    finally:
        document.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read an inbound email and its invoice PDF attachment."
    )
    parser.add_argument(
        "--email",
        required=True,
        type=Path,
        help="Path to the inbound email JSON file.",
    )
    args = parser.parse_args()

    try:
        email_data = load_email(args.email)
        attachment_path = get_attachment_path(email_data, args.email)
        pdf_text, page_count = extract_pdf_text(attachment_path)

        message = email_data.get("Message", {})

        print("Input validation successful")
        print(f"Subject: {message.get('Subject', 'Unknown')}")
        print(f"Attachment: {attachment_path}")
        print(f"PDF pages: {page_count}")
        print(f"Extracted PDF characters: {len(pdf_text)}")

    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()