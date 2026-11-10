# Third-party UI strings (i18n exceptions)

Codex Microscope keeps a single HTML/JS UI and loads product copy from locale bundles. Some vendor surfaces still show English or app-supplied accessibility text.

## Schema Viewer (`@stoplight/json-schema-viewer` + Mosaic adapter)

| Surface | Owner | Notes |
| --- | --- | --- |
| Adapter strings (`emptyText`, forbid/allow any value, type selector aria) | **Own** — keys in locale bundles (`context.schema.*`, `accessibility.schemaSelectType`, `common.imageFallbackAlt`) | Adapters read the current locale through the shared translation runtime; the bundle is rebuilt from the same source for both languages. |
| Constraint chrome (`required`, combiners, `nullable`, `Default`, `Example`, JSON Schema type names) | **Stoplight bundle** (`designs/browser/vendor/schema-viewer.js`) | English hardcoded in minified vendor build. No supported locale pack. Options: accept English chrome, upstream/fork change, or targeted a11y/CSS mitigations — **no** blind string replace in the bundle. |
| Example values / schema titles (`Text`, `Number`, …) | Schema data or upstream | Treated as schema content, not product UI. |

## noUiSlider (`vendor/nouislider.min.js`)

| Surface | Owner | Notes |
| --- | --- | --- |
| Handle `aria-label` (`usage.handleStartAria` / `usage.handleEndAria`) | **App** via `handleAttributes` | noUiSlider has no locale files; labels come from our messages. |
| `aria-valuetext` (ISO dates) | **App** | Displayed dates use the selected locale through `I18n.formatDate`; ISO date keys remain unchanged internally. |
| Library `console` warnings | Vendor | Not product UI; English only. |

## Other vendors (markdown-it, highlight.js, lucide)

No user-facing product strings beyond decorative icons and syntax-colored code (data).
