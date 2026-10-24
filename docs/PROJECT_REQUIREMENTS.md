# N'Ko Academy — AI-Assisted Translator
## Project Requirements

## 1. Project Overview

This project is a standalone translation service/application that will eventually be integrated into the existing N'Ko Academy website.

The existing website source code is not currently available to the developer. Therefore, this project must be developed independently and expose a clean interface/API that the N'Ko Academy website can integrate with later.

The first version focuses on an AI-assisted translator involving:

- English → N'Ko
- French → N'Ko
- N'Ko → English
- N'Ko → French

The translator should support words, sentences, and short/medium paragraphs.

## 2. Main Goal

Build a practical first version of an N'Ko translation system using:

1. An existing AI/translation model
2. The provided French–N'Ko dictionary
3. Search/retrieval of relevant dictionary information
4. A backend translation API
5. A simple translator interface for testing
6. Human evaluation and correction

The first version should be designed so that translation quality can be improved later as verified N'Ko data becomes available.

## 3. Initial User Flow

A user should eventually be able to:

1. Select a source language.
2. Select a target language.
3. Enter text.
4. Request a translation.
5. See the translated text.
6. Copy the result if this is included in the final UI.
7. Receive understandable loading and error states.

Initial language choices:

- English
- French
- N'Ko

Only these four translation directions are required for the first version.

## 4. High-Level Architecture

The intended architecture is:

User
  ↓
Translator UI
  ↓
Translation Backend/API
  ↓
Relevant dictionary/resource retrieval
  ↓
AI/translation model
  ↓
Translation result
  ↓
Translator UI

The architecture is a starting point, not a rigid requirement. Technical decisions should be documented before major implementation changes.

## 5. Standalone Integration Requirement

Because the existing N'Ko Academy website code is unavailable, the translator must not depend on the client's website source code.

The application should eventually expose a backend endpoint such as:

POST /api/translate

Example request:

{
  "text": "How are you?",
  "source_language": "en",
  "target_language": "nko"
}

Example response shape:

{
  "translation": "...",
  "source_language": "en",
  "target_language": "nko"
}

The exact API contract must be finalized during implementation.

## 6. Dictionary Requirement

The project includes a 498-page French–N'Ko dictionary:

"DICTIONNAIRE BILINGUE FRANÇAIS - N'KO"

Author:
BABA MAMADI DIANE (Dianè Mohamed)

First edition:
2014

The dictionary reports more than 33,000 words and is organized primarily from French as the source language with N'Ko equivalents.

The PDF must first be inspected for extraction quality and structure.

Do not assume that all N'Ko text can be extracted cleanly from the PDF.

The dictionary must not be sent wholesale to an AI API as a substitute for a searchable data layer.

## 7. Translation Quality Requirement

N'Ko is a lower-resource language in this project context. Translation output must therefore be tested rather than assumed to be correct.

A small evaluation dataset should be created during development.

Suggested structure:

- Input
- Source language
- Target language
- System translation
- Human/verified translation
- Error/problem
- Correction
- Notes

Human review by a knowledgeable N'Ko speaker should be sought where possible.

## 8. Error Handling

The system should eventually handle:

- Empty input
- Unsupported language direction
- Invalid API requests
- AI provider failure
- Timeout
- Rate limiting
- Missing dictionary context
- Unexpected model output

The backend must return safe, understandable errors.

## 9. Security

AI provider credentials must remain on the backend.

Never:

- hardcode API keys
- expose provider keys in frontend JavaScript
- commit secrets
- place secret credentials in documentation

Use environment variables and provide an `.env.example` without secret values.

## 10. Performance and Cost

The first version should be simple and cost-conscious.

Avoid unnecessary infrastructure.

Do not introduce a large database, vector database, model-serving cluster, or other infrastructure unless the project actually requires it.

AI usage costs depend on the selected provider, model, input/output length, and usage. The implementation should make the provider configurable where practical.

## 11. Out of Scope for Version 1

The first version does NOT include:

- Training a translation model from scratch
- Building a foundation language model
- Whole-book automatic translation
- Guaranteed professional translation
- Guaranteed native-level translation
- Automatic publication of translations without review
- A specialized N'Ko model unless separately approved
- Large-scale fine-tuning unless separately approved

## 12. Future Possibilities

If enough verified parallel data is collected later, the project may investigate:

- Fine-tuning
- Specialized N'Ko translation models
- Additional parallel corpora
- Better retrieval
- Translation memory
- Human feedback workflows
- Automated evaluation

These are future phases and should not silently become part of Version 1.

## 13. Development Principle

Build the smallest reliable system that can be tested.

Prefer:

Understand → Prototype → Evaluate → Improve → Integrate

over:

Build a large system → Assume it works → Integrate everything at once.
