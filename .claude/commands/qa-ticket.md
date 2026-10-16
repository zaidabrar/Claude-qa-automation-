---
description: Run the autonomous QA harness for a Jira ticket and summarize the outcome
argument-hint: <JIRA-KEY> [autonomous|supervised|dry_run]
---

Run the QA harness for ticket `$1` (mode: `${2:-dry_run}`):

1. Run `qa-harness doctor` and stop if a required credential is missing. Say exactly which one.
2. Run `qa-harness --mode ${2:-dry_run} run $1`.
3. Read the newest `.qa_runs/$1-*/report.md` and `state.json`, then summarize the status, the device matrix, any bugs filed, the PR link, and the LLM cost.
4. If the status is `needs_human` or `failed`, read the triage verdicts in `state.json` and the evidence under `artifacts/`. Explain what a person needs to decide, quoting the evidence.
