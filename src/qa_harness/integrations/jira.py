"""Jira Cloud REST v3 client: read tickets, comment, transition, file bugs."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx2 as httpx

from ..config import JiraConfig
from ..models import Ticket

AC_HEADING = re.compile(r"^\s*(acceptance criteria|ac|definition of done)\s*:?\s*$", re.I)


class JiraClient:
    def __init__(self, cfg: JiraConfig, email: str, token: str, transport: httpx.BaseTransport | None = None):
        if not cfg.base_url:
            raise ValueError("jira.base_url is not configured")
        self.cfg = cfg
        self.base = cfg.base_url.rstrip("/")
        self.http = httpx.Client(
            base_url=f"{self.base}/rest/api/3",
            auth=(email, token),
            headers={"Accept": "application/json"},
            timeout=30.0,
            transport=transport,
        )

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        r = self.http.request(method, path, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"Jira {method} {path} -> {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else None

    # ------------------------------------------------------------------ read

    def get_ticket(self, key: str) -> Ticket:
        data = self._req("GET", f"/issue/{key}", params={"expand": "renderedFields"})
        f = data["fields"]
        description = adf_to_text(f.get("description"))
        ac = ""
        if self.cfg.acceptance_criteria_field:
            raw = f.get(self.cfg.acceptance_criteria_field)
            ac = adf_to_text(raw) if isinstance(raw, dict) else (raw or "")
        if not ac:
            ac = extract_acceptance_criteria(description)
        comments = [
            f"{c.get('author', {}).get('displayName', '?')}: {adf_to_text(c.get('body'))}"
            for c in (f.get("comment") or {}).get("comments", [])[-15:]
        ]
        links = []
        for link in f.get("issuelinks", []):
            other = link.get("outwardIssue") or link.get("inwardIssue") or {}
            if other:
                links.append(f"{link['type']['name']}: {other['key']} {other['fields'].get('summary', '')}")
        return Ticket(
            key=data["key"],
            summary=f.get("summary", ""),
            description=description,
            issue_type=(f.get("issuetype") or {}).get("name", ""),
            status=(f.get("status") or {}).get("name", ""),
            priority=(f.get("priority") or {}).get("name", ""),
            labels=f.get("labels", []),
            components=[c["name"] for c in f.get("components", [])],
            acceptance_criteria=ac,
            comments=comments,
            linked_issues=links,
            url=f"{self.base}/browse/{data['key']}",
        )

    def search_keys(self, jql: str, limit: int = 20) -> list[str]:
        data = self._req("POST", "/search/jql", json={"jql": jql, "fields": ["key"], "maxResults": limit})
        return [i["key"] for i in data.get("issues", [])]

    # ------------------------------------------------------------------ write

    def comment(self, key: str, markdown: str) -> None:
        self._req("POST", f"/issue/{key}/comment", json={"body": text_to_adf(markdown)})

    def transition(self, key: str, name: str) -> bool:
        data = self._req("GET", f"/issue/{key}/transitions")
        for t in data.get("transitions", []):
            if t["name"].lower() == name.lower() or t["to"]["name"].lower() == name.lower():
                self._req("POST", f"/issue/{key}/transitions", json={"transition": {"id": t["id"]}})
                return True
        return False

    def add_label(self, key: str, label: str) -> None:
        self._req("PUT", f"/issue/{key}", json={"update": {"labels": [{"add": label}]}})

    def create_bug(self, project: str, summary: str, markdown: str, labels: list[str], priority: str | None) -> str:
        fields: dict[str, Any] = {
            "project": {"key": project},
            "issuetype": {"name": self.cfg.bug_issue_type},
            "summary": summary[:250],
            "description": text_to_adf(markdown),
            "labels": labels,
        }
        if priority:
            fields["priority"] = {"name": priority}
        try:
            data = self._req("POST", "/issue", json={"fields": fields})
        except RuntimeError:
            if not priority:
                raise
            fields.pop("priority")  # schemes without a priority field reject it
            data = self._req("POST", "/issue", json={"fields": fields})
        return data["key"]

    def link(self, from_key: str, to_key: str, link_type: str = "Relates") -> None:
        self._req(
            "POST",
            "/issueLink",
            json={"type": {"name": link_type}, "inwardIssue": {"key": from_key}, "outwardIssue": {"key": to_key}},
        )

    def attach(self, key: str, path: Path) -> None:
        with path.open("rb") as fh:
            r = self.http.post(
                f"/issue/{key}/attachments",
                headers={"X-Atlassian-Token": "no-check"},
                files={"file": (path.name, fh)},
            )
        if r.status_code >= 400:
            raise RuntimeError(f"Jira attach -> {r.status_code}: {r.text[:300]}")


# ---------------------------------------------------------------------- ADF helpers


def adf_to_text(node: Any) -> str:
    """Flatten Atlassian Document Format to readable markdown-ish text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    out: list[str] = []

    def walk(n: dict[str, Any], prefix: str = "") -> None:
        t = n.get("type")
        children = n.get("content", [])
        if t == "text":
            text = n.get("text", "")
            for mark in n.get("marks", []):
                if mark.get("type") == "link":
                    text = f"[{text}]({mark.get('attrs', {}).get('href', '')})"
                elif mark.get("type") == "code":
                    text = f"`{text}`"
            out.append(text)
        elif t == "hardBreak":
            out.append("\n")
        elif t == "heading":
            out.append("\n" + "#" * n.get("attrs", {}).get("level", 2) + " ")
            for c in children:
                walk(c)
            out.append("\n")
        elif t in ("bulletList", "orderedList"):
            for i, item in enumerate(children, 1):
                marker = "- " if t == "bulletList" else f"{i}. "
                out.append("\n" + prefix + marker)
                for c in item.get("content", []):
                    if c.get("type") == "paragraph":
                        for cc in c.get("content", []):
                            walk(cc)
                    else:
                        walk(c, prefix + "  ")
            out.append("\n")
        elif t == "codeBlock":
            out.append("\n```\n")
            for c in children:
                walk(c)
            out.append("\n```\n")
        elif t == "paragraph":
            for c in children:
                walk(c)
            out.append("\n")
        elif t in ("mention", "emoji", "inlineCard"):
            attrs = n.get("attrs", {})
            out.append(attrs.get("text") or attrs.get("url") or attrs.get("shortName") or "")
        else:
            for c in children:
                walk(c, prefix)

    walk(node)
    return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip()


