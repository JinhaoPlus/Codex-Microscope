# Local JSON Schema viewer

The browser loads the prebuilt `designs/browser/vendor/schema-viewer.js` only
when a tool definition is opened fullscreen. It mounts the official
`@stoplight/json-schema-viewer` in a Shadow DOM. The small popover does not mount
or load the viewer. Closing fullscreen unmounts React and disconnects its theme
observer. Build tools are optional for normal installation and use.

To rebuild from this directory (requires Node/npm):

```sh
npm ci --ignore-scripts
npm run build
```

Versions are pinned by `package.json` and `package-lock.json`. Commit the generated
JS, CSS, and `schema-viewer.LICENSE` together with source changes. There are no CDN
imports, runtime package downloads, or source maps with machine paths.

The official renderer and its Mosaic styles are bundled locally. Markdown
is deliberately adapted to the existing local markdown-it renderer with HTML
disabled. Description images are rendered as text instead of loading remote
resources; links use markdown-it's URL checks and `noopener noreferrer`.
The adapter retains the viewer's expandable long-description behavior.
The two combiner pickers use native HTML selects through the `mosaic.js` adapter;
Mosaic's popup focus scope retains shadow-root event targets across animation
frames, causing null-target focus errors. The adapter changes only these controls,
not Schema parsing, node selection semantics, or the upstream package files.

The default resolver handles local schema references; external references are
not fetched. Reference expansion is bounded with `maxRefDepth: 4`. The library
advertises Draft 4 support; it must not be presented as complete support for
newer dialects (`if/then/else`, `prefixItems`, etc.). The exact original Schema
remains available below the viewer even after loading/rendering errors.
Boolean schemas and an empty schema have explicit any-value/no-value messages.

`build.mjs` collects notices for packages included by esbuild. A few published
MIT packages omit standalone license files; `licenses/` records their published
attribution and standard MIT terms. The build fails for missing notices.

Browser regression checks require a running local server and Chrome/Chromium.
Run `npm test` from this directory with `SCHEMA_TEST_BROWSER` pointing to the
browser executable (`SCHEMA_TEST_URL` optionally overrides the local server URL).
The checks inject synthetic definitions into `/demo`, cover 1280/390px, lazy
loading, Markdown safety, dark mode, nested/root combiner switches and unmount/
reopen behavior, and fail on browser errors or external network requests.
No real conversation records are used.
