"""
TypedDict definitions for browser automation tool responses.

These types provide static type checking and documentation for the
dictionary structures returned by browser automation tools.
"""
from __future__ import annotations

from typing import Any, NotRequired, TypedDict


# ═══════════════════════════════════════════════════════════════════════════════
# Common response types
# ═══════════════════════════════════════════════════════════════════════════════


class TargetInfo(TypedDict):
    """Browser target identification."""

    id: str
    webSocketDebuggerUrl: NotRequired[str]
    url: NotRequired[str]


class ActionResult(TypedDict, total=False):
    """Result of a browser action (click, type, navigate, etc.)."""

    success: bool
    target: str
    message: NotRequired[str]


class NavigationResult(TypedDict, total=False):
    """Result of navigation actions."""

    success: bool
    url: str
    title: NotRequired[str]
    target: str


# ═══════════════════════════════════════════════════════════════════════════════
# Pagination types
# ═══════════════════════════════════════════════════════════════════════════════


class PaginationNav(TypedDict, total=False):
    """Pagination navigation hints."""

    prev: str
    next: str


class PaginatedResponse(TypedDict, total=False):
    """Base type for paginated responses."""

    total: int
    offset: int
    limit: int
    hasMore: bool
    navigation: PaginationNav


# ═══════════════════════════════════════════════════════════════════════════════
# Cookie types
# ═══════════════════════════════════════════════════════════════════════════════


class CookieInfo(TypedDict, total=False):
    """Cookie data structure."""

    name: str
    value: str
    domain: str
    path: str
    expires: float
    size: int
    httpOnly: bool
    secure: bool
    session: bool
    sameSite: str


class CookieResult(TypedDict):
    """Result of cookie operations."""

    success: bool


class CookiesResponse(PaginatedResponse, total=False):
    """Response from get_all_cookies."""

    cookies: list[CookieInfo]


# ═══════════════════════════════════════════════════════════════════════════════
# Tab types
# ═══════════════════════════════════════════════════════════════════════════════


class TabInfo(TypedDict, total=False):
    """Tab information."""

    id: str
    url: str
    title: str
    active: bool
    isCurrent: NotRequired[bool]


class TabsResponse(PaginatedResponse, total=False):
    """Response from list_tabs."""

    tabs: list[TabInfo]
    currentTabId: str


class TabOperationResult(TypedDict, total=False):
    """Result of tab operations (switch, new, close)."""

    result: dict[str, Any]


# ═══════════════════════════════════════════════════════════════════════════════
# DOM types
# ═══════════════════════════════════════════════════════════════════════════════


class DomResult(TypedDict, total=False):
    """Result of DOM operations."""

    html: str
    totalChars: int
    returnedChars: NotRequired[int]
    truncated: bool
    hint: NotRequired[str]
    targetId: str


class ElementInfo(TypedDict, total=False):
    """Element information."""

    selector: str
    tagName: str
    id: NotRequired[str]
    className: NotRequired[str]
    text: NotRequired[str]
    bounds: NotRequired[dict[str, float]]
    attributes: NotRequired[dict[str, str]]
    visible: bool


class PageInfo(TypedDict, total=False):
    """Page metadata."""

    url: str
    title: str
    scrollX: int
    scrollY: int
    innerWidth: int
    innerHeight: int
    documentWidth: int
    documentHeight: int


class PageInfoResponse(TypedDict):
    """Response from get_page_info."""

    pageInfo: PageInfo
    target: str


# ═══════════════════════════════════════════════════════════════════════════════
# Form types
# ═══════════════════════════════════════════════════════════════════════════════


class FormField(TypedDict, total=False):
    """Form field information."""

    type: str
    name: str
    id: NotRequired[str]
    label: str
    placeholder: NotRequired[str]
    required: bool
    hasValue: NotRequired[bool]
    selector: NotRequired[str]
    options: NotRequired[list[dict[str, str]]]


class FormInfo(TypedDict, total=False):
    """Form information."""

    index: int
    id: NotRequired[str]
    name: NotRequired[str]
    action: NotRequired[str]
    method: str
    fields: list[FormField]
    fieldCount: int
    submitText: NotRequired[str]
    submitButton: NotRequired[dict[str, str]]


# ═══════════════════════════════════════════════════════════════════════════════
# Page analysis types
# ═══════════════════════════════════════════════════════════════════════════════


class PageCounts(TypedDict, total=False):
    """Element counts on page."""

    forms: int
    links: int
    buttons: int
    inputs: int


class PagePreview(TypedDict, total=False):
    """Preview data for page overview."""

    forms: list[dict[str, Any]]
    topLinks: list[str]
    topButtons: list[str]
    content: NotRequired[str]


class PageOverview(TypedDict, total=False):
    """Page analysis overview."""

    url: str
    title: str
    pageType: str
    counts: PageCounts
    preview: PagePreview
    suggestedActions: list[str]
    hints: dict[str, str]


class AnalyzePageResult(TypedDict, total=False):
    """Result of analyze_page."""

    overview: NotRequired[PageOverview]
    detail: NotRequired[str]
    target: str
    error: NotRequired[bool]
    reason: NotRequired[str]


