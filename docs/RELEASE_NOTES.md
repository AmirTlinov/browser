[LEGEND]
REL_2026_01_24 = Release 2026-01-24.
REL_2026_01_26 = Release 2026-01-26.
REL_2026_01_26B = Release 2026-01-26 (update B).
REL_2026_01_26C = Release 2026-01-26 (update C).
REL_2026_01_26D = Release 2026-01-26 (update D).
FEAT_DOWNLOADS = Download capture robustness: browser-level CDP fallback, fallback download dirs, safer download clicks.
FEAT_SMOKE = Live-site smoke suite expanded with real sites and edge cases.
FEAT_AUTO_SCROLL = Page tool auto-scroll prepass for lazy-loaded content.
FEAT_JS_COND = JS condition support for run internal assert/when/repeat.
FEAT_MACROS_PAGINATE = New run macros: scroll_to_end and paginate_next.
FEAT_MACRO_EXPAND = New run macro: auto_expand for show-more/read-more expansion.
FEAT_SMOKE_MACROS = Live-site smoke expanded for macro pagination/scroll (feature-flagged).
FEAT_PAGE_AUTO_EXPAND = Page tool auto-expand prepass for collapsed content.
FEAT_MACRO_PIPELINE = New run macro pipeline: auto_expand_scroll_extract.
FEAT_EXPAND_SEMANTIC = Auto-expand heuristics extended with semantic aria/data hints.
FEAT_EXTRACT_UNIFIED = Unified extract_content tool exposed for run/flow.
FEAT_SMOKE_EXTRACT = Live-site smoke for auto_expand_scroll_extract (feature-flagged).
DOC_EXTRACT_PACK = Agent playbook + runbook pack expanded with one-call extract variants.
DOC_RUNBOOK_PACK_V2 = Runbook pack extended with pagination and table-index variants.
DOC_SKILL_PACK = Skill packaging doc for browser-mcp-effective.
DOC_ANTI_FLAKE = Runbook anti-flakiness defaults (auto_dialog/auto_tab/auto_affordances).
FEAT_AUTO_DISMISS_OVERLAYS = Auto-dismiss blocking overlays before click/type/form (run/flow).
DOC_AUTO_DISMISS_OVERLAYS = Docs: auto_dismiss_overlays guidance.
FEAT_DOWNLOAD_FALLBACK = Download wait can fall back to default OS download dirs when CDP behavior is unavailable.
FEAT_AUTO_DOWNLOAD_ABORT = Auto-download can proceed after ERR_ABORTED if a download is captured.
FEAT_TABS_SESSION_SCOPE = tabs list defaults to session-only; include_all opt-out.
FIX_WHEN_TEXT = when text matcher normalizes and can scope by selector.
FIX_MACRO_EXTRACT_SYNC = auto_expand_scroll_extract inserts DOM ready wait and avoids selector=null.
TEST_SMOKE_EDGE = Live/edge smoke expanded for macro+when regression checks.
DOC_MACRO_SYNC = Macro docs updated for DOM wait and selector safety.

[CONTENT]
## [REL_2026_01_24]
- [FEAT_DOWNLOADS]
- [FEAT_SMOKE]
- [FEAT_AUTO_SCROLL]
- [FEAT_JS_COND]
- [FEAT_MACROS_PAGINATE]
- [FEAT_MACRO_EXPAND]
- [FEAT_SMOKE_MACROS]
- [FEAT_PAGE_AUTO_EXPAND]
- [FEAT_MACRO_PIPELINE]
- [FEAT_EXPAND_SEMANTIC]
- [FEAT_EXTRACT_UNIFIED]
- [FEAT_SMOKE_EXTRACT]
- [DOC_EXTRACT_PACK]

## [REL_2026_01_26]
- [DOC_RUNBOOK_PACK_V2]
- [DOC_SKILL_PACK]
- [DOC_ANTI_FLAKE]

## [REL_2026_01_26B]
- [FEAT_AUTO_DISMISS_OVERLAYS]
- [DOC_AUTO_DISMISS_OVERLAYS]

## [REL_2026_01_26C]
- [FEAT_DOWNLOAD_FALLBACK]
- [FEAT_AUTO_DOWNLOAD_ABORT]
- [FEAT_TABS_SESSION_SCOPE]
- [FIX_WHEN_TEXT]
- [FIX_MACRO_EXTRACT_SYNC]

## [REL_2026_01_26D]
- [TEST_SMOKE_EDGE]
- [DOC_MACRO_SYNC]
