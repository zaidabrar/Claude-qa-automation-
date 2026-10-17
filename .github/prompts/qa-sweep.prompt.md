---
mode: agent
description: Work through every Jira ticket waiting for QA automation
---
Call `qa_ready_tickets`. For each ticket in priority order, run the full `qa-engineer` workflow from `.github/agents/qa-engineer.agent.md`, with one branch and one PR per ticket. If a ticket can't be automated (for example, no mobile UI is involved), say why and move on. Finish with one table: ticket, status, scenarios passed/failed, bugs filed, PR link.
