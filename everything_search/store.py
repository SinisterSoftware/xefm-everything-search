"""Read and safely update Everything Search's compatible data files."""

import json
import os
import tempfile
from pathlib import Path


class StoreError(ValueError):
    """A stored data file is malformed or has an unsupported shape."""


def state_directory(home=None):
    return Path(home or Path.home()) / ".xefm" / "state"


def _read_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            return json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StoreError(f"Cannot read {path.name}: {exc}") from exc


def read_bookmarks(path):
    data = _read_json(path, [])
    if not isinstance(data, list):
        raise StoreError(f"{Path(path).name} must contain a JSON array")
    for index, item in enumerate(data):
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not isinstance(item.get("query"), str):
            raise StoreError(f"{Path(path).name} item {index + 1} must have string name and query fields")
        if item.get("scope") is not None and not isinstance(item.get("scope"), str):
            raise StoreError(f"{Path(path).name} item {index + 1} has an invalid scope")
    return data


def read_filters(path):
    data = _read_json(path, {})
    if not isinstance(data, dict):
        raise StoreError(f"{Path(path).name} must contain a JSON object")
    filters = {}
    for name, value in data.items():
        if not isinstance(name, str) or not name:
            raise StoreError(f"{Path(path).name} contains an invalid filter name")
        if isinstance(value, str):
            query, files_only = value, True
        elif isinstance(value, dict) and isinstance(value.get("query"), str):
            files_only = value.get("files_only", True)
            if not isinstance(files_only, bool):
                raise StoreError(f"Filter {name!r} in {Path(path).name} has an invalid files_only value")
            query = value["query"]
        else:
            raise StoreError(f"Filter {name!r} in {Path(path).name} must be a query string or object")
        filters[name] = {"name": name, "query": query, "files_only": files_only, "source": "extension"}
    return filters


def _write_json_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise StoreError(f"Cannot safely update {path.name}: {exc}") from exc


def save_bookmark(path, bookmark):
    bookmarks = read_bookmarks(path)
    name = bookmark["name"]
    for index, existing in enumerate(bookmarks):
        if existing["name"] == name:
            replacement = dict(existing)
            replacement.update(bookmark)
            bookmarks[index] = replacement
            break
    else:
        bookmarks.append(dict(bookmark))
    _write_json_atomic(path, bookmarks)


def delete_bookmark(path, name):
    bookmarks = read_bookmarks(path)
    updated = [item for item in bookmarks if item["name"] != name]
    if len(updated) == len(bookmarks):
        return False
    _write_json_atomic(path, updated)
    return True
