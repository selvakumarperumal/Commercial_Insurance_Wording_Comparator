"""Load the prompts in src/config/prompts.yaml and fill in their placeholders."""

import os
import re
from functools import cache
from pathlib import Path

import yaml

DEFAULT_PROMPT_FILE = Path(__file__).resolve().parents[1] / "config" / "prompts.yaml"
PROMPT_FILE = Path(os.environ.get("PROMPT_FILE", DEFAULT_PROMPT_FILE))


@cache
def _load_prompts() -> dict[str, str]:
    """Read the `system_prompts` mapping from the prompt file once."""
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"Prompt file not found: {PROMPT_FILE}")

    prompts = yaml.safe_load(PROMPT_FILE.read_text()).get("system_prompts")
    if not prompts:
        raise ValueError(f"No 'system_prompts' found in {PROMPT_FILE}")

    return prompts


def render_prompt(name: str, **values: str) -> str:
    """Return prompt `name` with each `{key}` placeholder replaced by `values[key]`.

    Only the named placeholders are replaced, so literal JSON braces in the prompt stay as they are,
    which `str.format` and `ChatPromptTemplate` would reject.
    """
    template = _load_prompts().get(name)
    if not template:
        raise ValueError(f"Prompt '{name}' not found in {PROMPT_FILE}")

    missing = {key for key in re.findall(r"\{(\w+)\}", template) if key not in values}
    if missing:
        raise ValueError(f"Prompt '{name}' needs values for {sorted(missing)}")

    for key, value in values.items():
        template = template.replace(f"{{{key}}}", value)

    return template
