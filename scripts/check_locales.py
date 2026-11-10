#!/usr/bin/env python3
"""Validate locale message structure, per-language coverage, and metadata."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "designs" / "browser" / "locales"
PUBLIC_FILES = ROOT / "scripts" / "public-files.txt"

KEY_PATTERN = re.compile(r"^[a-z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9_-]+)+$")
PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

REQUIRED_PUBLIC = [
    "designs/browser/i18n.js",
    "designs/browser/locales/manifest.json",
    "designs/browser/locales/messages.schema.json",
    "designs/browser/locales/messages.meta.json",
    "designs/browser/locales/zh-CN.json",
    "designs/browser/locales/en.json",
    "scripts/check_locales.py",
    "designs/browser/local-directory.html",
    "designs/browser/local-directory.js",
    "designs/browser/local-directory.css",
]


def load_json(path: Path) -> dict:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{path.name}: duplicate JSON key {key!r}")
            result[key] = value
        return result
    result = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if not isinstance(result, dict):
        raise ValueError(f"{path.name}: expected a JSON object")
    return result


def err(errors: list[str], message: str) -> None:
    errors.append(message)


def placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(text))


def collect_strings(value: str | dict) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [v for v in value.values() if isinstance(v, str)]
    return []


def validate_value(key: str, value: str | dict, plural: bool, plurals: list[str], errors: list[str]) -> None:
    if isinstance(value, str):
        if plural:
            err(errors, f"{key}: meta says plural but value is string")
        if value.strip() == "":
            err(errors, f"{key}: empty string value")
        return
    if not isinstance(value, dict):
        err(errors, f"{key}: expected string or plural object")
        return
    if not plural:
        err(errors, f"{key}: meta says non-plural but value is object")
    branches = {k: v for k, v in value.items() if isinstance(v, str)}
    if len(branches) != len(value):
        err(errors, f"{key}: plural branches must be strings")
    if not branches:
        err(errors, f"{key}: plural object has no string branches")
    for cat in branches:
        if cat not in plurals:
            err(errors, f"{key}: plural branch '{cat}' not in manifest plurals {plurals}")
    for required in set(plurals) | {'other'}:
        if required not in branches or branches[required].strip() == "":
            err(errors, f"{key}: missing or empty plural branch '{required}'")
    for text in branches.values():
        if text.strip() == "":
            err(errors, f"{key}: empty plural string")


def check_public_files(errors: list[str]) -> None:
    if not PUBLIC_FILES.is_file():
        err(errors, f"Missing {PUBLIC_FILES}")
        return
    listed = {line.strip() for line in PUBLIC_FILES.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")}
    for rel in REQUIRED_PUBLIC:
        if rel not in listed:
            err(errors, f"scripts/public-files.txt missing entry: {rel}")


def main() -> int:
    errors: list[str] = []

    manifest = load_json(LOCALES / "manifest.json")
    meta = load_json(LOCALES / "messages.meta.json")
    meta_keys: dict = meta.get("keys") or {}

    if "glossary" not in meta:
        err(errors, "messages.meta.json: missing glossary")

    enabled = [lid for lid, cfg in manifest.get("locales", {}).items() if cfg.get("enabled", True)]
    if not enabled:
        err(errors, "manifest: at least one locale must be enabled")
    for field in ('default', 'fallback'):
        if manifest.get(field) not in enabled:
            err(errors, f"manifest: {field} must name an enabled locale")

    bundles: dict[str, dict] = {}
    for locale_id in enabled:
        if not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", locale_id):
            err(errors, f"manifest: invalid locale ID {locale_id!r}")
            continue
        path = LOCALES / f"{locale_id}.json"
        if not path.is_file():
            err(errors, f"Missing locale file {path}")
            continue
        bundles[locale_id] = load_json(path)

    check_public_files(errors)

    for locale_id, bundle in bundles.items():
        for missing_key in meta_keys.keys() - bundle.keys():
            err(errors, f"{locale_id}: missing key {missing_key}")
        cfg = manifest["locales"][locale_id]
        plurals = list(cfg.get("plurals") or ["other"])
        for key, value in bundle.items():
            if not KEY_PATTERN.match(key):
                err(errors, f"{locale_id}: invalid key {key!r}")
            if key not in meta_keys:
                err(errors, f"{locale_id}: unknown key vs meta: {key}")
                continue
            info = meta_keys[key]
            validate_value(key, value, bool(info.get("plural")), plurals, errors)
            expected = {p["name"] for p in info.get("params") or []}
            required = {
                p["name"]
                for p in info.get("params") or []
                if not p.get("optional")
            }
            # Every branch is a complete message. Count placeholders remain named,
            # including in `one`, so unrelated quantities cannot silently become 1.
            ph_texts = collect_strings(value)
            for text in ph_texts:
                if re.search(r"<[A-Za-z/][^>]*>", text):
                    err(errors, f"{locale_id} {key}: HTML is not allowed in messages")
                if re.search(r"%(?:\d+\$)?[sd]", text):
                    err(errors, f"{locale_id} {key}: unsupported printf placeholder")
                if locale_id.split('-')[0].lower() == 'en' and re.search(r"[\u3400-\u9fff]", text):
                    err(errors, f"{locale_id} {key}: untranslated Chinese text")
                found = placeholders(text)
                extra = found - expected
                missing = required - found
                if extra:
                    err(errors, f"{locale_id} {key}: unexpected placeholders {sorted(extra)}")
                if missing:
                    err(errors, f"{locale_id} {key}: missing placeholders {sorted(missing)}")

    if errors:
        print("Locale check failed:", file=sys.stderr)
        for line in errors:
            print(f"  - {line}", file=sys.stderr)
        return 1

    print(f"Locale check OK ({len(meta_keys)} keys, enabled: {', '.join(enabled)})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f"Locale check failed: {error}", file=sys.stderr)
        raise SystemExit(1)
