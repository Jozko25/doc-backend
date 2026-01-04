# DocParser

Universal document parser that converts PDF, images, Excel, and XML documents into a canonical JSON format with AI-powered extraction and validation.

## Features

- **Multi-format input**: PDF (native & scanned), images (JPG, PNG, TIFF), Excel, CSV, XML
- **AI-powered extraction**: Uses OpenAI GPT-4 to extract structured data from unstructured documents
- **OCR support**: Google Cloud Vision for scanned documents and images
- **Mathematical validation**: Automatic verification of totals, tax calculations, line items
- **VAT/Tax validation**: Country-specific tax rate verification and VAT ID format checking
- **Smart retry**: If validation fails, AI re-examines the document to correct OCR errors
- **Multiple export formats**: CSV, Excel, JSON (with UBL 2.1 and EN 16931 planned)
- **Uncertainty handling**: Clear flagging of uncertain values with AI suggestions

## Quick Start

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd doc

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"
```

### Configuration

Copy the example environment file and configure your API keys:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
GOOGLE_CLOUD_CREDENTIALS=/path/to/service-account.json
OPENAI_API_KEY=sk-...
```

### Running the API

```bash
# Start the development server
uvicorn docparser.main:app --reload

# Or use Python directly
python -m docparser.main
```

The API will be available at `http://localhost:8000`

- API docs: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## API Endpoints

### Parse Document

```bash
# Upload and parse a document
curl -X POST "http://localhost:8000/api/v1/documents/parse" \
  -F "file=@invoice.pdf" \
  -F "output_format=canonical"
```

Response:
```json
{
  "status": "valid",
  "document_id": "550e8400-e29b-41d4-a716-446655440000",
  "confidence": "high",
  "processing_time_ms": 2340,
  "review_required": false,
  "message": "Document processed and validated successfully."
}
```

### Get Processed Document

```bash
curl "http://localhost:8000/api/v1/documents/{document_id}"
```

### Export Document

```bash
# Export as CSV
curl "http://localhost:8000/api/v1/documents/{document_id}/export/csv" -o invoice.csv

# Export as Excel
curl "http://localhost:8000/api/v1/documents/{document_id}/export/xlsx" -o invoice.xlsx

# Export as JSON
curl "http://localhost:8000/api/v1/documents/{document_id}/export/json" -o invoice.json
```

## Canonical JSON Schema

All documents are normalized to an internal canonical format:

```json
{
  "schema_version": "1.0.0",
  "metadata": {
    "document_id": "uuid",
    "source_file": "invoice.pdf",
    "source_type": "pdf_native",
    "validation_status": "valid"
  },
  "document": {
    "type": "invoice",
    "number": "INV-2024-001",
    "issue_date": "2024-01-15",
    "due_date": "2024-02-15",
    "currency": "EUR"
  },
  "supplier": {
    "name": "Acme Corp",
    "tax_id": "CZ12345678",
    "address": {...}
  },
  "customer": {...},
  "line_items": [...],
  "totals": {
    "subtotal": 1000.00,
    "total_tax": 210.00,
    "total_amount": 1210.00
  },
  "payment": {...}
}
```

## Uncertainty Handling

When the system cannot fully validate a document, it returns with `status: "uncertain"`:

```json
{
  "status": "uncertain",
  "confidence": "low",
  "review_required": true,
  "suggestions": [
    {
      "field": "totals.total_amount",
      "extracted_value": "1O10.00",
      "ai_suggestion": "1010.00",
      "reason": "Possible OCR error: 'O' interpreted as '0'",
      "confidence": 0.75
    }
  ],
  "message": "Document processed but some values need verification."
}
```

## Project Structure

```
doc/
├── src/docparser/
│   ├── api/            # FastAPI routes and middleware
│   ├── core/           # Models and pipeline
│   ├── extractors/     # OCR, PDF, Excel, XML extractors
│   ├── normalizers/    # LLM extraction and prompts
│   ├── validators/     # Math and tax validation
│   ├── exporters/      # CSV, Excel exporters
│   └── utils/          # File handling utilities
├── tests/
└── scripts/
```

## Development

### Running Tests

```bash
pytest
pytest --cov=docparser  # With coverage
```

### Local Testing (without full API)

```bash
# Run mock test
python scripts/local_test.py --mock

# Process a specific file
python scripts/local_test.py --file path/to/invoice.pdf
```

## Roadmap

- [ ] UBL 2.1 XML export
- [ ] EN 16931 / CII XML export
- [ ] PEPPOL network integration
- [ ] Supabase database integration
- [ ] Human-in-the-loop UI
- [ ] Batch processing API
- [ ] Docker containerization
