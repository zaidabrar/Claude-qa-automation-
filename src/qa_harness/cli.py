"""qa-harness command line.

qa-harness run APP-123                 # full pipeline for one ticket
qa-harness run APP-123 --mode dry_run  # everything local; no Jira/GitHub writes
qa-harness watch                       # autonomous: poll Jira for ready tickets forever
qa-harness resume APP-123-20261016T...  # continue a crashed / budget-stopped run
qa-harness plan APP-123                # print the test plan only
qa-harness doctor                      # verify configuration and credentials
qa-harness mcp                         # MCP server for GitHub Copilot agent mode
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
import time
from pathlib import Path

from .config import AutonomyMode, Secrets, Settings, load_settings
from .framework import CucumberMaven
from .integrations.github import Git, GitHubClient
from .integrations.jira import JiraClient
from .integrations.saucelabs import SauceClient
from .llm import LLM
from .models import Ticket
from .pipeline import Deps, Pipeline, new_state
from .stages.executor import SauceExecutor
from .stages.reporter import render_report
from .state import Guard, RunState, RunStore

log = logging.getLogger("qa_harness")

EXIT = {"passed": 0, "product_bug": 2, "needs_human": 3, "failed": 4, "error": 1}


def build_framework(settings: Settings) -> CucumberMaven:
    return CucumberMaven(
        settings.tests_root, settings.repo_root, settings.project.maven_cmd, settings.project.maven_args
    )


def build_deps(settings: Settings, ticket_file: str | None = None) -> Deps:
    secrets = Secrets.from_env(settings.notify)
    jira = None
    if settings.jira.base_url and secrets.jira_email and secrets.jira_token:
        jira = JiraClient(settings.jira, secrets.jira_email, secrets.jira_token)
    sauce = None
    if secrets.sauce_username and secrets.sauce_access_key:
        sauce = SauceClient(settings.sauce, secrets.sauce_username, secrets.sauce_access_key)

    git = Git(settings.repo_root) if (settings.repo_root / ".git").exists() else None
    github = None
    if git and secrets.github_token:
        repo = settings.github.repo or git.remote_repo()
        if repo:
            github = GitHubClient(settings.github, secrets.github_token, repo)

    if ticket_file:
        data = json.loads(Path(ticket_file).read_text())

        def load_ticket(_key: str) -> Ticket:
            return Ticket.model_validate(data)
    elif jira:
        load_ticket = jira.get_ticket
    else:
        raise SystemExit("Jira is not configured (jira.base_url, JIRA_EMAIL, JIRA_API_TOKEN); pass --ticket-file")

    framework = build_framework(settings)
    executor = SauceExecutor(settings, secrets, sauce, framework, settings.runs_root / "_artifacts")
    return Deps(
        settings=settings,
        secrets=secrets,
        llm=LLM(settings.llm),
        framework=framework,
        executor=executor,
        load_ticket=load_ticket,
        jira=jira,
        git=git,
        github=github,
    )


def _run_one(settings: Settings, key: str, ticket_file: str | None) -> RunState:
    deps = build_deps(settings, ticket_file)
    state = new_state(key)
    store = RunStore(settings.runs_root, state.run_id)
    deps.executor.artifacts_root = store.artifacts
    print(f"▶ {key}: run {state.run_id} ({settings.autonomy.mode.value}) → {store.dir}", file=sys.stderr)
    return Pipeline(deps, store, state, Guard(settings.autonomy.mode, store)).run()


def cmd_run(args, settings: Settings) -> int:
    try:
        state = _run_one(settings, args.ticket, args.ticket_file)
    except Exception as exc:
        print(f"✖ {args.ticket}: {exc}", file=sys.stderr)
        return EXIT["error"]
    print(render_report(state))
    return EXIT.get(state.status, 1)


def cmd_resume(args, settings: Settings) -> int:
    store = RunStore(settings.runs_root, args.run_id)
    state = store.load()
    if state.status == "error":
        state.status, state.error = "running", None
    deps = build_deps(settings, args.ticket_file)
    deps.executor.artifacts_root = store.artifacts
    state = Pipeline(deps, store, state, Guard(settings.autonomy.mode, store)).run()
    print(render_report(state))
    return EXIT.get(state.status, 1)


def cmd_plan(args, settings: Settings) -> int:
    from .stages.planner import build_plan

    deps = build_deps(settings, args.ticket_file)
    plan = build_plan(deps.llm, deps.load_ticket(args.ticket), settings)
    print(plan.model_dump_json(indent=2) if args.json else _plan_markdown(plan))
    print(f"\n(cost ${deps.llm.cost.spent_usd:.3f})", file=sys.stderr)
    return 0


def _plan_markdown(plan) -> str:
    out = [f"# Test plan: {plan.ticket_key}", plan.feature_summary, "", "## Risks", *[f"- {r}" for r in plan.risks]]
    for c in plan.test_cases:
        out += ["", f"## {c.id} {c.title}  [{c.kind.value}, P{c.priority}, {'/'.join(p.value for p in c.platforms)}]"]
        out += [f"Pre: {p}" for p in c.preconditions]
        out += [f"{i}. {s.action} → {s.expected}" for i, s in enumerate(c.steps, 1)]
        if not c.automatable:
            out.append(f"_Manual: {c.automation_notes}_")
    if plan.ambiguities:
        out += ["", "## Ambiguities", *[f"- {a}" for a in plan.ambiguities]]
    return "\n".join(out)


def cmd_report(args, settings: Settings) -> int:
    print(render_report(RunStore(settings.runs_root, args.run_id).load()))
    return 0


def _exclude_done(jql: str, label: str) -> str:
    parts = re.split(r"\s+ORDER\s+BY\s+", jql, maxsplit=1, flags=re.I)
    where = f'({parts[0]}) AND (labels IS EMPTY OR labels != "{label}")'
    return where + (f" ORDER BY {parts[1]}" if len(parts) > 1 else "")


def cmd_watch(args, settings: Settings) -> int:
    deps = build_deps(settings)
    if not deps.jira:
        raise SystemExit("watch requires Jira credentials")
    seen_path = settings.runs_root / "processed.json"
    seen: set[str] = set(json.loads(seen_path.read_text())) if seen_path.exists() else set()
    jql = _exclude_done(settings.jira.ready_jql, settings.jira.done_label)
    print(f"Watching Jira every {args.interval}s: {jql}", file=sys.stderr)
    while True:
        try:
            keys = [k for k in deps.jira.search_keys(jql, limit=args.batch) if k not in seen]
        except Exception as exc:
            log.error("Jira poll failed: %s", exc)
            keys = []
        for key in keys:
            try:
                state = _run_one(settings, key, None)
                print(f"✔ {key}: {state.status} {state.pr_url or ''}", file=sys.stderr)
            except Exception as exc:  # one bad ticket must not stop the daemon
                print(f"✖ {key}: {exc}", file=sys.stderr)
            seen.add(key)
            seen_path.parent.mkdir(parents=True, exist_ok=True)
            seen_path.write_text(json.dumps(sorted(seen)))
        if args.once:
            return 0
        time.sleep(args.interval)


def cmd_doctor(args, settings: Settings) -> int:
    secrets = Secrets.from_env(settings.notify)
    ok = True

    def check(name: str, passed: bool, hint: str = "") -> None:
        nonlocal ok
        ok &= passed
        print(f"{'✔' if passed else '✖'} {name}" + ("" if passed else f"  — {hint}"))

    import os

    check(
        "Anthropic credentials",
        bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
        "set ANTHROPIC_API_KEY (or log in with `ant auth login`)",
    )
    check(
        "Jira config",
        bool(settings.jira.base_url and secrets.jira_email and secrets.jira_token),
        "jira.base_url + JIRA_EMAIL + JIRA_API_TOKEN",
    )
    check(
        "Sauce Labs credentials",
        bool(secrets.sauce_username and secrets.sauce_access_key),
        "SAUCE_USERNAME + SAUCE_ACCESS_KEY",
    )
    check("Device matrix", bool(settings.sauce.devices), "add sauce.devices to qa_harness.yaml")
    check(
        "App under test",
        bool(settings.sauce.android_app or settings.sauce.ios_app),
        "set sauce.android_app and/or sauce.ios_app",
    )
    check("GitHub token", bool(secrets.github_token), "GITHUB_TOKEN (contents + pull_requests write)")
    check("Test project", (settings.tests_root / "pom.xml").is_file(), f"no pom.xml in {settings.tests_root}")
    check("Maven", shutil.which(settings.project.maven_cmd) is not None, "install Maven 3.9+ and a JDK 17+")
    check("JDK", shutil.which("java") is not None, "install a JDK 17+")
    check("Git repository", (settings.repo_root / ".git").exists(), "repo_root is not a git checkout")

    if settings.jira.base_url and secrets.jira_email and secrets.jira_token:
        try:
            JiraClient(settings.jira, secrets.jira_email, secrets.jira_token)._req("GET", "/myself")
            check("Jira reachable", True)
        except Exception as exc:
            check("Jira reachable", False, str(exc)[:200])
    if secrets.sauce_username and secrets.sauce_access_key:
        try:
            r = SauceClient(settings.sauce, secrets.sauce_username, secrets.sauce_access_key).http.get(
                "/v1/storage/files", params={"per_page": 1}
            )
            check("Sauce Labs reachable", r.status_code == 200, f"HTTP {r.status_code}")
        except Exception as exc:
            check("Sauce Labs reachable", False, str(exc)[:200])
    print(
        f"\nAutonomy mode: {settings.autonomy.mode.value} · model {settings.llm.model} "
        f"(effort {settings.llm.effort}) · budget ${settings.llm.max_usd_per_run}/run"
    )
    return 0 if ok else 1


def cmd_mcp(args, settings: Settings) -> int:
    from .mcp_server import serve

    serve(settings)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="qa-harness", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--config", help="path to qa_harness.yaml")
    p.add_argument("--mode", choices=[m.value for m in AutonomyMode], help="override autonomy.mode")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run the full pipeline for one ticket")
    r.add_argument("ticket")
    r.add_argument("--ticket-file", help="load the ticket from JSON instead of Jira")
    r.set_defaults(fn=cmd_run)

    rs = sub.add_parser("resume", help="resume a previous run from its checkpoint")
    rs.add_argument("run_id")
    rs.add_argument("--ticket-file")
    rs.set_defaults(fn=cmd_resume)

    pl = sub.add_parser("plan", help="generate and print the test plan only")
    pl.add_argument("ticket")
    pl.add_argument("--ticket-file")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(fn=cmd_plan)

    rp = sub.add_parser("report", help="print the report for a run")
    rp.add_argument("run_id")
    rp.set_defaults(fn=cmd_report)

    w = sub.add_parser("watch", help="poll Jira and process ready tickets autonomously")
    w.add_argument("--interval", type=int, default=300)
    w.add_argument("--batch", type=int, default=5)
    w.add_argument("--once", action="store_true", help="process one poll then exit (for cron/CI)")
    w.set_defaults(fn=cmd_watch)

    d = sub.add_parser("doctor", help="check configuration and connectivity")
    d.set_defaults(fn=cmd_doctor)

    m = sub.add_parser("mcp", help="serve harness tools over MCP (stdio) for GitHub Copilot agent mode")
    m.set_defaults(fn=cmd_mcp)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    settings = load_settings(args.config)
    if args.mode:
        settings.autonomy.mode = AutonomyMode(args.mode)
    return args.fn(args, settings)


if __name__ == "__main__":
    sys.exit(main())
