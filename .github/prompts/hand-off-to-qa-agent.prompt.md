---
mode: agent
description: Hand a Jira ticket to the autonomous QA pipeline and report back
---
Start the autonomous QA pipeline for `${input:ticket:Jira key}` with the `start_autonomous_run` tool, in mode `${input:mode:dry_run or autonomous}`. Check `get_run_status` periodically until the status is no longer `running`. Then summarise the status, the device matrix, any bugs filed, the PR link, and what needs a human decision.
