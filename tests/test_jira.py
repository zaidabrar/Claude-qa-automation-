import json

import httpx2 as httpx

from qa_harness.config import JiraConfig
from qa_harness.integrations.jira import JiraClient, adf_to_text, extract_acceptance_criteria, text_to_adf

ADF = {
    "type": "doc",
    "version": 1,
    "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Users can log in."}]},
        {"type": "heading", "attrs": {"level": 3}, "content": [{"type": "text", "text": "Acceptance Criteria"}]},
        {
            "type": "orderedList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "Wrong password shows error"}]}
                    ],
                },
                {
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Lockout after 5 tries"}]}],
                },
            ],
        },
    ],
}


def test_adf_to_text_and_acceptance_criteria():
    text = adf_to_text(ADF)
    assert "Users can log in." in text
    ac = extract_acceptance_criteria(text)
    assert "1. Wrong password shows error" in ac and "2. Lockout after 5 tries" in ac


def test_text_to_adf_round_trips_structure():
    doc = text_to_adf("## Title\n- one with [link](https://x.io)\n- **two**\n\n```\ncode\n```\nplain")
    types = [n["type"] for n in doc["content"]]
    assert types == ["heading", "bulletList", "codeBlock", "paragraph"]
    link = doc["content"][1]["content"][0]["content"][0]["content"][1]
    assert link["marks"][0]["attrs"]["href"] == "https://x.io"
    assert "one with" in adf_to_text(doc)


def test_client_get_ticket_search_and_transition():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("/issue/APP-1") and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "key": "APP-1",
                    "fields": {
                        "summary": "Login errors",
                        "description": ADF,
                        "issuetype": {"name": "Story"},
                        "status": {"name": "Ready for QA"},
                        "labels": ["qa-ai"],
                        "components": [{"name": "auth"}],
                        "comment": {"comments": [{"author": {"displayName": "PM"}, "body": "Copy TBD"}]},
                        "issuelinks": [],
                    },
                },
            )
        if path.endswith("/search/jql"):
            assert json.loads(request.content)["jql"] == "project = APP"
            return httpx.Response(200, json={"issues": [{"key": "APP-1"}, {"key": "APP-2"}]})
        if path.endswith("/transitions") and request.method == "GET":
            return httpx.Response(
                200, json={"transitions": [{"id": "31", "name": "Pass", "to": {"name": "QA Passed"}}]}
            )
        if path.endswith("/transitions") and request.method == "POST":
            assert json.loads(request.content) == {"transition": {"id": "31"}}
            return httpx.Response(204)
        return httpx.Response(404, text="nope")

    client = JiraClient(
        JiraConfig(base_url="https://x.atlassian.net"), "e", "t", transport=httpx.MockTransport(handler)
    )
    ticket = client.get_ticket("APP-1")
    assert ticket.summary == "Login errors" and ticket.components == ["auth"]
    assert "Lockout" in ticket.acceptance_criteria
    assert ticket.comments == ["PM: Copy TBD"]
    assert ticket.url == "https://x.atlassian.net/browse/APP-1"
    assert client.search_keys("project = APP") == ["APP-1", "APP-2"]
    assert client.transition("APP-1", "qa passed") is True
