# README screenshot provenance

The screenshots use the production UI with a reconstructed walkthrough of a real,
public change in this repository: [81886c7](https://github.com/JinhaoPlus/Codex-Microscope/commit/81886c7dc502b8296f6b39094e5140ba67d668de).
The walkthrough follows the sparse date-range overview fix.

- **Source and diff:** read from the public repository checkout. The capture helper
  runs read-only searches and file reads, retrieves the committed diff with Git,
  and runs the chart regression test. It does not apply the patch again.
- **Conversation:** reconstructed in English and Chinese to explain that change;
  it is not a verbatim private conversation or a claim that the patch was applied
  during screenshot capture.
- **Tool input schemas:** transcribed from the public Codex Rust builders at
  [e16b631d08cdf82773831f9bbfb793da687d5299](https://github.com/openai/codex/blob/e16b631d08cdf82773831f9bbfb793da687d5299/codex-rs/core/src/tools/handlers/shell_spec.rs).
  `exec_command` enables permission approvals and excludes environment IDs and
  Windows-specific guidance. The field names, types, required fields and
  descriptions come from that configuration; descriptions stay in their original
  language in both screenshots. These are versioned examples, not a guarantee
  that every Codex client exposes the same parameters.
- **Prices:** the two-model subset in `readme-price-rates.json` comes from the
  public LiteLLM source cached on 2026-11-10. The original source URL and digest
  are included. It is a reproducible illustration, not a live quote.
- **Usage:** simulated work sessions with a fixed random seed, varied project
  activity, quiet days, model mix and cache ratios. Totals and costs are computed
  by the actual `token_usage` and `pricing` modules. They are not personal usage
  records or a bill.
- **Paths and IDs:** explicit demonstration values. No home directory, account,
  private session ID or private instructions are embedded.

Codex tool definitions retain the upstream Apache-2.0 terms; see
[codex-tools.LICENSE](codex-tools.LICENSE) and [codex-tools.NOTICE](codex-tools.NOTICE).
Screenshot generation is documented in the [usage guide](../guide.md#复现-readme-截图).
