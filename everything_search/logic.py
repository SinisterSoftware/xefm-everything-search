"""Search, filter, bookmark, and compatibility logic independent of XeFM."""

import csv
import logging
import os
import re
from pathlib import Path

from . import store
from .sdk import search as sdk_search

logger = logging.getLogger(__name__)
SEARCH_STATE_KEY = "last_search"
BOOKMARKS_FILENAME = "everything_bookmarks.json"
FILTERS_FILENAME = "everything_filters.json"
STANDARD_FILTERS = {
    "Everything": {"query": "", "files_only": False},
    "Audio": {"query": "audio:", "files_only": True},
    "Compressed": {"query": "zip:", "files_only": True},
    "Document": {"query": "doc:", "files_only": True},
    "Executable": {"query": "exe:", "files_only": True},
    "Folder": {"query": "folder:", "files_only": False},
    "Image": {"query": "image:", "files_only": True},
    "Video": {"query": "video:", "files_only": True},
}
_MIGEMO_TOKEN = re.compile(r"^[A-Za-z-]+$")
_BOOKMARK_FLAGS = {
    "Case": "match_case",
    "Whole Word": "whole_word",
    "Path": "match_path",
    "Diacritic": "match_diacritics",
    "Prefix": "prefix",
    "Suffix": "suffix",
    "Ignore Punctuation": "ignore_punctuation",
    "Ignore Whitespace": "ignore_whitespace",
    "Regex": "regex",
}


