# VeriGreen ESG Validation Portal — Integration Guide

## Architecture

```
Browser (Portal)
  ↓ 1. User uploads PDF/Word/TXT ESG document
  ↓ 2. pdfjs-dist / mammoth extracts raw text client-side
  ↓ 3. Sentence splitter + ESG keyword filter identifies claims
  ↓ 4. Deterministic djb2 hash assigns id_int per claim
  ↓ 5. JSON payload POSTed to Make.com webhook
Make.com Scenario 6411040 (v9 pipeline)
  ↓ Module 1: Webhook receiver
  ↓ Module 2: BasicFeeder iterator (fan-out per claim)
  ↓ Module 3: Gemini 2.5 Flash (scores 5 boolean indicators)
  ↓ Module 4: util:SetVariables (computes substantiation_score 0-5)
  ↓ Module 5: Mistral Embed-2312 (1024-dim semantic embedding)
  ↓ Module 6: Qdrant uploadPoint (persists to esg_claims collection)
```

## Webhook Payload Format

```json
{
  "job_id": "portal-e2e-test-001",
  "company_name": "GreenTech Solutions PLC",
  "reporting_year": "2024",
  "report_type": "sustainability",
  "claim_count": 36,
  "extraction_method": "sentence-split + ESG keyword filter",
  "claims": [
    {
      "raw_text": "In 2024, we reduced our total greenhouse gas emissions by 42%...",
      "category": "Climate & Emissions",
      "company_id": "greentech_solutions_plc",
      "year": "2024",
      "id_int": 1234567890,
      "job_id": "portal-e2e-test-001"
    }
  ]
}
```

## End-to-End Test Results

| Test | Document | Claims | Webhook | Pipeline Ops | Status |
|------|----------|--------|---------|--------------|--------|
| portal-e2e-test-001 | GreenTech ESG Report 2024 | 36 | HTTP 200 | 146 | ✅ SUCCESS |

**Expected operations formula:** `2 + (claim_count × 4)`
- 2 = Webhook + Iterator overhead
- 4 = Gemini + SetVariables + Mistral + Qdrant per claim

## Supported File Types

| Format | Library | Notes |
|--------|---------|-------|
| PDF | pdfjs-dist v6 | Full text extraction, all pages |
| DOCX/DOC | mammoth v1.12 | Raw text extraction |
| TXT/CSV/MD | Browser FileReader | Direct text read |
| PNG/JPG | — | Placeholder claim (manual review) |

## ESG Category Classification

8 categories with keyword-based routing:
- Climate & Emissions, Energy, Water, Biodiversity
- Social & Labour, Circular Economy, Governance, Supply Chain

## Known Limitations

1. **50-claim cap per submission** — Make.com free tier limits operations per run
2. **Image files** — no OCR; returns placeholder claim for manual review
3. **Scanned PDFs** — pdfjs-dist cannot extract text from image-only PDFs
4. **Language** — English only (keyword filter is English)
