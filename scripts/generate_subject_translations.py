#!/usr/bin/env python3
"""
Generate English, Gujarati and Hindi copies of every JSON quiz file under Subjects/.

Usage:
  pip install openai
  export OPENAI_API_KEY="..."
  python scripts/generate_subject_translations.py

Optional:
  OPENAI_MODEL=gpt-6-luna
  TRANSLATION_BATCH_SIZE=50

The original JSON files are treated as English source files. Keys, booleans,
numbers, array/object structure and answer flags are preserved exactly.
Only string values are translated.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
SUBJECTS = ROOT / "Subjects"
CACHE_PATH = ROOT / ".subject_translation_cache.json"

MODEL = os.getenv("OPENAI_MODEL", "gpt-6-luna")
BATCH_SIZE = int(os.getenv("TRANSLATION_BATCH_SIZE", "50"))
MAX_RETRIES = 5

LANGUAGES = {
    "gu": "Gujarati",
    "hi": "Hindi",
}

# These are intentionally not translated. They are quiz answer values that
# should remain numeric/technical tokens.
NUMBER_RE = re.compile(r"^[\\s\\d.,%+\\-×÷=<>:()/\\[\\]{}]+$")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\\n") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\\n")


def collect_strings(value: Any, output: set[str]) -> None:
    if isinstance(value, str):
        if value.strip() and not NUMBER_RE.fullmatch(value.strip()):
            output.add(value)
    elif isinstance(value, list):
        for item in value:
            collect_strings(item, output)
    elif isinstance(value, dict):
        for item in value.values():
            collect_strings(item, output)


def replace_strings(value: Any, translations: dict[str, str]) -> Any:
    if isinstance(value, str):
        return translations.get(value, value)
    if isinstance(value, list):
        return [replace_strings(item, translations) for item in value]
    if isinstance(value, dict):
        return {key: replace_strings(item, translations) for key, item in value.items()}
    return value


def load_cache() -> dict[str, dict[str, str]]:
    if not CACHE_PATH.exists():
        return {"gu": {}, "hi": {}}
    try:
        data = load_json(CACHE_PATH)
        return {
            "gu": dict(data.get("gu", {})),
            "hi": dict(data.get("hi", {})),
        }
    except Exception:
        return {"gu": {}, "hi": {}}


def save_cache(cache: dict[str, dict[str, str]]) -> None:
    save_json(CACHE_PATH, cache)


def translate_batch(
    client: OpenAI,
    strings: list[str],
    language: str,
) -> dict[str, str]:
    language_name = LANGUAGES[language]

    numbered = "\\n".join(f"{i + 1}. {json.dumps(s, ensure_ascii=False)}" for i, s in enumerate(strings))

    prompt = f"""
Translate the following English quiz strings into {language_name}.

Rules:
1. Return ONLY a valid JSON array of strings.
2. Return exactly {len(strings)} items, in exactly the same order.
3. Translate natural-language questions and answer choices accurately.
4. Preserve numbers, units, mathematical expressions, abbreviations, URLs,
   punctuation that is meaningful, and proper names when translation is not
   appropriate.
5. Do not add explanations, markdown, numbering, or extra text.
6. Do not change the meaning of a quiz question or its answer.
7. Use natural, standard {language_name} suitable for a general-knowledge quiz.
8. Do not translate a person's name, country/city name, team name, product name,
   scientific symbol, programming keyword, or other proper noun unless there is
   a standard localized form.
9. For English terms that are normally used unchanged in the target language,
   keep the term rather than inventing an unnatural translation.

Strings:
{numbered}
""".strip()

    for attempt in range(MAX_RETRIES):
        try:
            response = client.responses.create(
                model=MODEL,
                input=prompt,
            )
            raw = response.output_text.strip()
            translated = json.loads(raw)

            if (
                not isinstance(translated, list)
                or len(translated) != len(strings)
                or not all(isinstance(x, str) for x in translated)
            ):
                raise ValueError("Model returned an invalid translation array.")

            return dict(zip(strings, translated))
        except Exception as exc:
            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(
                    f"Translation failed for {language} after {MAX_RETRIES} attempts: {exc}"
                ) from exc
            time.sleep(2 ** attempt)

    raise AssertionError("unreachable")


def translate_strings(
    client: OpenAI,
    strings: set[str],
    language: str,
    cache: dict[str, dict[str, str]],
) -> None:
    existing = cache[language]
    pending = [s for s in strings if s not in existing]

    print(f"{language}: {len(existing)} cached, {len(pending)} pending")

    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start : start + BATCH_SIZE]
        result = translate_batch(client, batch, language)
        existing.update(result)
        save_cache(cache)
        print(
            f"{language}: translated {min(start + len(batch), len(pending))}/"
            f"{len(pending)}"
        )


def english_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}_en.json")


def localized_path(source: Path, language: str) -> Path:
    return source.with_name(f"{source.stem}_{language}.json")


def main() -> int:
    if not SUBJECTS.exists():
        print("Subjects directory not found.", file=sys.stderr)
        return 1

    if not os.getenv("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is required.", file=sys.stderr)
        return 1

    client = OpenAI()
    cache = load_cache()

    sources = sorted(
        p
        for p in SUBJECTS.rglob("*.json")
        if not p.stem.endswith(("_en", "_gu", "_hi"))
    )

    if not sources:
        print("No source JSON files found.")
        return 0

    all_strings: set[str] = set()
    parsed: dict[Path, Any] = {}

    for source in sources:
        data = load_json(source)
        parsed[source] = data
        collect_strings(data, all_strings)

    print(f"Source files: {len(sources)}")
    print(f"Unique translatable strings: {len(all_strings)}")

    for language in LANGUAGES:
        translate_strings(client, all_strings, language, cache)

    # English is an exact structural/value copy of the source.
    for source, data in parsed.items():
        save_json(english_path(source), data)

        for language in LANGUAGES:
            localized = replace_strings(data, cache[language])
            save_json(localized_path(source, language), localized)

    # Validate every generated JSON file.
    generated = []
    for source in sources:
        generated.append(english_path(source))
        generated.extend(localized_path(source, lang) for lang in LANGUAGES)

    for path in generated:
        load_json(path)

    print(f"Generated files: {len(generated)}")
    print("JSON validation: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
