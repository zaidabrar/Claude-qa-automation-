from __future__ import annotations

from importlib import resources


def load_prompt(name: str, **values: str) -> str:
    text = resources.files(__package__).joinpath(f"{name}.md").read_text()
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text
