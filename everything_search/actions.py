"""XeFM actions for Everything Search."""

import logging

from xefm.user_api import extension

from . import logic, store
from .sdk import EverythingError

logger = logging.getLogger(__name__)


def _settings():
    handle = extension(__name__)
    if handle is None or handle.settings is None:
        raise RuntimeError("Everything Search settings are unavailable")
    return handle.settings


def _state():
    handle = extension(__name__)
    if handle is None:
        raise RuntimeError("Everything Search state is unavailable")
    return handle.state


def _report_error(ctx, exc):
    logger.exception("Everything Search failed", exc_info=exc)
    ctx.message(f"Everything Search failed: {exc}")


def _start_search(ctx, query, scope=None, files_only=False, options=None, title=None, expand_migemo=True):
    try:
        settings = _settings()
        request = {
            "query": query,
            "scope": scope,
            "files_only": bool(files_only),
            "options": dict(options or {}),
        }
        migemo_expand = settings.MIGEMO_EXPAND if expand_migemo else None

        def work(job):
            return logic.run_search(
                query,
                scope=scope,
                files_only=files_only,
                options=options,
                migemo_expand=migemo_expand,
                job=job,
                expand_migemo_enabled=expand_migemo,
            )

        def done(ctx, outcome):
            if outcome.status == "cancelled":
                ctx.message("Everything search cancelled")
            elif not outcome.ok:
                ctx.message(f"Everything Search failed: {outcome.error}")
            else:
                try:
                    _state().set(logic.SEARCH_STATE_KEY, request)
                    ctx.pane.open_list(outcome.value, title=title or f"Everything: {query}")
                except (OSError, RuntimeError, ValueError) as exc:
                    _report_error(ctx, exc)
                    return
                count = len(outcome.value)
                if count:
                    ctx.message(
                        f"Everything found {count} result(s); XeFM is preparing the pane. "
                        "This may take time."
                    )
                else:
                    ctx.message("Everything found no results")

        ctx.run_task("Everything Search", work, on_done=done, read_only=True)
    except (OSError, ValueError, RuntimeError, store.StoreError, EverythingError) as exc:
        _report_error(ctx, exc)


def _ask_query(ctx, scope=None):
    try:
        initial = _state().get(logic.SEARCH_STATE_KEY, {})
    except (OSError, RuntimeError) as exc:
        _report_error(ctx, exc)
        initial = {}
    default = initial.get("query", "") if isinstance(initial, dict) else ""

    def accepted(query):
        if not query.strip():
            ctx.message("Enter a search term")
            return
        _start_search(ctx, query.strip(), scope=scope, title=f"Everything: {query.strip()}")

    ctx.input(
        "Search Everything",
        default,
        title="Everything Search",
        on_accept=accepted,
    )


def search_folder(ctx):
    """Search Everything within the active pane's current folder."""
    _ask_query(ctx, scope=str(ctx.pane.path))


def search_all(ctx):
    """Search Everything across all indexed locations."""
    _ask_query(ctx)


def _filters(ctx):
    settings = _settings()
    return logic.load_filters(settings.FILTERS, logic.filter_path())


def _pick_filter(ctx, scope=None):
    try:
        filters = _filters(ctx)
    except (OSError, ValueError, RuntimeError, store.StoreError) as exc:
        _report_error(ctx, exc)
        return
    if not filters:
        ctx.message("No Everything filters are available")
        return
    labels = [f'{item["name"]}  —  {item["query"]}' for item in filters]

    def selected(index):
        if index is None:
            return
        item = filters[index]
        _start_search(
            ctx,
            item["query"],
            scope=scope,
            files_only=item["files_only"],
            title=f'Everything: {item["name"]}',
            expand_migemo=False,
        )

    ctx.choose("Choose an Everything filter", labels, type="choice", on_result=selected)


def pick_filter(ctx):
    """Choose an Everything filter and search all indexed locations."""
    _pick_filter(ctx)


def pick_filter_folder(ctx):
    """Choose an Everything filter and search within the active folder."""
    _pick_filter(ctx, scope=str(ctx.pane.path))


def bookmarks(ctx):
    """Choose and run an Everything bookmark."""
    try:
        filters = _filters(ctx)
        items = logic.load_bookmarks(filters=filters)
    except (OSError, ValueError, RuntimeError, store.StoreError) as exc:
        _report_error(ctx, exc)
        return
    if not items:
        ctx.message("No Everything bookmarks are available")
        return
    labels = [item["label"] for item in items]

    def selected(index):
        if index is None:
            return
        item = items[index]
        _start_search(
            ctx,
            item["query"],
            scope=item.get("scope"),
            options=item.get("options"),
            title=f'Everything: {item["label"]}',
            expand_migemo=False,
        )

    ctx.choose("Choose an Everything bookmark", labels, type="choice", on_result=selected)


def save_bookmark(ctx):
    """Save the most recent search as an extension bookmark."""
    try:
        recent = _state().get(logic.SEARCH_STATE_KEY)
    except (OSError, RuntimeError) as exc:
        _report_error(ctx, exc)
        return
    if not isinstance(recent, dict) or not isinstance(recent.get("query"), str):
        ctx.message("There is no recent Everything search to save")
        return

    def accepted(name):
        name = name.strip()
        if not name:
            ctx.message("Bookmark name must not be empty")
            return
        bookmark = {
            "name": name,
            "query": recent["query"],
            "scope": recent.get("scope"),
        }
        try:
            store.save_bookmark(logic.bookmark_path(), bookmark)
            ctx.message(f"Saved Everything bookmark: {name}")
        except (OSError, ValueError, store.StoreError) as exc:
            _report_error(ctx, exc)

    ctx.input(
        "Bookmark name",
        recent.get("query", ""),
        title="Save Everything Bookmark",
        on_accept=accepted,
    )


def delete_bookmark(ctx):
    """Delete an extension bookmark without changing Everything's CSV bookmarks."""
    try:
        items = store.read_bookmarks(logic.bookmark_path())
    except (OSError, ValueError, store.StoreError) as exc:
        _report_error(ctx, exc)
        return
    if not items:
        ctx.message("No extension bookmarks are available to delete")
        return
    names = [item["name"] for item in items]

    def selected(index):
        if index is None:
            return
        name = names[index]
        try:
            if store.delete_bookmark(logic.bookmark_path(), name):
                ctx.message(f"Deleted Everything bookmark: {name}")
        except (OSError, ValueError, store.StoreError) as exc:
            _report_error(ctx, exc)

    ctx.choose("Delete an extension bookmark", names, type="choice", on_result=selected)


def show_help(ctx):
    """Show help for Everything Search."""
    ctx.show_markdown(
        "Everything Search",
        "Searches Everything 1.5 using its official SDK 3 named-pipe API. "
        "Results open as a list in the active XeFM pane. Search All, Search Folder, "
        "filter selection, bookmarks, and help are available from the command palette. "
        "Use `everything.save-bookmark` to save the most recent search. "
        "Everything CSV bookmarks and filters are read-only; only extension bookmarks "
        "can be changed. Configure `EverythingSearchConfig.MIGEMO_EXPAND` with a "
        "synchronous callable that accepts a token and returns a regular-expression string."
    )