def extract_acceptance_criteria(description: str) -> str:
    lines = description.splitlines()
    for i, line in enumerate(lines):
        if AC_HEADING.match(line.lstrip("#* ").rstrip("*")):
            block = []
            for nxt in lines[i + 1 :]:
                if nxt.startswith("#") and block:
                    break
                block.append(nxt)
            return "\n".join(block).strip()
    return ""


def text_to_adf(markdown: str) -> dict[str, Any]:
    """Convert a small markdown subset (headings, bullets, code fences, links) to ADF."""
    content: list[dict[str, Any]] = []
    bullets: list[dict[str, Any]] = []
    code: list[str] | None = None

    def inline(text: str) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        pos = 0
        for m in re.finditer(r"\[([^\]]+)\]\((https?://[^)]+)\)|\*\*([^*]+)\*\*|`([^`]+)`", text):
            if m.start() > pos:
                nodes.append({"type": "text", "text": text[pos : m.start()]})
            if m.group(1):
                nodes.append(
                    {"type": "text", "text": m.group(1), "marks": [{"type": "link", "attrs": {"href": m.group(2)}}]}
                )
            elif m.group(3):
                nodes.append({"type": "text", "text": m.group(3), "marks": [{"type": "strong"}]})
            else:
                nodes.append({"type": "text", "text": m.group(4), "marks": [{"type": "code"}]})
            pos = m.end()
        if pos < len(text):
            nodes.append({"type": "text", "text": text[pos:]})
        return nodes

    def flush_bullets() -> None:
        if bullets:
            content.append({"type": "bulletList", "content": list(bullets)})
            bullets.clear()

    for line in markdown.splitlines():
        if code is not None:
            if line.strip().startswith("```"):
                content.append({"type": "codeBlock", "content": [{"type": "text", "text": "\n".join(code) or " "}]})
                code = None
            else:
                code.append(line)
            continue
        if line.strip().startswith("```"):
            flush_bullets()
            code = []
        elif m := re.match(r"^(#{1,6})\s+(.*)", line):
            flush_bullets()
            content.append({"type": "heading", "attrs": {"level": len(m.group(1))}, "content": inline(m.group(2))})
        elif m := re.match(r"^\s*[-*]\s+(.*)", line):
            bullets.append({"type": "listItem", "content": [{"type": "paragraph", "content": inline(m.group(1))}]})
        elif line.strip():
            flush_bullets()
            content.append({"type": "paragraph", "content": inline(line)})
        else:
            flush_bullets()
    if code is not None:
        content.append({"type": "codeBlock", "content": [{"type": "text", "text": "\n".join(code) or " "}]})
    flush_bullets()
    return {"type": "doc", "version": 1, "content": content or [{"type": "paragraph", "content": []}]}
