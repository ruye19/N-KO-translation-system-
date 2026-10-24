# French–N'Ko Dictionary Resource

## 1. Source

File:

`dictionnaire Fr_nko.pdf`

The supplied PDF is approximately 498 pages.

Title:

**DICTIONNAIRE BILINGUE FRANÇAIS - N'KO**

Author:

**BABA MAMADI DIANE (Dianè Mohamed)**

The title page identifies the author as Professor of N'Ko at Cairo University.

Edition:

**1st edition, 2014**

## 2. Reported Size and Organization

The dictionary states that it contains more than 33,000 words.

It is organized primarily by the French source language, with N'Ko equivalents.

The dictionary describes broad coverage across domains, including scientific and technological terminology, while also indicating that it is not exhaustive.

These facts should be treated as properties of the supplied dictionary itself.

## 3. Intended Project Use

The dictionary is a project resource for improving the translator.

The intended role is:

French–N'Ko lexical/terminological knowledge
        ↓
Searchable structured data
        ↓
Relevant entries retrieved for translation
        ↓
AI/translation model receives supporting context

The dictionary should not be treated as the entire translation system.

## 4. Important Extraction Warning

Before building the complete data pipeline, inspect the PDF.

The PDF must be tested for:

- selectable text
- OCR requirements
- N'Ko Unicode preservation
- entry boundaries
- French/N'Ko alignment
- page headers/footers
- pronunciation/transliteration information if present
- grammatical information if present
- domain labels
- examples
- punctuation and separators

Do not assume that extracted text is correct simply because a PDF parser returns text.

Some extracted N'Ko content may require visual comparison with the original PDF.

## 5. Recommended Processing Stages

### Stage 1 — Preserve source

Keep:

`dictionnaire Fr_nko.pdf`

unchanged as the source artifact.

### Stage 2 — Sample extraction

Extract a small number of pages from:

- beginning
- middle
- end

Inspect the output.

### Stage 3 — Determine structure

Identify the repeating dictionary-entry pattern.

Example conceptual structure:

```json
{
  "french": "...",
  "nko": "...",
  "metadata": {}
}
```

This is only a conceptual example.

Do not invent dictionary fields that are not actually present.

### Stage 4 — Parse

Build a parser only after the entry format has been confirmed.

### Stage 5 — Validate

Check:

- number of entries
- empty entries
- corrupted N'Ko characters
- duplicate entries
- French/N'Ko alignment
- malformed records

### Stage 6 — Search/index

Choose the simplest search system that works.

Potential options:

- normalized exact lookup
- keyword/full-text search
- database indexing
- embeddings/vector search if necessary

Do not assume vector search is required.

## 6. N'Ko Unicode

N'Ko text must be treated as Unicode.

The implementation must preserve N'Ko characters through:

PDF extraction
→ parsing
→ storage
→ API
→ model request
→ model response
→ frontend

Do not use transformations that silently replace N'Ko characters with ASCII approximations.

The database, API, and frontend must support Unicode correctly.

## 7. Translation Directions and Dictionary Limitations

The supplied dictionary is primarily French → N'Ko.

This means:

### French → N'Ko

The dictionary can provide direct lexical support.

### English → N'Ko

The dictionary does not directly provide English → N'Ko entries.

English may require:

- model knowledge
- an English/French bridge
- additional resources
- future English–N'Ko parallel data

Any bridge approach must be tested rather than assumed to preserve meaning.

### N'Ko → French

The dictionary may provide useful reverse lookup if the N'Ko equivalent can be matched reliably, but the structure and quality of reverse retrieval must be tested.

### N'Ko → English

The dictionary does not directly provide English equivalents as its primary organization.

Additional resources/model capabilities may therefore be necessary.

## 8. Retrieval Context

Retrieved dictionary entries should be treated as supporting evidence/context.

The translation model should not be instructed to mechanically concatenate dictionary definitions into the output.

The final translation must be generated according to the source text, target language, context, and relevant retrieved information.

## 9. Evaluation

Create test cases using dictionary-supported words and phrases.

For each case record:

```text
Source
Source language
Target language
Expected/verified translation
System output
Problem
Correction
Notes
```

The dictionary should help create evaluation examples, but human verification remains important for sentence-level quality.

## 10. Copyright / Usage

The dictionary is a third-party published work.

Before redistributing the extracted dictionary data publicly, embedding the full dictionary into a public download, training a model on it, or otherwise using it beyond the agreed project purpose, verify that the project has the necessary rights or permission.

Do not assume that possession of the PDF automatically grants unrestricted redistribution or training rights.

## 11. Current Status

The dictionary is available as a project resource.

The following are NOT yet finalized:

- extraction method
- complete structured schema
- parser
- search/index technology
- retrieval strategy
- AI provider
- evaluation benchmark

These decisions should be made after sample inspection.
