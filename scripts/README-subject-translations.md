# Subject translations

The source quiz JSON files under `Subjects/` are English. The generator creates
three language versions for every source file:

- `*_en.json` — exact English copy
- `*_gu.json` — Gujarati
- `*_hi.json` — Hindi

The JSON structure and keys are preserved. Only string values are translated;
booleans, numbers, answer flags and the object/array structure are unchanged.

## Run locally

```bash
pip install openai
export OPENAI_API_KEY="your-api-key"
python scripts/generate_subject_translations.py
```

The script caches translations in `.subject_translation_cache.json`, so a
rerun does not translate strings that were already completed.

## GitHub Actions

The repository includes a manual workflow at
`.github/workflows/generate-subject-translations.yml`.

Add an `OPENAI_API_KEY` repository secret, then run **Generate Subject
Translations** from GitHub Actions.
