#!/usr/bin/env python3
# Translation generation supports the no-API-key workflow.
"""
Generate English, Gujarati and Hindi copies of every JSON quiz file under Subjects/.

This version intentionally uses the public Google Translate web endpoint through
the deep-translator package, so no OpenAI API key is required.

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

from deep_translator import GoogleTranslator

ROOT = Path(__file__).resolve().parents[1]
SUBJECTS = ROOT / "Subjects"
CACHE_PATH = ROOT / ".subject_translation_cache.json"

BATCH_SIZE = int(os.getenv("TRANSLATION_BATCH_SIZE", "20"))
MAX_RETRIES = 5
REQUEST_DELAY = float(os.getenv("TRANSLATION_REQUEST_DELAY", "0.2"))

LANGUAGES = {
    "gu": "gu",
    "hi": "hi",
}

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
    translator: GoogleTranslator,
    strings: list[str],
) -> dict[str, str]:
    for attempt in range(MAX_RETRIES):
        try:
            translated = translator.translate_batch(strings)
            if (
                not isinstance(translated, list)
                or len(translated) != len(strings)
                or not all(isinstance(x, str) for x in translated)
            ):
                raise ValueError("Translator returned an invalid translation batch.")

            time.sleep(REQUEST_DELAY)
            return dict(zip(strings, translated))
        except Exception as exc:
            if attempt == MAX_RETRIES - 1:
                raise RuntimeError(
                    f"Translation failed after {MAX_RETRIES} attempts: {exc}"
                ) from exc
            time.sleep(2 ** attempt)

    raise AssertionError("unreachable")


def translate_strings(
    strings: set[str],
    language: str,
    cache: dict[str, dict[str, str]],
) -> None:
    existing = cache[language]
    pending = [s for s in sorted(strings) if s not in existing]

    print(f"{language}: {len(existing)} cached, {len(pending)} pending")

    translator = GoogleTranslator(source="en", target=LANGUAGES[language])

    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start : start + BATCH_SIZE]
        result = translate_batch(translator, batch)
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
        translate_strings(all_strings, language, cache)

    for source, data in parsed.items():
        save_json(english_path(source), data)

        for language in LANGUAGES:
            localized = replace_strings(data, cache[language])
            save_json(localized_path(source, language), localized)

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