def _truth(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def everything_config_dirs(environ=None):
    env = os.environ if environ is None else environ
    roots = []
    scoop = env.get("SCOOP")
    if scoop:
        roots.extend((Path(scoop) / "persist" / "everything-beta", Path(scoop) / "persist" / "everything"))
    for variable in ("APPDATA", "LOCALAPPDATA"):
        if env.get(variable):
            roots.append(Path(env[variable]) / "Everything")
    return roots


def first_csv(filename, environ=None):
    for directory in everything_config_dirs(environ):
        path = directory / filename
        if path.is_file():
            return path
    return None


def _read_csv(path, required_headers=()):
    try:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not reader.fieldnames or any(header not in reader.fieldnames for header in required_headers):
                raise store.StoreError(
                    f"{Path(path).name} is missing required columns: {', '.join(required_headers)}"
                )
            return list(reader)
    except store.StoreError:
        raise
    except (OSError, UnicodeError, csv.Error) as exc:
        raise store.StoreError(f"Cannot read {Path(path).name}: {exc}") from exc


def _normalise_filter(name, query, files_only, source):
    if not isinstance(name, str) or not name:
        raise store.StoreError("Filter names must be non-empty strings")
    if not isinstance(query, str):
        raise store.StoreError(f"Filter {name!r} must have a string query")
    if not isinstance(files_only, bool):
        raise store.StoreError(f"Filter {name!r} must have a boolean files_only value")
    return {"name": name, "query": query, "files_only": files_only, "source": source}


def load_filters(settings_filters=None, filter_json=None, environ=None):
    """Merge defaults, the selected Everything Filters.csv, then extension JSON."""
    merged = {}
    for name, value in STANDARD_FILTERS.items():
        merged[name.casefold()] = _normalise_filter(name, value["query"], value["files_only"], "standard")
    if settings_filters is not None and not isinstance(settings_filters, dict):
        raise store.StoreError("Configured FILTERS must be a mapping")
    for name, value in (settings_filters or {}).items():
        if isinstance(value, str):
            query, files_only = value, not value.strip().lower().startswith("folder:")
        elif isinstance(value, dict):
            query = value.get("query")
            files_only = value.get("files_only", not str(query or "").strip().lower().startswith("folder:"))
        else:
            raise store.StoreError(f"Configured filter {name!r} must be a query string or object")
        merged[name.casefold()] = _normalise_filter(name, query, files_only, "standard")

    csv_path = first_csv("Filters.csv", environ)
    if csv_path:
        for row in _read_csv(csv_path, ("Name", "Search")):
            name, query = row.get("Name") or "", row.get("Search") or ""
            if not name:
                continue
            merged[name.casefold()] = _normalise_filter(
                name, query, not query.strip().lower().startswith("folder:"), "everything"
            )

    json_path = Path(filter_json) if filter_json is not None else store.state_directory() / FILTERS_FILENAME
    for name, value in store.read_filters(json_path).items():
        merged[name.casefold()] = value
    return list(merged.values())


def _sort_spec(sort_value, descending):
    if not sort_value:
        return []
    name = "-".join(str(sort_value).strip().lower().split())
    if name not in {
        "name", "path", "size", "extension", "type", "date-modified", "date-created",
        "date-accessed", "attributes", "date-recently-changed", "run-count", "date-run",
    }:
        logger.warning("Unsupported Everything bookmark sort field %r; ignoring it", sort_value)
        return []
    return [(name, not _truth(descending))]


def load_everything_bookmarks(filters, environ=None):
    csv_path = first_csv("Bookmarks.csv", environ)
    if not csv_path:
        return []
    filters_by_name = {item["name"].casefold(): item for item in filters}
    bookmarks = []
    for row in _read_csv(csv_path, ("Name",)):
        kind = (row.get("Type") or "").strip()
        name = (row.get("Name") or "").strip()
        if kind not in ("", "0") or not name:
            continue
        query = (row.get("Search") or "").strip()
        filter_name = (row.get("Filter") or "").strip()
        filter_item = filters_by_name.get(filter_name.casefold())
        if filter_item:
            query = combine_queries(filter_item["query"], query)
        if not query and not any(_truth(row.get(field)) for field in _BOOKMARK_FLAGS):
            continue
        options = {key: _truth(row.get(field)) for field, key in _BOOKMARK_FLAGS.items()}
        options["sort"] = _sort_spec(row.get("Sort", ""), row.get("Descending", ""))
        folder_label = (row.get("Folder") or "").strip()
        bookmarks.append({
            "name": name,
            "query": query,
            "scope": None,
            "source": "everything",
            "label": f"{name} ({folder_label})" if folder_label else name,
            "options": options,
        })
    return bookmarks


def combine_queries(*queries):
    return " ".join(query.strip() for query in queries if isinstance(query, str) and query.strip())


def expand_migemo(query, expand, trace=None):
    """Expand eligible search terms without changing filters or Everything syntax."""
    if not callable(expand) or not query:
        if trace is not None:
            trace.append(("Migemo", "No callable configured or query is empty"))
        return query
    result = []
    for raw_token in query.split(";"):
        token = raw_token.strip()
        if not (_MIGEMO_TOKEN.fullmatch(token) and any(ch.isupper() for ch in token)):
            if trace is not None:
                trace.append(("Migemo skipped token", raw_token))
            result.append(raw_token)
            continue
        if trace is not None:
            trace.append(("Migemo input token", token))
        try:
            pattern = expand(token)
        except Exception:
            logger.exception("MIGEMO_EXPAND failed for token %r; using it unchanged", token)
            if trace is not None:
                trace.append(("Migemo", "Callback failed; token unchanged"))
            result.append(raw_token)
            continue
        if not pattern:
            if trace is not None:
                trace.append(("Migemo", "Callback returned no pattern; token unchanged"))
            result.append(raw_token)
            continue
        if not isinstance(pattern, str):
            logger.error("MIGEMO_EXPAND must return a string pattern; using token %r unchanged", token)
            if trace is not None:
                trace.append(("Migemo", "Callback returned a non-string pattern; token unchanged"))
            result.append(raw_token)
            continue
        if trace is not None:
            trace.append(("Migemo pattern", pattern))
        result.append(f'regex:"{pattern.replace(chr(34), chr(34) * 2)}"')
    return ";".join(result)


def build_query(query, scope=None, files_only=False):
    parts = []
    if scope:
        normalized_scope = str(scope).replace("/", "\\").rstrip("\\") + "\\"
        parts.append(f'"{normalized_scope}"')
    if files_only:
        parts.append("file:")
    if query.strip():
        parts.append(query.strip())
    return " ".join(parts)


def bookmark_path(home=None):
    return store.state_directory(home) / BOOKMARKS_FILENAME


def filter_path(home=None):
    return store.state_directory(home) / FILTERS_FILENAME


def load_bookmarks(home=None, filters=None, environ=None):
    path = bookmark_path(home)
    local = [dict(item, source="extension", label=item["name"], options={}) for item in store.read_bookmarks(path)]
    imported = load_everything_bookmarks(filters or load_filters(filter_json=filter_path(home), environ=environ), environ)
    return local + imported


def run_search(
    query, scope=None, files_only=False, options=None, migemo_expand=None,
    searcher=sdk_search, job=None, expand_migemo_enabled=True, trace=None,
):
    if trace is not None:
        trace.append(("Input", query))
    if expand_migemo_enabled:
        expanded = expand_migemo(query, migemo_expand, trace=trace)
    else:
        expanded = query
        if trace is not None:
            trace.append(("Migemo", "Disabled for this search"))
    sdk_query = build_query(expanded, scope, files_only)
    if trace is not None:
        trace.append(("After Migemo", expanded))
        trace.append(("SDK search text prepared", sdk_query))
    checkpoint = job.checkpoint if job is not None else None
    progress = job.progress if job is not None else None
    kwargs = {"options": options or {}, "checkpoint": checkpoint, "progress": progress}
    if trace is not None:
        kwargs["on_set_search_text"] = lambda text: trace.append(("SDK SetSearchTextW attempted", text))
    return searcher(sdk_query, **kwargs)
