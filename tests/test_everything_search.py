import csv
import json
import sys
import tomllib
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

xefm_module = types.ModuleType("xefm")
user_api_module = types.ModuleType("xefm.user_api")
user_api_module.extension = lambda name: None
sys.modules.setdefault("xefm", xefm_module)
sys.modules.setdefault("xefm.user_api", user_api_module)

from everything_search import actions
from everything_search import logic, store
from everything_search.sdk import EverythingError, search


def test_migemo_expands_only_uppercase_alpha_hyphen_tokens():
    calls = []

    def expand(token):
        calls.append(token)
        return "kana.*"

    actual = logic.expand_migemo(
        "ABC;lower;foo-Bar;regex:ABC;A1; A-Z ",
        expand,
    )
    assert calls == ["ABC", "foo-Bar", "A-Z"]
    assert actual == 'regex:"kana.*";lower;regex:"kana.*";regex:ABC;A1;regex:"kana.*"'


def test_migemo_escapes_quotes_and_preserves_falsey_or_failed_tokens(caplog):
    def expand(token):
        if token == "A":
            return 'a"b'
        if token == "B":
            raise RuntimeError("failed")
        return ""

    assert logic.expand_migemo("A;B;C", expand) == 'regex:"a""b";B;C'
    assert "using it unchanged" in caplog.text


def test_query_scope_uses_trailing_separator_and_file_filter():
    assert logic.build_query("report", r"C:\My Folder", True) == '"C:\\My Folder\\" file: report'


