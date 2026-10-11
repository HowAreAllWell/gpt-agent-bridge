"""Small synthetic canonical cognition; only write inside caller-owned test roots."""
import json
from pathlib import Path

STATE_TEXT = "# Synthetic current position\nNext: verify fixture routing.\n"
MEMORY_TEXT = (
    "# Synthetic memory\n"
    "There is no standing authority outside the currently authorized project/work.\n"
    "Narrower task restrictions apply to Ordinary Agents; a service restart needs task authority.\n"
    "Cause: preserve fixture memory independently from replaceable state.\n"
)


def write_canonical_cognition(root):
    root = Path(root)
    manifest = {"rules": ["AGENTS.md"], "current_state": ".principal/state.md",
                "memory": ".principal/memory.md"}
    contents = {"AGENTS.md": "# Synthetic rules\nUse only the authorized disposable checkout.\n",
                manifest["current_state"]: STATE_TEXT, manifest["memory"]: MEMORY_TEXT}
    for relative, text in contents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / ".principal/project.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
