from __future__ import annotations

import os
import ssl
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import truststore
from agents import (
    Agent,
    RunContextWrapper,
    Runner,
    function_tool,
    set_default_openai_client,
    set_tracing_disabled,
)
from dotenv import load_dotenv
from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from extractor import (
    extract_local_invoice_data,
    extract_pdf_text,
    get_attachment_path,
    load_email,
    merge_image_summary,
)
from models import InvoicePayload
from notifier import (
    send_customer_service_notification as write_customer_service_notification,
)
from vision import extract_invoice_image_summary


@dataclass
class InvoiceAgentContext:
    """Local state shared by the two agent tools."""

    payload: InvoicePayload | None = None
    notification_outputs: dict[str, str] = field(default_factory=dict)


@function_tool
def extract_invoice_data(
    context: RunContextWrapper[InvoiceAgentContext],
    email_path: str,
) -> dict[str, Any]:
    """
    Load an inbound email and its PDF attachment, extract structured invoice
    information from PDF text and the page-one image, and return the payload.

    Args:
        email_path: Local path to the inbound email JSON file.
    """

    resolved_email_path = Path(email_path)

    email_data = load_email(resolved_email_path)
    attachment_path = get_attachment_path(
        email_data,
        resolved_email_path,
    )

    pdf_text, page_count = extract_pdf_text(attachment_path)

    payload = extract_local_invoice_data(
        email_data=email_data,
        pdf_text=pdf_text,
        page_count=page_count,
    )

    image_summary = extract_invoice_image_summary(attachment_path)

    payload = merge_image_summary(
        payload=payload,
        image_summary=image_summary,
    )

    context.context.payload = payload

    return payload.model_dump(mode="json")


@function_tool
def send_customer_service_notification(
    context: RunContextWrapper[InvoiceAgentContext],
) -> dict[str, str]:
    """
    Generate the Customer Service notification and structured JSON output.

    The invoice extraction tool must be called before this tool.
    """

    if context.context.payload is None:
        raise ValueError(
            "Invoice data has not been extracted. "
            "Call extract_invoice_data first."
        )

    outputs = write_customer_service_notification(
        context.context.payload
    )

    context.context.notification_outputs = outputs

    return outputs


def configure_agents_sdk() -> None:
    """Configure the Agents SDK using the Windows certificate store."""

    load_dotenv()

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key or api_key == "PASTE_THE_PROVIDED_KEY_HERE":
        raise ValueError(
            "OPENAI_API_KEY is missing or contains the placeholder value."
        )

    ssl_context = truststore.SSLContext(
        ssl.PROTOCOL_TLS_CLIENT
    )

    async_client = AsyncOpenAI(
        api_key=api_key,
        http_client=DefaultAsyncHttpxClient(
            verify=ssl_context,
            timeout=60.0,
        ),
    )

    set_default_openai_client(
        async_client,
        use_for_tracing=False,
    )

    # Tracing is unnecessary for this small assignment and would create
    # an additional network operation.
    set_tracing_disabled(True)


def run_invoice_agent(
    email_path: Path,
) -> tuple[str, InvoiceAgentContext]:
    """Run the complete two-tool invoice-intake workflow."""

    configure_agents_sdk()

    agent_model = os.getenv(
        "OPENAI_AGENT_MODEL",
        "gpt-5-nano",
    )

    if agent_model not in {"gpt-5-mini", "gpt-5-nano"}:
        raise ValueError(
            "OPENAI_AGENT_MODEL must be gpt-5-mini or gpt-5-nano."
        )

    context = InvoiceAgentContext()

    agent = Agent[InvoiceAgentContext](
        name="Invoice Intake Agent",
        model=agent_model,
        instructions=(
            "Process one inbound invoice email. "
            "First call extract_invoice_data exactly once using the "
            "email path provided by the user. "
            "After extraction succeeds, call "
            "send_customer_service_notification exactly once. "
            "Do not skip either tool. "
            "Do not invent invoice values. "
            "After both tools complete, briefly report the generated "
            "output file paths."
        ),
        tools=[
            extract_invoice_data,
            send_customer_service_notification,
        ],
    )

    result = Runner.run_sync(
        agent,
        input=(
            "Process the inbound invoice email at this exact local path: "
            f"{email_path}"
        ),
        context=context,
        max_turns=5,
    )

    if context.payload is None:
        raise RuntimeError(
            "The agent finished without extracting invoice data."
        )

    if not context.notification_outputs:
        raise RuntimeError(
            "The agent finished without creating the notification."
        )

    return str(result.final_output), context