# ═══════════════════════════════════════════════════════════════════════════════
# Content extraction types
# ═══════════════════════════════════════════════════════════════════════════════


class LinkInfo(TypedDict, total=False):
    """Link information."""

    text: str
    href: str
    isExternal: bool


class HeadingInfo(TypedDict, total=False):
    """Heading information."""

    level: int
    text: str


class ImageInfo(TypedDict, total=False):
    """Image information."""

    src: str
    alt: str
    width: NotRequired[int]
    height: NotRequired[int]


class TableRow(TypedDict, total=False):
    """Table row data."""

    cells: list[str]


class TableInfo(TypedDict, total=False):
    """Table information."""

    index: int
    rows: int
    cols: int
    headers: NotRequired[list[str]]


class ExtractContentResult(PaginatedResponse, total=False):
    """Result of extract_content."""

    contentType: str
    items: list[Any]
    target: str


# ═══════════════════════════════════════════════════════════════════════════════
# Wait types
# ═══════════════════════════════════════════════════════════════════════════════


class WaitResult(TypedDict, total=False):
    """Result of wait_for."""

    success: bool
    condition: str
    elapsed: float
    timeout: NotRequired[float]
    target: str
    text: NotRequired[str]
    selector: NotRequired[str]
    old_url: NotRequired[str]
    new_url: NotRequired[str]
    suggestion: NotRequired[str]


# ═══════════════════════════════════════════════════════════════════════════════
# CAPTCHA types
# ═══════════════════════════════════════════════════════════════════════════════


class CaptchaClickableArea(TypedDict):
    """CAPTCHA clickable area."""

    id: int
    name: str
    selector: str


class CaptchaAnalysis(TypedDict, total=False):
    """Result of analyze_captcha."""

    detected: bool
    type: str
    selector: NotRequired[str]
    state: NotRequired[str]
    challenge: NotRequired[str]
    grid_size: NotRequired[int]
    clickable_areas: NotRequired[list[CaptchaClickableArea]]
    suggestion: str
    target: str


class CaptchaScreenshot(TypedDict, total=False):
    """Result of get_captcha_screenshot."""

    image_base64: str
    grid_size: int
    blocks_shown: list[int]
    hint: str
    target: str


class CaptchaClickResult(TypedDict, total=False):
    """Result of click_captcha_blocks or click_captcha_area."""

    success: bool
    clicked: list[int] | int
    message: str
    target: str


# ═══════════════════════════════════════════════════════════════════════════════
# Smart tool types
# ═══════════════════════════════════════════════════════════════════════════════


class ClickElementResult(TypedDict, total=False):
    """Result of click_element."""

    success: bool
    clicked: str
    selector: NotRequired[str]
    element_text: NotRequired[str]
    target: str


class FillFormResult(TypedDict, total=False):
    """Result of fill_form."""

    success: bool
    filled: dict[str, bool]
    submitted: bool
    target: str


class SearchPageResult(TypedDict, total=False):
    """Result of search_page."""

    success: bool
    query: str
    submitted: bool
    target: str


class WorkflowStepResult(TypedDict, total=False):
    """Result of a workflow step."""

    step: int
    action: str
    success: bool
    result: dict[str, Any]
    error: NotRequired[str]


class WorkflowResult(TypedDict, total=False):
    """Result of execute_workflow."""

    success: bool
    steps_executed: int
    steps_total: int
    results: list[WorkflowStepResult]
    failed_step: NotRequired[int]
    error: NotRequired[str]


# ═══════════════════════════════════════════════════════════════════════════════
# Input types
# ═══════════════════════════════════════════════════════════════════════════════


class ClickResult(TypedDict, total=False):
    """Result of click operations."""

    success: bool
    x: float
    y: float
    button: NotRequired[str]
    target: str


class TypeResult(TypedDict, total=False):
    """Result of type operations."""

    success: bool
    selector: NotRequired[str]
    typed: str
    target: str


class ScrollResult(TypedDict, total=False):
    """Result of scroll operations."""

    success: bool
    delta_x: float
    delta_y: float
    target: str


class KeyPressResult(TypedDict, total=False):
    """Result of key press."""

    success: bool
    key: str
    modifiers: NotRequired[int]
    target: str


# ═══════════════════════════════════════════════════════════════════════════════
# Network types
# ═══════════════════════════════════════════════════════════════════════════════


class FetchResult(TypedDict, total=False):
    """Result of browser_fetch."""

    ok: bool
    status: int
    statusText: str
    headers: NotRequired[dict[str, str]]
    body: str
    truncated: NotRequired[bool]


class EvalJsResult(TypedDict, total=False):
    """Result of eval_js."""

    result: Any
    target: str


# ═══════════════════════════════════════════════════════════════════════════════
# Error type
# ═══════════════════════════════════════════════════════════════════════════════


class ToolError(TypedDict):
    """Structured error from tools."""

    error: bool
    tool: str
    action: str
    reason: str
    suggestion: str
    details: NotRequired[dict[str, Any]]
