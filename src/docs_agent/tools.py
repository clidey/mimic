"""Tool dispatch and execution handlers for the computer-use agent."""

from __future__ import annotations

import logging
import time
from typing import Any

from docs_agent.docker_manager import exec_in_desktop, take_screenshot, xdotool

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Screenshot helper
# ---------------------------------------------------------------------------

def screenshot_result(b64: str | None) -> list[dict[str, Any]]:
    """Build a tool_result content block from a screenshot, handling failures."""
    if b64:
        return [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}]
    return [{"type": "text", "text": "Screenshot failed — the desktop display may be unavailable."}]


# ---------------------------------------------------------------------------
# Individual tool handlers
# ---------------------------------------------------------------------------

def execute_computer_tool(action: str, **kwargs: Any) -> list[dict[str, Any]]:
    """Execute a computer-use action and return tool_result content blocks."""
    if action == "screenshot":
        return screenshot_result(take_screenshot())

    if action == "left_click":
        x, y = kwargs["coordinate"]
        xdotool(f"mousemove {x} {y} click 1")
    elif action == "right_click":
        x, y = kwargs["coordinate"]
        xdotool(f"mousemove {x} {y} click 3")
    elif action == "double_click":
        x, y = kwargs["coordinate"]
        xdotool(f"mousemove {x} {y} click --repeat 2 1")
    elif action == "triple_click":
        x, y = kwargs["coordinate"]
        xdotool(f"mousemove {x} {y} click --repeat 3 1")
    elif action == "middle_click":
        x, y = kwargs["coordinate"]
        xdotool(f"mousemove {x} {y} click 2")
    elif action == "mouse_move":
        x, y = kwargs["coordinate"]
        xdotool(f"mousemove {x} {y}")
    elif action == "type":
        text = kwargs["text"]
        escaped = str(text).replace("'", "'\\''")
        xdotool(f"type --delay 12 '{escaped}'")
    elif action == "key":
        key = str(kwargs["text"])
        xdotool(f"key {key}")
    elif action == "scroll":
        x, y = kwargs["coordinate"]
        direction = kwargs.get("scroll_direction", kwargs.get("direction", "down"))
        amount = int(kwargs.get("scroll_amount", kwargs.get("amount", 3)))
        button_map = {"up": 4, "down": 5, "left": 6, "right": 7}
        button = button_map.get(direction, 5)
        xdotool(f"mousemove {x} {y}")
        xdotool(f"click --repeat {amount} {button}")
    elif action == "left_click_drag":
        sx, sy = kwargs["start_coordinate"]
        ex, ey = kwargs["coordinate"]
        xdotool(f"mousemove {sx} {sy} mousedown 1")
        xdotool(f"mousemove {ex} {ey} mouseup 1")
    elif action == "wait":
        secs = int(kwargs.get("duration", 2))
        time.sleep(secs)
    else:
        return [{"type": "text", "text": f"Unknown computer action: {action}"}]

    # For non-screenshot actions, auto-take a screenshot to show result
    return screenshot_result(take_screenshot())


def execute_bash_tool(command: str) -> list[dict[str, Any]]:
    """Execute a bash command inside the desktop container."""
    output = exec_in_desktop(command, timeout=60)
    return [{"type": "text", "text": output or "(no output)"}]


def execute_text_editor_tool(command: str, **kwargs: Any) -> list[dict[str, Any]]:
    """Execute a text editor command inside the desktop container."""
    path = kwargs.get("path", "")
    if command == "view":
        output = exec_in_desktop(f"cat '{path}'")
    elif command == "create":
        content = str(kwargs.get("file_text", ""))
        escaped = content.replace("'", "'\\''")
        exec_in_desktop(f"mkdir -p $(dirname '{path}') && printf '%s' '{escaped}' > '{path}'")
        output = f"Created {path}"
    elif command == "str_replace":
        old = str(kwargs.get("old_str", ""))
        new = str(kwargs.get("new_str", ""))
        old_esc = old.replace("'", "'\\''")
        new_esc = new.replace("'", "'\\''")
        exec_in_desktop(
            f"python3 -c \"\nimport pathlib\np = pathlib.Path('{path}')\nt = p.read_text()\nassert t.count('''{old_esc}''') == 1, f'Expected 1 occurrence, found {{t.count(\\\"\\\"\\\"{ old_esc }\\\"\\\"\\\")}}'\np.write_text(t.replace('''{old_esc}''', '''{new_esc}''', 1))\nprint('Replaced successfully')\n\""
        )
        output = f"Replaced in {path}"
    elif command == "insert":
        line = int(kwargs.get("insert_line", 0))
        text = str(kwargs.get("new_str", ""))
        text_esc = text.replace("'", "'\\''")
        exec_in_desktop(
            f"python3 -c \"\nimport pathlib\np = pathlib.Path('{path}')\nlines = p.read_text().splitlines(True)\nlines.insert({line}, '''{text_esc}\\n''')\np.write_text(''.join(lines))\nprint('Inserted at line {line}')\n\""
        )
        output = f"Inserted at line {line} in {path}"
    else:
        output = f"Unknown editor command: {command}"
    return [{"type": "text", "text": output}]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch_tool(tool_name: str, tool_input: dict[str, Any]) -> list[dict[str, Any]]:
    """Route a tool call to the appropriate handler."""
    if tool_name == "computer":
        action = tool_input.pop("action", "")
        return execute_computer_tool(action, **tool_input)
    elif tool_name == "bash":
        return execute_bash_tool(tool_input.get("command", ""))
    elif tool_name == "str_replace_based_edit_tool":
        cmd = tool_input.pop("command", "")
        return execute_text_editor_tool(cmd, **tool_input)
    return [{"type": "text", "text": f"Unknown tool: {tool_name}"}]