def test_filter_json_and_csv_precedence_and_files_only(tmp_path):
    appdata = tmp_path / "roaming"
    folder = appdata / "Everything"
    folder.mkdir(parents=True)
    with (folder / "Filters.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["Name", "Search"])
        writer.writeheader()
        writer.writerow({"Name": "Image", "Search": "ext:png"})
        writer.writerow({"Name": "Dirs", "Search": "folder:docs"})
    filter_path = tmp_path / "everything_filters.json"
    filter_path.write_text(json.dumps({
        "image": {"query": "ext:jpg", "files_only": False},
        "Custom": "ext:txt",
    }), encoding="utf-8")

    filters = logic.load_filters(
        filter_json=filter_path,
        environ={"APPDATA": str(appdata)},
    )
    by_name = {item["name"].casefold(): item for item in filters}
    assert by_name["image"] == {
        "name": "image", "query": "ext:jpg", "files_only": False, "source": "extension"
    }
    assert by_name["dirs"]["files_only"] is False
    assert by_name["custom"]["files_only"] is True
    assert by_name["audio"]["query"] == "audio:"
    assert by_name["everything"]["query"] == ""


def test_scoop_csv_searches_in_precedence_order(tmp_path):
    beta = tmp_path / "scoop" / "persist" / "everything-beta"
    normal = tmp_path / "scoop" / "persist" / "everything"
    beta.mkdir(parents=True)
    normal.mkdir(parents=True)
    (beta / "Filters.csv").write_text("Name,Search\nFirst,ext:beta\n", encoding="utf-8")
    (normal / "Filters.csv").write_text("Name,Search\nSecond,ext:normal\n", encoding="utf-8")
    assert logic.first_csv("Filters.csv", {"SCOOP": str(tmp_path / "scoop")}) == beta / "Filters.csv"


def test_everything_bookmarks_csv_imports_filter_flags_and_sort(tmp_path):
    data = tmp_path / "scoop" / "persist" / "everything"
    data.mkdir(parents=True)
    with (data / "Filters.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["Name", "Search"])
        writer.writeheader()
        writer.writerow({"Name": "PDF", "Search": "ext:pdf"})
    columns = [
        "Name", "Type", "Filter", "Search", "Sort", "Descending", "Folder",
        "Case", "Whole Word", "Path", "Diacritic", "Prefix", "Suffix",
        "Ignore Punctuation", "Ignore Whitespace", "Regex",
    ]
    with (data / "Bookmarks.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerow({
            "Name": "Reports", "Type": "0", "Filter": "PDF", "Search": "Quarter",
            "Sort": "Date Modified", "Descending": "1", "Folder": "Work",
            "Case": "1", "Whole Word": "0", "Path": "1", "Diacritic": "0",
            "Prefix": "0", "Suffix": "0", "Ignore Punctuation": "0",
            "Ignore Whitespace": "0", "Regex": "0",
        })
        writer.writerow({"Name": "ignored", "Type": "1"})
    filters = logic.load_filters(filter_json=tmp_path / "missing.json", environ={"SCOOP": str(tmp_path / "scoop")})
    bookmarks = logic.load_everything_bookmarks(filters, {"SCOOP": str(tmp_path / "scoop")})
    assert len(bookmarks) == 1
    assert bookmarks[0]["query"] == "ext:pdf Quarter"
    assert bookmarks[0]["label"] == "Reports (Work)"
    assert bookmarks[0]["options"]["match_case"] is True
    assert bookmarks[0]["options"]["match_path"] is True
    assert bookmarks[0]["options"]["sort"] == [("date-modified", False)]


def test_json_bookmark_updates_preserve_unknown_keys_and_atomic_shape(tmp_path):
    path = tmp_path / "everything_bookmarks.json"
    path.write_text(json.dumps([{
        "name": "keep", "query": "old", "scope": None, "custom": {"keep": True}
    }]), encoding="utf-8")
    store.save_bookmark(path, {"name": "keep", "query": "new", "scope": r"C:\work"})
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == [{
        "name": "keep", "query": "new", "scope": r"C:\work", "custom": {"keep": True}
    }]
    assert store.delete_bookmark(path, "keep")
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_malformed_bookmark_json_is_never_replaced(tmp_path):
    path = tmp_path / "everything_bookmarks.json"
    original = b'{"bad":'
    path.write_bytes(original)
    with pytest.raises(store.StoreError):
        store.save_bookmark(path, {"name": "x", "query": "y", "scope": None})
    assert path.read_bytes() == original


class FakeSdk:
    def __init__(self, fail_connect=False, fail_search=False):
        self.calls = []
        self.fail_connect = fail_connect
        self.fail_search = fail_search

    def Everything3_ConnectW(self, instance):
        self.calls.append(("connect", instance))
        if self.fail_connect is True or (self.fail_connect == "default" and instance is None):
            return None
        return 10

    def Everything3_CreateSearchState(self):
        self.calls.append(("create_state",))
        return 20

    def Everything3_SetSearchTextW(self, state, query):
        self.calls.append(("query", query))
        return 1

    def Everything3_SetSearchMatchCase(self, state, value):
        self.calls.append(("match_case", value))
        return 1

    def Everything3_SetSearchMatchDiacritics(self, state, value):
        return 1

    def Everything3_SetSearchMatchWholeWords(self, state, value):
        return 1

    def Everything3_SetSearchMatchPath(self, state, value):
        return 1

    def Everything3_SetSearchMatchPrefix(self, state, value):
        return 1

    def Everything3_SetSearchMatchSuffix(self, state, value):
        return 1

    def Everything3_SetSearchIgnorePunctuation(self, state, value):
        return 1

    def Everything3_SetSearchWhitespace(self, state, value):
        return 1

    def Everything3_SetSearchRegex(self, state, value):
        return 1

    def Everything3_ClearSearchSorts(self, state):
        self.calls.append(("clear_sorts",))
        return 1

    def Everything3_AddSearchSort(self, state, prop, ascending):
        self.calls.append(("sort", prop, ascending))
        return 1

    def Everything3_Search(self, client, state):
        self.calls.append(("search",))
        return None if self.fail_search else 30

    def Everything3_GetResultListViewportCount(self, results):
        return 2

    def Everything3_GetResultFullPathNameW(self, results, index, buffer, size):
        value = [r"C:\a.txt", r"C:\b.txt"][index]
        buffer.value = value
        return len(value)

    def Everything3_DestroyResultList(self, results):
        self.calls.append(("destroy_results", results))
        return 1

    def Everything3_DestroySearchState(self, state):
        self.calls.append(("destroy_state", state))
        return 1

    def Everything3_DestroyClient(self, client):
        self.calls.append(("destroy_client", client))
        return 1

    def Everything3_GetLastError(self):
        return 0xE0000002


def test_sdk_connects_to_standard_then_15a_and_cleans_up():
    dll = FakeSdk(fail_connect="default")
    paths = search("report", dll_loader=lambda: dll)
    assert paths == [r"C:\a.txt", r"C:\b.txt"]
    assert dll.calls[:2] == [("connect", None), ("connect", "1.5a")]
    assert dll.calls[-3:] == [
        ("destroy_results", 30), ("destroy_state", 20), ("destroy_client", 10)
    ]


def test_sdk_passes_flags_and_sorts_to_fake_sdk():
    dll = FakeSdk()
    paths = search(
        "report",
        options={"match_case": True, "sort": [("size", False)]},
        dll_loader=lambda: dll,
    )
    assert len(paths) == 2
    assert ("match_case", True) in dll.calls
    assert ("sort", 2, False) in dll.calls


@pytest.mark.parametrize("fail_connect,fail_search", [(True, False), (False, True)])
def test_sdk_reports_connection_and_search_errors(fail_connect, fail_search):
    dll = FakeSdk(fail_connect=fail_connect, fail_search=fail_search)
    with pytest.raises(EverythingError):
        search("report", dll_loader=lambda: dll)


def test_all_legacy_action_keys_are_present_in_manifest():
    package_root = Path(__file__).parents[1]
    with (package_root / "xefm-extension.toml").open("rb") as stream:
        manifest = tomllib.load(stream)
    expected = {
        "everything.search-folder": ("search_folder", "Alt-S"),
        "everything.search-all": ("search_all", "Alt-Shift-S"),
        "everything.pick-filter": ("pick_filter", "Alt-Shift-F"),
        "everything.pick-filter-folder": ("pick_filter_folder", "Alt-Shift-L"),
        "everything.bookmarks": ("bookmarks", "Alt-B"),
        "everything.save-bookmark": ("save_bookmark", "Alt-Shift-B"),
        "everything.delete-bookmark": ("delete_bookmark", None),
        "everything.show-help": ("show_help", None),
    }
    suggestions = manifest["contributes"]["key_suggestions"]
    actions_table = manifest["contributes"]["actions"]
    for action, (function, key) in expected.items():
        assert action in actions_table
        assert callable(getattr(actions, function))
        if key is not None:
            assert suggestions[action] == [key]
    assert set(actions_table) == set(expected)


def test_run_search_preserves_query_on_migemo_error():
    received = []

    def broken(token):
        raise RuntimeError("migemo failure")

    def fake_search(query, **kwargs):
        received.append(query)
        return [r"C:\result.txt"]

    assert logic.run_search("ABC", migemo_expand=broken, searcher=fake_search) == [r"C:\result.txt"]
    assert received == ["ABC"]


def test_filter_and_bookmark_searches_skip_migemo_expansion():
    received = []

    def fake_search(query, **kwargs):
        received.append(query)
        return []

    logic.run_search(
        "ABC",
        migemo_expand=lambda token: "expanded",
        searcher=fake_search,
        expand_migemo_enabled=False,
    )
    assert received == ["ABC"]


class FakeState:
    def __init__(self, value=None):
        self.value = value

    def get(self, key, default=None):
        return self.value if self.value is not None else default

    def set(self, key, value):
        self.value = value


class FakeContext:
    def __init__(self, path=r"C:\work", state=None):
        self.messages = []
        self.inputs = []
        self.choices = []
        self.tasks = []
        self.markdown = []
        self.state = state or FakeState()
        self.pane = SimpleNamespace(
            path=Path(path),
            opened=None,
            open_list=lambda paths, title: setattr(self.pane, "opened", (paths, title)),
        )

    def message(self, text):
        self.messages.append(text)

    def input(self, prompt, default="", **kwargs):
        self.inputs.append((prompt, default, kwargs["on_accept"]))

    def choose(self, title, items, **kwargs):
        self.choices.append((title, items, kwargs["on_result"]))

    def run_task(self, title, work, on_done, **kwargs):
        self.tasks.append((title, work, on_done))

    def show_markdown(self, title, source):
        self.markdown.append((title, source))


def _wire_actions(monkeypatch, context):
    settings = SimpleNamespace(FILTERS={}, MIGEMO_EXPAND=None)
    monkeypatch.setattr(actions, "_settings", lambda: settings)
    monkeypatch.setattr(actions, "_state", lambda: context.state)
    monkeypatch.setattr(logic, "load_filters", lambda *args, **kwargs: [
        {"name": "PDF", "query": "ext:pdf", "files_only": True, "source": "standard"}
    ])
    monkeypatch.setattr(logic, "run_search", lambda query, **kwargs: [r"C:\work\report.pdf"])


@pytest.mark.parametrize(("action", "expected_scope"), [
    (actions.search_folder, r"C:\work"),
    (actions.search_all, None),
])
def test_search_input_actions_launch_search_and_store_recent(monkeypatch, action, expected_scope):
    context = FakeContext()
    _wire_actions(monkeypatch, context)
    action(context)
    assert len(context.inputs) == 1
    context.inputs[0][2]("Report")
    assert len(context.tasks) == 1
    _, work, done = context.tasks[0]
    result = work(SimpleNamespace(checkpoint=lambda: None, progress=lambda *args, **kwargs: None))
    done(context, SimpleNamespace(status="done", ok=True, value=result, error=None))
    assert context.state.value == {
        "query": "Report", "scope": expected_scope, "files_only": False, "options": {}
    }
    assert context.pane.opened == ([r"C:\work\report.pdf"], "Everything: Report")
    assert context.messages == [
        "Everything found 1 result(s); XeFM is preparing the pane. This may take time."
    ]


def test_search_no_results_does_not_claim_pane_is_being_prepared(monkeypatch):
    context = FakeContext()
    _wire_actions(monkeypatch, context)
    actions.search_all(context)
    context.inputs[0][2]("missing")
    _, _, done = context.tasks[0]
    done(context, SimpleNamespace(status="done", ok=True, value=[], error=None))
    assert context.pane.opened == ([], "Everything: missing")
    assert context.messages == ["Everything found no results"]


@pytest.mark.parametrize(("status", "error", "message"), [
    ("cancelled", None, "Everything search cancelled"),
    ("failed", RuntimeError("offline"), "Everything Search failed: offline"),
])
def test_search_unsuccessful_task_does_not_prepare_pane(monkeypatch, status, error, message):
    context = FakeContext()
    _wire_actions(monkeypatch, context)
    actions.search_all(context)
    context.inputs[0][2]("report")
    _, _, done = context.tasks[0]
    done(context, SimpleNamespace(status=status, ok=False, value=None, error=error))
    assert context.pane.opened is None
    assert context.messages == [message]


def test_search_open_list_error_does_not_claim_pane_is_being_prepared(monkeypatch):
    context = FakeContext()
    _wire_actions(monkeypatch, context)

    def fail_open(paths, *, title):
        raise RuntimeError("cannot open list")

    context.pane.open_list = fail_open
    actions.search_all(context)
    context.inputs[0][2]("report")
    _, _, done = context.tasks[0]
    done(context, SimpleNamespace(status="done", ok=True, value=["report"], error=None))
    assert context.messages == ["Everything Search failed: cannot open list"]


def test_search_input_rejects_blank_query(monkeypatch):
    context = FakeContext()
    _wire_actions(monkeypatch, context)
    actions.search_all(context)
    context.inputs[0][2]("   ")
    assert context.messages == ["Enter a search term"]
    assert not context.tasks


@pytest.mark.parametrize(("action", "expected_scope"), [
    (actions.pick_filter, None),
    (actions.pick_filter_folder, r"C:\work"),
])
def test_filter_pick_actions_launch_without_migemo(monkeypatch, action, expected_scope):
    context = FakeContext()
    _wire_actions(monkeypatch, context)
    action(context)
    assert context.choices[0][1] == ["PDF  —  ext:pdf"]
    context.choices[0][2](0)
    assert context.tasks
    _, work, _ = context.tasks[0]
    calls = []
    monkeypatch.setattr(logic, "run_search", lambda query, **kwargs: calls.append((query, kwargs)) or [])
    work(SimpleNamespace(checkpoint=lambda: None, progress=lambda *args, **kwargs: None))
    assert calls[0][0] == "ext:pdf"
    assert calls[0][1]["scope"] == expected_scope
    assert calls[0][1]["expand_migemo_enabled"] is False


def test_bookmarks_action_includes_local_and_everything_sources(monkeypatch):
    context = FakeContext()
    _wire_actions(monkeypatch, context)
    items = [{
        "name": "Recent", "label": "Recent", "query": "ABC",
        "scope": None, "source": "extension", "options": {},
    }]
    monkeypatch.setattr(logic, "load_bookmarks", lambda **kwargs: items)
    actions.bookmarks(context)
    assert context.choices[0][1] == ["Recent"]
    context.choices[0][2](0)
    _, work, _ = context.tasks[0]
    calls = []
    monkeypatch.setattr(logic, "run_search", lambda query, **kwargs: calls.append(kwargs) or [])
    work(SimpleNamespace(checkpoint=lambda: None, progress=lambda *args, **kwargs: None))
    assert calls[0]["expand_migemo_enabled"] is False


@pytest.mark.parametrize("action", [
    actions.pick_filter, actions.pick_filter_folder, actions.bookmarks, actions.delete_bookmark,
])
def test_choice_cancellation_does_not_run_action(monkeypatch, action):
    context = FakeContext()
    _wire_actions(monkeypatch, context)
    monkeypatch.setattr(logic, "load_bookmarks", lambda **kwargs: [{
        "label": "Recent", "query": "ABC",
    }])
    monkeypatch.setattr(store, "read_bookmarks", lambda path: [{"name": "Recent"}])
    action(context)
    context.choices[0][2](None)
    assert not context.tasks
    assert not context.messages


def test_save_and_delete_bookmark_actions_only_edit_extension_json(monkeypatch, tmp_path):
    context = FakeContext(state=FakeState({
        "query": "report", "scope": r"C:\work", "files_only": False, "options": {}
    }))
    _wire_actions(monkeypatch, context)
    path = tmp_path / "everything_bookmarks.json"
    monkeypatch.setattr(logic, "bookmark_path", lambda: path)
    actions.save_bookmark(context)
    context.inputs[0][2]("Work")
    assert store.read_bookmarks(path) == [
        {"name": "Work", "query": "report", "scope": r"C:\work"}
    ]
    actions.delete_bookmark(context)
    context.choices[0][2](0)
    assert store.read_bookmarks(path) == []


def test_save_bookmark_rejects_blank_name(monkeypatch, tmp_path):
    context = FakeContext(state=FakeState({"query": "report"}))
    _wire_actions(monkeypatch, context)
    path = tmp_path / "everything_bookmarks.json"
    monkeypatch.setattr(logic, "bookmark_path", lambda: path)
    actions.save_bookmark(context)
    context.inputs[0][2]("   ")
    assert context.messages == ["Bookmark name must not be empty"]
    assert not path.exists()


def test_help_action_displays_explanation():
    context = FakeContext()
    actions.show_help(context)
    assert len(context.markdown) == 1
    assert "SDK 3 named-pipe API" in context.markdown[0][1]
