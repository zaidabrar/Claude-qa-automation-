"""qa-harness command line. The same operations GitHub Copilot calls through MCP, for humans and CI.

qa-harness mcp                                  # MCP server for Copilot (see .vscode/mcp.json)
qa-harness doctor                               # check config, credentials, JDK/Maven, connectivity
qa-harness ready                                # Jira tickets waiting for QA automation
qa-harness ticket APP-123                       # print a ticket as markdown
qa-harness discover [feature ...]               # compile + Cucumber dry run
qa-harness run APP-123 -s <feature:line> ...    # run scenarios on Sauce Labs  [--device X] [--run-id R]
qa-harness evidence RUN_ID SCENARIO DEVICE      # triage evidence for one failure
qa-harness report RUN_ID|APP-123                # markdown report (PR description)
qa-harness publish RUN_ID                       # report to Jira (comment, transition, label)
qa-harness pr RUN_ID                            # commit tests, push, open draft PR
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

from . import ops
from .config import AutonomyMode, Settings, load_settings
from .integrations.jira import JiraClient
from .services import Services
from .state import RunStore


def _resolve_run(settings: Settings, ref: str) -> str:
    if (settings.runs_root / ref / "run.json").exists():
        return ref
    latest = RunStore.latest_id(settings.runs_root, ref)
    if not latest:
        raise SystemExit(f"No run {ref!r}")
    return latest


def cmd_doctor(args, settings: Settings) -> int:
    svc = Services.from_settings(settings)
    s = svc.secrets
    ok = True

    def check(name: str, passed: bool, hint: str = "", required: bool = True) -> None:
        nonlocal ok
        ok &= passed or not required
        mark = "✔" if passed else ("✖" if required else "–")
        print(f"{mark} {name}" + ("" if passed else f"  — {hint}"))

    check("Test project", (settings.tests_root / "pom.xml").is_file(), f"no pom.xml in {settings.tests_root}")
    check("Maven", shutil.which(settings.project.maven_cmd) is not None, "install Maven 3.9+")
    check("JDK", shutil.which("java") is not None, "install a JDK 17+")
    check("Device matrix", bool(settings.sauce.devices), "add sauce.devices to qa_harness.yaml")
    check("App under test", bool(settings.sauce.android_app or settings.sauce.ios_app), "set sauce.*_app")
    check("Sauce Labs credentials", bool(s.sauce_username and s.sauce_access_key), "SAUCE_USERNAME + SAUCE_ACCESS_KEY")
    check("Jira", svc.jira is not None, "jira.base_url + JIRA_EMAIL + JIRA_API_TOKEN")
    check("Git repository", svc.git is not None, "repo_root is not a git checkout")
    check("GitHub token (optional)", bool(s.github_token), "without it, open_pull_request returns a link", False)

    if svc.jira:
        try:
            JiraClient(settings.jira, s.jira_email, s.jira_token)._req("GET", "/myself")
            check("Jira reachable", True)
        except Exception as exc:
            check("Jira reachable", False, str(exc)[:200])
    if svc.sauce:
        try:
            r = svc.sauce.http.get("/v1/storage/files", params={"per_page": 1})
            check("Sauce Labs reachable", r.status_code == 200, f"HTTP {r.status_code}")
        except Exception as exc:
            check("Sauce Labs reachable", False, str(exc)[:200])
    print(f"\nMode: {settings.autonomy.mode.value}. No LLM key needed: GitHub Copilot is the agent.")
    return 0 if ok else 1


def cmd_mcp(args, settings: Settings) -> int:
    from .mcp_server import serve

    serve(settings)
    return 0


def _print(text: str) -> int:
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="qa-harness", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--config", help="path to qa_harness.yaml")
    p.add_argument("--mode", choices=[m.value for m in AutonomyMode], help="override autonomy.mode")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("mcp", help="serve the QA tools over MCP (stdio) for GitHub Copilot").set_defaults(fn=cmd_mcp)
    sub.add_parser("doctor", help="check configuration and connectivity").set_defaults(fn=cmd_doctor)

    r = sub.add_parser("ready", help="Jira tickets waiting for QA automation")
    r.add_argument("--limit", type=int, default=20)
    r.set_defaults(fn=lambda a, s: _print(ops.ready_tickets(Services.from_settings(s), a.limit)))

    t = sub.add_parser("ticket", help="print a Jira ticket as markdown")
    t.add_argument("key")
    t.set_defaults(fn=lambda a, s: _print(ops.get_ticket(Services.from_settings(s), a.key)))

    d = sub.add_parser("discover", help="compile + Cucumber dry run")
    d.add_argument("features", nargs="*")
    d.set_defaults(fn=lambda a, s: _print(ops.discover(Services.from_settings(s), a.features)))

    run = sub.add_parser("run", help="run scenarios on Sauce Labs")
    run.add_argument("ticket")
    run.add_argument("-s", "--scenario", action="append", required=True, help="feature:line (repeatable)")
    run.add_argument("--device", action="append", help="device name (repeatable; default all)")
    run.add_argument("--run-id", help="add an attempt to an existing run")

    def cmd_run(a, s):
        qa_run, text = ops.run_scenarios(Services.from_settings(s), a.ticket, a.scenario, a.device, a.run_id)
        print(text)
        return 0 if qa_run.status() == "passed" else 2

    run.set_defaults(fn=cmd_run)

    e = sub.add_parser("evidence", help="triage evidence for one failure")
    e.add_argument("run_id")
    e.add_argument("scenario")
    e.add_argument("device")
    e.set_defaults(
        fn=lambda a, s: _print(ops.failure_evidence(Services.from_settings(s), a.run_id, a.scenario, a.device))
    )

    rp = sub.add_parser("report", help="markdown report for a run id or ticket key")
    rp.add_argument("ref")
    rp.set_defaults(fn=lambda a, s: _print(ops.pr_description(Services.from_settings(s), _resolve_run(s, a.ref))))

    pb = sub.add_parser("publish", help="report a run to Jira")
    pb.add_argument("ref")
    pb.set_defaults(fn=lambda a, s: _print(ops.publish_to_jira(Services.from_settings(s), _resolve_run(s, a.ref))))

    pr = sub.add_parser("pr", help="commit test changes, push, open a draft PR")
    pr.add_argument("ref")
    pr.add_argument("--title")
    pr.set_defaults(
        fn=lambda a, s: _print(ops.open_pull_request(Services.from_settings(s), _resolve_run(s, a.ref), a.title))
    )

    args = p.parse_args(argv)
    settings = load_settings(args.config or os.environ.get("QA_HARNESS_CONFIG"))
    if args.mode:
        settings.autonomy.mode = AutonomyMode(args.mode)
    try:
        return args.fn(args, settings)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
