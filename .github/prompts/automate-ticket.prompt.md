---
mode: agent
description: Full autonomous QA flow for one Jira ticket (plan → scenarios → Sauce Labs → triage/fix → bugs → Jira → PR)
---
Act as the `qa-engineer` agent defined in `.github/agents/qa-engineer.agent.md` and follow its workflow and rules exactly for Jira ticket `${input:ticket:Jira key, e.g. APP-123}`. Work autonomously to the end: don't stop for confirmation between steps.
