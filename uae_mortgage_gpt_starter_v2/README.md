
# UAE Mortgage Comparison GPT Starter, v0.2.0

Created: 2025-10-19

## What is inside
- schemas/input_schema.json and schemas/output_schema.json
- backend/calculator.py, backend/app.py (FastAPI)
- prompts/*.txt for your custom GPT
- sample_data/sample_input.json
- tests/test_engine.py

## Buyout fee defaults included
When `assumptions.auto_estimate_buyout_fees = true` and fees are not provided, the API estimates:
- Processing fee: min(1 percent of principal, 10,000 AED)
- Valuation fee: 2,500 AED
- DLD fee: 0.25 percent of principal plus 290 AED
- Trustee fee: 4,200 AED
- Mortgage registration fee: 2,000 AED
- Old bank admin: release letter 1,000 AED, liability letter 100 AED
- Early settlement penalty of old bank: applied upfront on switch using `current_terms.early_settlement` (default 1 percent with 10,000 AED cap)

## How to run locally
1) cd backend
2) pip install fastapi uvicorn pydantic
3) uvicorn app:app --reload --port 8080
4) POST to http://localhost:8080/compare with ../sample_data/sample_input.json

## How to deploy
- Render, Railway, or Fly.io. Start command:
  uvicorn app:app --host 0.0.0.0 --port 10000

## OpenAPI for Actions
openapi: 3.0.1
info:
  title: UAE Mortgage Comparison API
  version: "0.2.0"
servers:
  - url: https://YOUR-DOMAIN/
paths:
  /compare:
    post:
      operationId: compare
      summary: Compare stay versus switch
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
      responses:
        "200":
          description: OK

## Step by step, build this as a Custom GPT in ChatGPT

1) Create the Custom GPT
   - Open Explore GPTs, Create a GPT.
   - Name it "UAE Mortgage Decision Assistant".
   - In Instructions, paste `prompts/system_prompt.txt`.
   - Add the Extraction and Explanation prompts in the relevant sections.

2) Add Knowledge
   - Upload `schemas/input_schema.json` and `schemas/output_schema.json` so the GPT adheres to the contract.
   - Optionally upload JSON for default EIBOR curves and Emirate specific fee notes.

3) Enable Actions
   - Deploy the FastAPI app and obtain a HTTPS base URL.
   - In the GPT builder, Actions, Add API Schema, paste the OpenAPI block above and update the server URL.
   - Allow the GPT to call this API.

4) Conversation wiring
   - Intake: Ask for principal, tenure, and PDF uploads of current offer and new quote.
   - Extraction: Parse PDFs to JSON, show a confirmation view.
   - Scenarios: Offer Base, Optimistic, Conservative arrays. Default 36 months.
   - Build the payload with `assumptions.auto_estimate_buyout_fees = true` by default.
   - Call `/compare`. Do not do math in the model.
   - Explain results clearly, show total cash, break even, and fee waterfall.

5) Guardrails
   - Never invent numbers. If auto estimates are used, state it explicitly and show line items.
   - If confidence is low on extraction, request user confirmation before calling the API.

6) QA checklist
   - Early settlement penalty appears as an upfront fee when switching.
   - DLD, trustee, registration, processing, valuation appear when not provided.
   - Insurance and recurring fees are visible in monthly cash flows.
   - Break even month equals the first month cumulative switch cash out is less than or equal to stay.

7) Launch and iterate
   - Pilot with 5 to 10 homeowners.
   - Tweak fee defaults per emirate and per bank.
   - Add Arabic localization as a next step.
