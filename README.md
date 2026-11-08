# Everything Search

A Windows XeFM extension for Everything 1.5. It calls the official Everything
SDK 3 named-pipe API and shows matches in the active XeFM pane. It does not
launch or locate the Everything executable, so renaming that executable has no
effect. The bundled SDK DLL is 64-bit; 64-bit Python is required.

日本語の詳しい説明は [README.ja.md](README.ja.md) を参照してください。

Install from GitHub with:

```text
xefm ext install github:SinisterSoftware/xefm-everything-search
```

Everything 1.5 must be running with IPC enabled. The extension first connects
to the default instance, then tries the `1.5a` instance. Connection and search
failures are reported in XeFM. Search results are collected in a background
task and opened as a virtual list in the active pane. After results are found,
XeFM checks the paths before displaying them; for large searches the original
pane remains visible while the list is prepared. The log reports when the list
is ready or when no paths can be shown.

## Actions

The extension contributes the existing action names and suggested keys:

| Action | Suggested key |
|---|---|
| `everything.search-folder` | `Alt-S` |
| `everything.search-all` | `Alt-Shift-S` |
| `everything.pick-filter` | `Alt-Shift-F` |
| `everything.pick-filter-folder` | `Alt-Shift-L` |
| `everything.bookmarks` | `Alt-B` |
| `everything.save-bookmark` | `Alt-Shift-B` |
| `everything.delete-bookmark` | — |
| `everything.show-help` | — |

XeFM suggests a key only when it is available. If a suggestion conflicts with
another action, add the action explicitly to `KEY_BINDINGS` in `config.py`.
Every action is also available from the command palette.

## Filters, bookmarks, and search state

The extension reads `~/.xefm/state/everything_filters.json`, whose root is an
object mapping filter names to either a query string or an object:

```json
{
  "Source files": {"query": "ext:c;h;py", "files_only": true},
  "Folders": {"query": "folder:", "files_only": false}
}
```

Filters merge in this order: standard filters, the first available
`Filters.csv`, then this JSON file. The last definition of a name wins
case-insensitively. `Filters.csv` is read from the first existing location in
this order: `%SCOOP%\persist\everything-beta`,
`%SCOOP%\persist\everything`, `%APPDATA%\Everything`, then
`%LOCALAPPDATA%\Everything`. CSV files are read-only.

Extension bookmarks live in `~/.xefm/state/everything_bookmarks.json` as a
UTF-8 JSON array of objects with `name`, `query`, and `scope` fields. Existing
additional keys on an edited bookmark are preserved. Updates use a temporary
file and atomic replacement. Invalid or unreadable files are reported and are
never replaced with empty data. `everything.delete-bookmark` changes only this
extension JSON file; it never edits Everything's `Bookmarks.csv`.

Everything's `Bookmarks.csv` is read from the same ordered directories and
remains read-only. Eligible bookmarks (missing or zero `Type`) are imported
alongside extension bookmarks. Search flags, filters, sorting, and optional
folder labels are applied where supported.

The most recent extension search is stored in XeFM extension state so it can
be saved as a bookmark later. Search input is not written to a separate
history file.

The extension uses XeFM Preview APIs for dialogs, background searches,
Markdown help, settings, and virtual-folder results. `xefm ext check` lists
those Preview uses because the host API may change in a future XeFM release.

## Migemo

`EverythingSearchConfig.MIGEMO_EXPAND` may be a synchronous callable that
accepts a search token and returns a regular-expression string. It defaults to
`None`. Only semicolon-delimited tokens made of ASCII letters and hyphens
that contain an uppercase letter are passed to it. Filter expressions,
Everything syntax, and lowercase words are left unchanged. A returned pattern
becomes an Everything `regex:` term; falsey results or callback errors keep
the original token, with callback errors logged.

## License and SDK

This extension is MIT-licensed. It includes `Everything3_x64.dll` from
Everything SDK 3.0.0.9, obtained from
[voidtools/everything_sdk3](https://github.com/voidtools/everything_sdk3).
The SDK is MIT-licensed by voidtools / David Carpenter; its required
attribution and license text are included in `THIRD-PARTY-NOTICES.md`.
The verified release ZIP SHA-256 is
`124685d35a5f49f3c1e9898853e166215748c893782c6a251f5dde58dacad4fa`; the
bundled DLL SHA-256 is
`be25b01c73bbf359b50ddf30255133225f93b4bc40a8d208173319373bcdaa5c`.

## Development

Run `xefm ext check .` and `python -m pytest tests`. Tests use a fake SDK and
do not launch XeFM or Everything.
