"""Client-side tools exposed to the agent, with input validation and path sandboxing.

Reads are allowed anywhere in the repository except secrets and VCS internals.
Writes are confined to the configured tests directory, so a generation or
self-healing agent can never touch application code, CI config, or the harness itself.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from .framework import TestFramework

MAX_READ_BYTES = 200_000
MAX_OUTPUT_CHARS = 30_000

DENY_READ = [".git/*", ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.keystore", "*.jks", "*secrets*"]
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache", "target", ".idea"}
WRITABLE_SUFFIXES = {".java", ".feature", ".properties", ".json", ".csv", ".md", ".txt"}


class ToolFailure(Exception):
    """Raised by a tool to return an ``is_error`` result to the model."""


@dataclass
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    fn: Callable[[Any], str]

    def definition(self) -> dict[str, Any]:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
            # Streamed tool input arrives unvalidated; execute() validates it.
            "eager_input_streaming": True,
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def add(self, name: str, description: str, input_model: type[BaseModel]):
        def decorator(fn: Callable[[Any], str]) -> Callable[[Any], str]:
            self._tools[name] = Tool(name, description, input_model, fn)
            return fn

        return decorator

    def names(self) -> list[str]:
        return list(self._tools)

    def definitions(self) -> list[dict[str, Any]]:
        # Deterministic order keeps the prompt-cache prefix stable.
        return [self._tools[n].definition() for n in sorted(self._tools)]

    def execute(self, name: str, raw_input: dict[str, Any]) -> tuple[str, bool]:
        tool = self._tools.get(name)
        if tool is None:
            return f"Unknown tool {name!r}. Available: {', '.join(self.names())}", True
        try:
            parsed = tool.input_model.model_validate(raw_input)
        except ValidationError as exc:
            return f"Invalid input for {name}: {exc}", True
        try:
            out = tool.fn(parsed)
        except ToolFailure as exc:
            return str(exc), True
        except Exception as exc:  # surfaced to the model so it can adapt
            return f"{type(exc).__name__}: {exc}", True
        if len(out) > MAX_OUTPUT_CHARS:
            out = out[:MAX_OUTPUT_CHARS] + f"\n... [truncated {len(out) - MAX_OUTPUT_CHARS} chars]"
        return out, False


# ---------------------------------------------------------------------- inputs


class ListDirInput(BaseModel):
    path: str = Field(".", description="Directory relative to the repo root.")
    depth: int = Field(2, ge=1, le=6)


class ReadFileInput(BaseModel):
    path: str = Field(description="File path relative to the repo root.")
    start_line: int = Field(1, ge=1)
    max_lines: int = Field(800, ge=1, le=4000)


class WriteFileInput(BaseModel):
    path: str = Field(description="File path relative to the repo root; must be inside the tests directory.")
    content: str


class EditFileInput(BaseModel):
    path: str
    old_str: str = Field(description="Exact text to replace; must occur exactly once.")
    new_str: str


class SearchInput(BaseModel):
    pattern: str = Field(description="Python regular expression.")
    path: str = Field(".", description="Directory to search, relative to the repo root.")
    glob: str = Field("*.java", description="Filename glob filter, e.g. *.java or *.feature.")
    max_results: int = Field(80, ge=1, le=500)


class DryRunInput(BaseModel):
    features: list[str] = Field(
        default_factory=list,
        description="Feature files (repo-relative) to dry-run. Empty = the whole suite.",
    )


class EmptyInput(BaseModel):
    pass


# ---------------------------------------------------------------------- workspace


class Workspace:
    def __init__(self, repo_root: Path, writable_dir: Path):
        self.root = repo_root.resolve()
        self.writable = writable_dir.resolve()
        self.written: set[str] = set()

    def resolve(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise ToolFailure(f"Path {rel!r} escapes the repository")
        return p

    def rel(self, p: Path) -> str:
        return str(p.relative_to(self.root)) or "."

    def check_readable(self, p: Path) -> None:
        rel = self.rel(p)
        if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(p.name, pat) for pat in DENY_READ):
            raise ToolFailure(f"Reading {rel} is not permitted")

    def check_writable(self, p: Path) -> None:
        if p != self.writable and self.writable not in p.parents:
            raise ToolFailure(f"Writes are only allowed under {self.rel(self.writable)}/")
        if p.suffix == ".xml" or p.name in {"pom.xml", "build.gradle", "testng.xml"}:
            raise ToolFailure("Build files are not editable by the agent; dependency changes need a human")
        if p.suffix not in WRITABLE_SUFFIXES:
            raise ToolFailure(f"Refusing to write file type {p.suffix!r}")


def build_workspace_tools(ws: Workspace, framework: TestFramework, *, allow_write: bool = True) -> ToolRegistry:
    reg = ToolRegistry()

    @reg.add("list_dir", "List files and directories (tree view) under a path.", ListDirInput)
    def list_dir(inp: ListDirInput) -> str:
        base = ws.resolve(inp.path)
        if not base.is_dir():
            raise ToolFailure(f"{inp.path} is not a directory")
        lines: list[str] = []

        def walk(d: Path, level: int) -> None:
            for child in sorted(d.iterdir(), key=lambda c: (c.is_file(), c.name)):
                if child.name in SKIP_DIRS:
                    continue
                lines.append("  " * level + child.name + ("/" if child.is_dir() else ""))
                if child.is_dir() and level + 1 < inp.depth:
                    walk(child, level + 1)
                if len(lines) > 600:
                    return

        walk(base, 0)
        return "\n".join(lines) or "(empty)"

    @reg.add("read_file", "Read a text file with line numbers.", ReadFileInput)
    def read_file(inp: ReadFileInput) -> str:
        p = ws.resolve(inp.path)
        ws.check_readable(p)
        if not p.is_file():
            raise ToolFailure(f"{inp.path} does not exist")
        if p.stat().st_size > MAX_READ_BYTES:
            raise ToolFailure(f"{inp.path} is too large; use search instead")
        all_lines = p.read_text(errors="replace").splitlines()
        chunk = all_lines[inp.start_line - 1 : inp.start_line - 1 + inp.max_lines]
        body = "\n".join(f"{i:5d}  {line}" for i, line in enumerate(chunk, start=inp.start_line))
        more = len(all_lines) - (inp.start_line - 1 + len(chunk))
        return body + (f"\n... {more} more lines" if more > 0 else "")

    @reg.add("search", "Regex search across files. Returns path:line: text.", SearchInput)
    def search(inp: SearchInput) -> str:
        base = ws.resolve(inp.path)
        try:
            rx = re.compile(inp.pattern)
        except re.error as exc:
            raise ToolFailure(f"Bad regex: {exc}") from exc
        hits: list[str] = []
        for p in sorted(base.rglob(inp.glob)):
            if any(part in SKIP_DIRS for part in p.parts) or not p.is_file():
                continue
            try:
                ws.check_readable(p)
                if p.stat().st_size > MAX_READ_BYTES:
                    continue
                for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                    if rx.search(line):
                        hits.append(f"{ws.rel(p)}:{n}: {line.strip()[:200]}")
                        if len(hits) >= inp.max_results:
                            return "\n".join(hits) + "\n... (more results truncated)"
            except ToolFailure:
                continue
        return "\n".join(hits) or "No matches"

    @reg.add(
        "compile",
        "Compile the test suite (mvn test-compile). Returns compiler errors with file:line.",
        EmptyInput,
    )
    def compile_(_: EmptyInput) -> str:
        ok, out = framework.compile()
        return ("BUILD SUCCESS" if ok else "BUILD FAILED") + "\n" + out

    @reg.add(
        "cucumber_dry_run",
        "Compile, then run Cucumber in dry-run mode: lists every scenario id (feature:line) and reports "
        "undefined or ambiguous steps. No device is used.",
        DryRunInput,
    )
    def dry_run(inp: DryRunInput) -> str:
        features = []
        for f in inp.features:
            rel = framework.to_project_path(f)
            if rel is None:
                raise ToolFailure(f"{f} is not inside the test project")
            features.append(rel)
        return framework.discover(features or None).summary()

    if not allow_write:
        return reg

    @reg.add(
        "write_file",
        "Create or overwrite a file. Only allowed inside the tests directory.",
        WriteFileInput,
    )
    def write_file(inp: WriteFileInput) -> str:
        p = ws.resolve(inp.path)
        ws.check_writable(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(inp.content)
        ws.written.add(ws.rel(p))
        return f"Wrote {ws.rel(p)} ({len(inp.content.splitlines())} lines)"

    @reg.add(
        "edit_file",
        "Replace one exact occurrence of old_str with new_str. Only inside the tests directory.",
        EditFileInput,
    )
    def edit_file(inp: EditFileInput) -> str:
        p = ws.resolve(inp.path)
        ws.check_writable(p)
        if not p.is_file():
            raise ToolFailure(f"{inp.path} does not exist")
        text = p.read_text()
        count = text.count(inp.old_str)
        if count != 1:
            raise ToolFailure(f"old_str occurs {count} times in {inp.path}; it must occur exactly once")
        p.write_text(text.replace(inp.old_str, inp.new_str, 1))
        ws.written.add(ws.rel(p))
        return f"Edited {ws.rel(p)}"

    return reg
