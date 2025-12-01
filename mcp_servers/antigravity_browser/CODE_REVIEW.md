# CODE REVIEW: antigravity_browser MCP Server

## Summary

MCP server for browser automation via Chrome DevTools Protocol (CDP). Provides AI-friendly abstraction layer over low-level browser operations.

**Verdict: REQUEST_CHANGES**

The codebase has significant structural and quality issues that must be addressed before production use.

---

## Risk Table

| Category     | Risk Level | Notes |
|-------------|------------|-------|
| Security    | MEDIUM     | No hardcoded secrets, but eval_js executes arbitrary JS without sandboxing |
| Correctness | HIGH       | No tests at all (0% coverage), bare except blocks |
| Performance | MEDIUM     | Synchronous blocking I/O, duplicated JS code in every tool call |
| DX          | HIGH       | Massive files (1791 LOC in server.py), no pyproject.toml, 9000+ linter warnings |

---

## Gate Checklist

| Gate | Status | Notes |
|------|--------|-------|
| Tests >= 90% diff coverage | FAIL | 0% - No tests exist |
| Static/lint 0 errors | FAIL | 9025 ruff warnings, cyclomatic complexity F(71) |
| Security 0 High/Critical | PASS | No critical vulnerabilities found |
| Performance no obvious issues | WARN | Blocking I/O, duplicated helpers |
| Edge-state handling | WARN | Bare `except Exception` in 50+ locations |

---

## Findings

### CRITICAL (Blockers)

#### [C-001] ZERO TEST COVERAGE
**Path:** Entire project
**Issue:** No test files exist (`**/test*.py`, `**/*_test.py` - 0 matches)
**Impact:** Cannot validate correctness, refactoring is extremely risky
**Fix:** Create comprehensive test suite with unit + integration tests

#### [C-002] Extreme Cyclomatic Complexity in handle_call_tool
**Path:** `server.py:1242`
**Complexity:** F(71) - extreme (should be <= 10)
**Issue:** Single 500+ line method with massive if-elif chain for 30+ tool dispatch
**Fix:** Implement Command pattern or tool registry with dispatch table

```python
# Bad: Current approach
def handle_call_tool(self, request_id, name, arguments):
    if name == "analyze_page":
        ...
    elif name == "click_element":
        ...
    # 30+ more elif branches
```

```python
# Good: Registry pattern
TOOL_HANDLERS = {
    "analyze_page": _handle_analyze_page,
    "click_element": _handle_click_element,
    ...
}

def handle_call_tool(self, request_id, name, arguments):
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return self._error_response("unknown_tool")
    return handler(self.config, arguments)
```

#### [C-003] Massive File Sizes
**Paths:**
- `server.py`: 1791 lines (limit ~300)
- `tools/page.py`: 1322 lines
- `tools/smart.py`: 905 lines
- `tools/captcha.py`: 835 lines
- `session.py`: 479 lines
- `tools/input.py`: 425 lines

**Fix:** Decompose into logical modules:
- `server.py` -> `server/`, `tools/registry.py`, `protocol/`
- `page.py` -> `page/overview.py`, `page/forms.py`, `page/content.py`, etc.

---

### HIGH

#### [H-001] 50+ Bare except Exception Blocks
**Pattern:** `except Exception as e:` without proper exception handling
**Paths:** `session.py:99, 345, 435, 474`, `tools/input.py:46, 75, 104...` (50+ locations)
**Issue:** Catches all exceptions including KeyboardInterrupt, SystemExit
**Fix:** Catch specific exceptions or use `except Exception:` with logging + re-raise for unknown types

#### [H-002] Global Mutable State
**Paths:** `tools/page.py:24, 84, 1267`, `tools/base.py:119`
**Issue:** `global _page_context` - thread-unsafe, testing nightmare
**Fix:** Inject page context via session or use thread-local storage

#### [H-003] Massive JS Code Duplication
**Count:** 62 occurrences of `isVisible`, `getCleanText` helpers across tools
**Issue:** Same helper functions copy-pasted into every JS eval string
**Fix:** Create shared JS library, inject via CDP or template system

```python
# Good: Shared helpers
JS_HELPERS = """
const isVisible = (el) => {...};
const getCleanText = (el) => {...};
"""

def build_js(custom_code):
    return f"(() => {{ {JS_HELPERS}\n{custom_code} }})()"
```

#### [H-004] No Package Configuration
**Issue:** Missing `pyproject.toml`, `setup.py`, `requirements.txt`
**Impact:** Cannot install as package, dependency management undefined
**Fix:** Add pyproject.toml with proper metadata and dependencies

#### [H-005] Hardcoded Example Credentials in Documentation
**Path:** `server.py:162, 300`
**Content:** `"password": "secret123"`, `password: "123"`
**Issue:** Example credentials that could be copy-pasted
**Fix:** Use obviously fake values: `"password": "<YOUR_PASSWORD>"` or `"password": "EXAMPLE_DO_NOT_USE"`

---

### MEDIUM

#### [M-001] Missing Type Definitions for Return Values
**Pattern:** Most functions return `dict[str, Any]`
**Issue:** No TypedDict or dataclass for structured responses
**Fix:** Define response types:

