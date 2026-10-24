# N'Ko Academy — Translation Scope

## Version 1 Scope

### Required translation directions

1. English → N'Ko
2. French → N'Ko
3. N'Ko → English
4. N'Ko → French

## Supported Input

Version 1 should target:

- Words
- Sentences
- Short/medium paragraphs

The exact maximum input length should be determined during implementation based on the selected provider and cost/performance requirements.

## Required User Experience

The first translator interface should provide:

- Source language selection
- Target language selection
- Text input
- Translate button/action
- Translation result
- Loading state
- Error state

Optional if straightforward:

- Copy translation
- Swap languages
- Clear input

## Translation Approach

Version 1 should use an existing AI/translation model supported by a backend service.

The model may receive relevant information retrieved from the provided French–N'Ko dictionary.

The dictionary is a supporting resource, not a complete translation engine.

## Dictionary Role

The dictionary can help with:

- French word lookup
- French → N'Ko lexical information
- terminology
- supporting context for translation

The dictionary alone does not establish that a complete sentence or paragraph translation is grammatically correct.

For N'Ko → French and N'Ko → English, additional resources or model knowledge may be needed because the supplied dictionary is organized primarily from French to N'Ko.

## Quality Expectations

The first version should be described as:

"AI-assisted translation"

not:

"perfect translation"

or:

"professional certified translation"

Translation quality must be evaluated with real examples.

Where possible, knowledgeable N'Ko speakers should review outputs.

## Out of Scope

The following are not part of Version 1:

### Whole-book translation

The system should not promise or implement automatic full-book translation as an initial feature.

Large documents may introduce:

- context problems
- terminology consistency problems
- quality-control problems
- cost concerns
- output-length limitations

### Model training from scratch

Do not train a new N'Ko foundation model for Version 1.

### Specialized N'Ko model

A specialized model can be investigated later after enough verified training/evaluation data exists.

### Guaranteed accuracy

Do not advertise or document a guaranteed accuracy percentage unless it has been measured using a defined evaluation methodology.

### Automatic publication

Translations should not automatically become authoritative N'Ko content without appropriate review.

## Future Scope

Potential later features:

- document translation
- translation memory
- terminology management
- user corrections
- reviewer workflow
- parallel corpus collection
- fine-tuning
- specialized N'Ko translation model
- additional languages

These require separate planning and should not silently be added to Version 1.

## Success Criteria

Version 1 should be considered technically successful when:

1. All four required directions can be requested.
2. The API reliably returns translations or understandable errors.
3. The dictionary can be searched/retrieved where appropriate.
4. The frontend can use the translation API.
5. Translation outputs can be evaluated systematically.
6. The system can be deployed independently.
7. The integration contract for the future N'Ko Academy website is documented.
