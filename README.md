# Invoice Intake Agent

A Python project that uses the OpenAI Agents SDK to process an inbound email and its attached invoice PDF.

The workflow extracts structured invoice data from searchable PDF text and image-only fields, then generates a human-readable Customer Service notification and a JSON payload for downstream processing.

## Features

* Reads an inbound Microsoft Graph-style email JSON file
* Locates the referenced PDF attachment
* Extracts searchable PDF text locally with PyMuPDF
* Extracts image-only invoice fields from page one using `gpt-5-mini`
* Uses an OpenAI Agents SDK agent with two callable tools
* Extracts:

  * Vendor name
  * Invoice number
  * Invoice date and due date
  * Payment terms and currency
  * Customer PO and customer account
  * Subtotal, tax breakdown, and total due
  * Line items
  * Ship-to locations and site allocations
  * Delivery and receiving notes
  * Duplicate invoice warning
* Generates:

  * A human-readable Customer Service notification
  * A structured JSON payload

## Architecture

The agent uses two tools:

1. `extract_invoice_data`

   * Loads the email JSON
   * Resolves the PDF attachment
   * Extracts PDF text locally
   * Extracts the page-one image fields with `gpt-5-mini`
   * Returns a validated structured invoice payload

2. `send_customer_service_notification`

   * Creates a human-readable notification
   * Writes the structured payload to JSON
   * Simulates a downstream Customer Service notification action

The lightweight agent orchestration uses `gpt-5-nano`.

## Project Structure

```text
invoice-intake-agent/
├── data/
│   ├── Email.json
│   └── Invoice.pdf
├── agent_workflow.py
├── extractor.py
├── main.py
├── models.py
├── notifier.py
├── vision.py
├── pyproject.toml
├── uv.lock
├── .gitignore
└── README.md
```

The `outputs/` directory is created automatically when the application runs.

## Requirements

* Python 3.12+
* `uv`
* An OpenAI API key with access to:

  * `gpt-5-mini`
  * `gpt-5-nano`

## Setup

Clone the repository:

```bash
git clone https://github.com/ShashankMhatre/invoice-intake-agent.git
cd invoice-intake-agent
```

Install the dependencies:

```bash
uv sync
```

Create a local `.env` file:

```env
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-5-mini
OPENAI_AGENT_MODEL=gpt-5-nano
```

The `.env` file is excluded through `.gitignore` and must not be committed.

## Run the Full Agent Workflow

```bash
uv run python main.py --email ./data/Email.json
```

The full workflow:

1. Reads the email and PDF
2. Extracts searchable PDF data locally
3. Uses `gpt-5-mini` for image-only invoice fields
4. Uses the Agents SDK to call both workflow tools
5. Generates the Customer Service outputs

## Run Local-Only Extraction

To test deterministic email and PDF-text parsing without making an OpenAI API request:

```bash
uv run python main.py --email ./data/Email.json --local-only
```

Image-only fields such as the invoice number, invoice date, and due date may remain empty in local-only mode.

## Generated Outputs

The full workflow creates:

```text
outputs/outbound_email.txt
outputs/outbound_payload.json
```

The local-only workflow creates:

```text
outputs/local_extraction.json
```

The `outputs/` directory is ignored by Git because these files are generated at runtime.

## Cost-Aware Design

The application minimizes model usage by:

* Parsing the email locally
* Extracting searchable PDF text locally
* Parsing line items, taxes, totals, and site allocations deterministically
* Sending only the first PDF page image to `gpt-5-mini`
* Using `gpt-5-nano` for lightweight tool orchestration
* Avoiding unnecessary retries and repeated extraction calls
* Disabling Agents SDK tracing for this limited-credit assignment

## Validation

The application performs lightweight validation, including:

* Checking that the email file exists
* Validating the email JSON structure
* Confirming that a PDF attachment is listed
* Confirming that the PDF file exists
* Handling unreadable or empty PDF files
* Validating model output with Pydantic
* Comparing the sum of line totals with the invoice subtotal
* Comparing the sum of tax records with the total tax
* Reporting unresolved extraction warnings

## Security

* The OpenAI API key is stored only in `.env`
* `.env` is excluded from Git
* SSL certificate verification remains enabled
* The application uses the operating system certificate store where required
* No API keys are included in source code or documentation

## Main Technologies

* Python
* OpenAI Agents SDK
* OpenAI Responses API
* `gpt-5-mini`
* `gpt-5-nano`
* PyMuPDF
* Pydantic
* `uv`
* `python-dotenv`
* `truststore`

## Notes

The sample email and invoice are treated strictly as input files. Their full contents are not copied into source-code comments or this README.
