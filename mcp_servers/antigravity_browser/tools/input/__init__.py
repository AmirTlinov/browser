"""
Mouse and keyboard input tools for browser automation.

Provides:
- Mouse operations: click, double-click, move, hover, drag
- Keyboard operations: press key, type text
- DOM actions: click element, type into element
- Scroll operations: scroll page, scroll to element
"""

from .dom import dom_action_click, dom_action_type
from .keyboard import press_key, type_text
from .mouse import click_at_pixel, double_click_at_pixel, drag_from_to, hover_element, move_mouse_to
from .scroll import scroll_page, scroll_to_element

__all__ = [
    # Mouse
    "click_at_pixel",
    "double_click_at_pixel",
    "move_mouse_to",
    "hover_element",
    "drag_from_to",
    # Keyboard
    "press_key",
    "type_text",
    # DOM
    "dom_action_click",
    "dom_action_type",
    # Scroll
    "scroll_page",
    "scroll_to_element",
]
