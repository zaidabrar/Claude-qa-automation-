from pathlib import Path

from qa_harness.tools import Workspace, build_workspace_tools


def _tools(tmp_path: Path):
    (tmp_path / "mobile_tests" / "pages").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('app')\n")
    (tmp_path / ".env").write_text("SECRET=1\n")
    ws = Workspace(tmp_path, tmp_path / "mobile_tests")
    return ws, build_workspace_tools(ws)


def test_writes_are_confined_to_tests_dir(tmp_path):
    ws, tools = _tools(tmp_path)
    out, err = tools.execute("write_file", {"path": "src/app.py", "content": "pwned"})
    assert err and "only allowed" in out
    assert (tmp_path / "src" / "app.py").read_text() == "print('app')\n"

    out, err = tools.execute("write_file", {"path": "mobile_tests/pages/home.py", "content": "x = 1\n"})
    assert not err
    assert ws.written == {"mobile_tests/pages/home.py"}


def test_path_escape_and_secrets_are_blocked(tmp_path):
    _, tools = _tools(tmp_path)
    out, err = tools.execute("read_file", {"path": "../../etc/passwd"})
    assert err and "escapes" in out
    out, err = tools.execute("read_file", {"path": ".env"})
    assert err and "not permitted" in out
    out, err = tools.execute("write_file", {"path": "mobile_tests/run.sh", "content": "rm -rf /"})
    assert err and "file type" in out


def test_invalid_input_is_reported_not_raised(tmp_path):
    _, tools = _tools(tmp_path)
    out, err = tools.execute("read_file", {"start_line": 1})
    assert err and "Invalid input" in out
    out, err = tools.execute("nope", {})
    assert err and "Unknown tool" in out


def test_edit_requires_unique_match(tmp_path):
    _, tools = _tools(tmp_path)
    tools.execute("write_file", {"path": "mobile_tests/a.py", "content": "x = 1\nx = 1\n"})
    out, err = tools.execute("edit_file", {"path": "mobile_tests/a.py", "old_str": "x = 1", "new_str": "y"})
    assert err and "2 times" in out
    out, err = tools.execute("edit_file", {"path": "mobile_tests/a.py", "old_str": "x = 1\nx", "new_str": "z = 2\nx"})
    assert not err
    assert (tmp_path / "mobile_tests" / "a.py").read_text() == "z = 2\nx = 1\n"


def test_search_and_list(tmp_path):
    _, tools = _tools(tmp_path)
    out, err = tools.execute("search", {"pattern": r"print\(", "path": "."})
    assert not err and "src/app.py:1" in out
    out, err = tools.execute("list_dir", {"path": "."})
    assert "mobile_tests/" in out and "src/" in out


def test_definitions_are_sorted_and_eager(tmp_path):
    _, tools = _tools(tmp_path)
    defs = tools.definitions()
    assert [d["name"] for d in defs] == sorted(d["name"] for d in defs)
    assert all(d["eager_input_streaming"] for d in defs)
