from pathlib import Path

from qa_harness.tools import Workspace, build_workspace_tools

from .fakes import FakeFramework

PAGE = "mobile-tests/src/test/java/com/qa/mobile/pages/HomePage.java"


def _tools(tmp_path: Path):
    (tmp_path / "mobile-tests" / "src").mkdir(parents=True)
    (tmp_path / "mobile-tests" / "pom.xml").write_text("<project/>")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "Main.java").write_text("class Main {}\n")
    (tmp_path / ".env").write_text("SECRET=1\n")
    ws = Workspace(tmp_path, tmp_path / "mobile-tests")
    return ws, build_workspace_tools(ws, FakeFramework(tmp_path / "mobile-tests", tmp_path))


def test_writes_are_confined_to_tests_dir(tmp_path):
    ws, tools = _tools(tmp_path)
    out, err = tools.execute("write_file", {"path": "app/Main.java", "content": "pwned"})
    assert err and "only allowed" in out
    assert (tmp_path / "app" / "Main.java").read_text() == "class Main {}\n"

    out, err = tools.execute("write_file", {"path": PAGE, "content": "class HomePage {}\n"})
    assert not err
    assert ws.written == {PAGE}


def test_build_files_and_unknown_types_are_refused(tmp_path):
    _, tools = _tools(tmp_path)
    out, err = tools.execute("write_file", {"path": "mobile-tests/pom.xml", "content": "<evil/>"})
    assert err and "Build files" in out
    out, err = tools.execute("write_file", {"path": "mobile-tests/run.sh", "content": "rm -rf /"})
    assert err and "file type" in out


def test_path_escape_and_secrets_are_blocked(tmp_path):
    _, tools = _tools(tmp_path)
    out, err = tools.execute("read_file", {"path": "../../etc/passwd"})
    assert err and "escapes" in out
    out, err = tools.execute("read_file", {"path": ".env"})
    assert err and "not permitted" in out


def test_invalid_input_is_reported_not_raised(tmp_path):
    _, tools = _tools(tmp_path)
    out, err = tools.execute("read_file", {"start_line": 1})
    assert err and "Invalid input" in out
    out, err = tools.execute("nope", {})
    assert err and "Unknown tool" in out


def test_edit_requires_unique_match(tmp_path):
    _, tools = _tools(tmp_path)
    tools.execute("write_file", {"path": PAGE, "content": "int x = 1;\nint x = 1;\n"})
    out, err = tools.execute("edit_file", {"path": PAGE, "old_str": "int x = 1;", "new_str": "y"})
    assert err and "2 times" in out
    out, err = tools.execute("edit_file", {"path": PAGE, "old_str": "int x = 1;\nint", "new_str": "int z = 2;\nint"})
    assert not err
    assert (tmp_path / PAGE).read_text() == "int z = 2;\nint x = 1;\n"


def test_search_and_list(tmp_path):
    _, tools = _tools(tmp_path)
    out, err = tools.execute("search", {"pattern": r"class Main", "path": "."})
    assert not err and "app/Main.java:1" in out
    out, err = tools.execute("list_dir", {"path": "."})
    assert "mobile-tests/" in out and "app/" in out


def test_dry_run_tool_reports_scenarios_and_compile_errors(tmp_path):
    _, tools = _tools(tmp_path)
    feature = "mobile-tests/src/test/resources/features/a.feature"
    tools.execute("write_file", {"path": feature, "content": "Feature: A\n  Scenario: one\n    Given x\n"})
    out, err = tools.execute("cucumber_dry_run", {"features": [feature]})
    assert not err and "OK   src/test/resources/features/a.feature:2" in out
    out, err = tools.execute("cucumber_dry_run", {"features": ["app/Main.java"]})
    assert err and "not inside the test project" in out
    tools.execute("write_file", {"path": PAGE, "content": "BROKEN"})
    out, _ = tools.execute("compile", {})
    assert out.startswith("BUILD FAILED")


def test_definitions_are_sorted_and_eager(tmp_path):
    _, tools = _tools(tmp_path)
    defs = tools.definitions()
    assert [d["name"] for d in defs] == sorted(d["name"] for d in defs)
    assert {"compile", "cucumber_dry_run", "write_file"} <= {d["name"] for d in defs}
    assert all(d["eager_input_streaming"] for d in defs)