```python
@dataclass
class ToolResult:
    success: bool
    target: str
    data: dict[str, Any] | None = None
    error: str | None = None
```

#### [M-002] 9025 Ruff Warnings
**Breakdown:**
- 157 trailing commas missing (COM812)
- 39 docstring issues (D212)
- 23 executable without shebang (EXE002)
- 21 relative imports (TID252)
- 16 boolean positional args (FBT001)
- 15 abstract raise (TRY301)
- 14 type-checking imports (TC001)
- 7 blind exception catch (BLE001)

**Fix:** Add ruff configuration and fix progressively

#### [M-003] Synchronous Blocking I/O
**Issue:** All operations are synchronous, blocking event loop
**Impact:** Cannot handle concurrent requests efficiently
**Note:** May be acceptable for single-agent use case, but limits scalability

#### [M-004] URL Audit Warning (S310)
**Paths:** 8 occurrences in `http_client.py`, `session.py`
**Issue:** `urlopen` allows file:// and custom schemes without audit
**Fix:** Add explicit scheme validation or use requests library

#### [M-005] Magic Numbers and Strings
**Examples:**
- Timeout defaults: `5.0`, `10.0`, `2.0` scattered across codebase
- Grid sizes: `3`, `4` in captcha.py
- Port: `9222` hardcoded
**Fix:** Extract to named constants in config

---

### LOW

#### [L-001] Inconsistent Response Format
**Issue:** Some tools return `{"success": True, ...}`, others return raw data
**Fix:** Standardize all responses to consistent schema

#### [L-002] Session Close Pattern
**Path:** `tools/base.py:150-154`
**Issue:** Manual session.close() in finally - could use context manager pattern more consistently

#### [L-003] Import Organization
**Issue:** Relative imports from parent modules (TID252)
**Fix:** Use absolute imports or restructure package

#### [L-004] Missing Module Docstrings
**Paths:** `config.py`, `http_client.py`, `__init__.py`
**Fix:** Add module-level docstrings

#### [L-005] Unused Global Variable
**Path:** `tools/base.py:119` - `_page_context` defined but only used in `tools/page.py`
**Fix:** Move to page.py or proper state management

---

## Architecture Issues

### SOLID Violations

1. **Single Responsibility Principle (SRP)**
   - `server.py` handles: protocol parsing, tool dispatch, result formatting, logging, browser lifecycle
   - Should be split into: `protocol.py`, `dispatcher.py`, `handlers/`, `lifecycle.py`

2. **Open/Closed Principle (OCP)**
   - Adding new tool requires modifying massive if-elif in `handle_call_tool`
   - Should use registry pattern for extensibility

3. **Dependency Inversion Principle (DIP)**
   - Tools directly import and instantiate `session_manager` singleton
   - Should inject session provider interface

### Module Coupling

```
server.py ─────┬─> smart_tools.py ─> tools/* (15 modules)
               ├─> config.py
               ├─> http_client.py
               └─> launcher.py ──────> config.py

tools/* ───────┬─> base.py ──> session.py ──> http_client.py
               └─> config.py
```

**Issue:** High coupling between tools and session management. Every tool imports session infrastructure.

---

## Recommended Fixes (Priority Order)

### Phase 1: Critical (Week 1)
1. Add test infrastructure (pytest, fixtures for browser mock)
2. Split `handle_call_tool` into registry pattern
3. Begin file size reduction (extract tool_definitions to JSON/YAML)

### Phase 2: High (Week 2-3)
1. Add type definitions for responses
2. Fix bare except blocks (catch specific exceptions)
3. Create shared JS helpers module
4. Add pyproject.toml

### Phase 3: Medium (Week 4)
1. Fix ruff warnings (start with security-related)
2. Extract magic constants
3. Standardize response format

### Phase 4: Low (Ongoing)
1. Add comprehensive docstrings
2. Refactor to async if scalability needed
3. Add property-based tests for parsers

---

## Commands to Reproduce

```bash
# Cyclomatic complexity analysis
python3 -m radon cc /path/to/antigravity_browser -a -s | grep -E "\s+[D-F]\s"

# Ruff linter
python3 -m ruff check /path/to/antigravity_browser --select ALL 2>&1 | wc -l

# File line counts
wc -l /path/to/antigravity_browser/**/*.py | sort -n

# Find duplicated JS helpers
grep -rn "isVisible\|getCleanText" tools/*.py | wc -l

# Find bare except blocks
grep -rn "except Exception" /path/to/antigravity_browser
```

---

## Verdict

**REQUEST_CHANGES**

The codebase cannot be shipped in current state due to:
1. Zero test coverage (BLOCKER)
2. Extreme cyclomatic complexity in core dispatch (BLOCKER)
3. Files exceeding 300 LOC limit by 4-6x (BLOCKER)

Minimum required before approval:
- [ ] Test coverage >= 50% for core modules
- [ ] `handle_call_tool` complexity <= 10
- [ ] No file > 400 lines
- [ ] Bare except blocks reduced by 80%

---

*Generated: 2025-12-01*
*Reviewer: Claude Code Audit*
