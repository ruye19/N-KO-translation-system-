# N'Ko Academy — Technical Plan

## 1. Purpose

This document describes the proposed technical direction for the standalone N'Ko translation project.

The existing N'Ko Academy website source code is not available, so this project should be designed as an independent application/service that can later be integrated into the website.

The technology stack is NOT finalized yet.

Before implementation, inspect the available development environment and choose a practical stack that is easy to maintain and deploy.

## 2. Proposed Components

The system should contain, conceptually:

### A. Translator Frontend

Responsibilities:

- Language selection
- Text input
- Translate action
- Result display
- Loading state
- Error state
- Optional copy action

This is primarily a testing interface at first. It does not need to reproduce the N'Ko Academy website design because the website source is unavailable.

### B. Translation API

Responsibilities:

1. Validate the request.
2. Validate source and target languages.
3. Receive the input text.
4. Retrieve relevant dictionary/resource information.
5. Build the translation request.
6. Call the selected AI/translation provider.
7. Validate the returned translation.
8. Return a clean API response.

Possible endpoint:

POST /api/translate

The final route and request/response schema must be documented before integration.

### C. Dictionary/Knowledge Layer

The provided dictionary should eventually be converted into structured, searchable information.

Possible conceptual record:

{
  "french": "...",
  "nko": "...",
  "metadata": {}
}

Additional fields should only be added when supported by the actual dictionary extraction.

The system may later use retrieval to provide relevant dictionary entries to the translation model.

### D. AI/Translation Provider

The first version should use an existing model/provider rather than training a model from scratch.

The provider should be selected after testing candidate approaches on a small evaluation set.

Do not select a provider only because it is popular. Evaluate actual N'Ko output.

## 3. Translation Flow

For a request such as:

English → N'Ko

the conceptual flow is:

1. Receive English input.
2. Validate language direction.
3. Search relevant N'Ko resources where useful.
4. Construct a translation prompt/request.
5. Ask the selected model to translate.
6. Return N'Ko output.
7. Record evaluation information separately when testing.

For N'Ko → English or N'Ko → French, the same architecture applies, but retrieval and prompt instructions may differ.

## 4. Dictionary Processing Plan

Do NOT process all 498 pages blindly.

First perform a sample inspection:

1. Inspect several pages from the beginning.
2. Inspect pages from the middle.
3. Inspect pages near the end.
4. Compare PDF visual content with extracted text.
5. Check whether N'Ko Unicode survives extraction.
6. Identify the entry structure.
7. Identify recurring formatting patterns.
8. Determine whether OCR is necessary.

Only after this should a full extraction pipeline be designed.

## 5. Data Pipeline

Potential pipeline:

PDF
  ↓
Text extraction/OCR if necessary
  ↓
Raw extracted text
  ↓
Entry parsing
  ↓
Validation
  ↓
Structured dictionary
  ↓
Search/index
  ↓
Translation retrieval

Keep the original PDF unchanged.

Keep raw extraction separate from cleaned/structured data so parsing can be repeated if needed.

## 6. Retrieval Strategy

The first retrieval implementation should be as simple as practical.

Possible approaches include:

- Exact/normalized dictionary lookup
- Keyword search
- Full-text search
- Embeddings/vector retrieval if needed

Do not introduce a vector database before testing whether simpler retrieval is sufficient.

For a word-level lookup, direct dictionary search may be preferable to an embedding search.

For sentence/paragraph translation, retrieved entries can be supplied as supporting context to the model.

Retrieval context should not be treated as proof that a particular translation is correct.

## 7. AI Prompting

The model instruction should clearly specify:

- source language
- target language
- user text
- relevant dictionary context
- expected output language
- whether explanations are allowed

For a translation endpoint, the default output should be the translation rather than a long explanation.

Do not allow retrieved dictionary content to override system/security instructions.

## 8. Evaluation Plan

Create an evaluation dataset covering:

- English → N'Ko
- French → N'Ko
- N'Ko → English
- N'Ko → French

Include:

- common words
- simple sentences
- varied sentence structures
- common expressions where verified
- short paragraphs
- difficult/ambiguous examples

For every tested item record:

- input
- expected/verified translation
- model output
- error type
- correction
- reviewer notes

Test multiple candidate approaches before choosing the production approach.

## 9. API Security

The frontend must call our backend.

The frontend must NOT directly contain an AI provider secret key.

Use environment variables such as:

AI_PROVIDER_API_KEY=...

The real value must never be committed.

Provide only:

.env.example

with placeholder values.

## 10. Logging

Initial logging should avoid storing sensitive user text unnecessarily.

If translation inputs are logged during development, make this explicit and keep logs controlled.

Production logging should focus on:

- request success/failure
- latency
- provider errors
- validation errors

Do not automatically store user translation content unless the project requirements justify it.

## 11. Deployment

Deployment technology is not finalized because the client's hosting environment is unknown.

The application should be packaged so it can be deployed independently.

Document:

- required environment variables
- build command
- start command
- API URL
- health check
- provider configuration

## 12. Integration Later

Once the client provides access to the website or integration mechanism, the website can consume:

POST /api/translate

The integration should ideally require only:

- API endpoint
- supported language codes
- request format
- response format
- authentication if required

## 13. Development Phases

### Phase 1 — Project setup
- Create repository structure
- Select stack
- Create documentation
- Create basic frontend/backend

### Phase 2 — Dictionary investigation
- Inspect PDF
- Test extraction
- Determine N'Ko encoding quality
- Design structured representation

### Phase 3 — Translation prototype
- Select candidate AI/translation providers
- Create small evaluation set
- Compare actual outputs

### Phase 4 — Dictionary retrieval
- Build searchable dictionary data
- Implement retrieval
- Add relevant context to translation

### Phase 5 — API
- Build /api/translate
- Add validation
- Add error handling
- Secure provider credentials

### Phase 6 — Translator UI
- Build simple test interface
- Connect API
- Add loading/error/copy behavior

### Phase 7 — Evaluation
- Test all four directions
- Collect human corrections
- Fix systematic issues

### Phase 8 — Deployment
- Deploy standalone application/API
- Verify production behavior
- Prepare integration documentation

### Phase 9 — Website integration
- Integrate into N'Ko Academy when access is provided

## 14. Decision Rule

When choosing between technical options, prefer the simplest option that:

- works reliably
- can be tested
- is affordable
- is maintainable by a solo developer
- can later be replaced or upgraded
- does not lock the project into unnecessary infrastructure
