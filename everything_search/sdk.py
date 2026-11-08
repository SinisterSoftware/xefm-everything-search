"""Minimal ctypes binding to the official Everything SDK 3 DLL."""

import ctypes
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SDK_DLL = "Everything3_x64.dll"
MAX_PATH_CHARS = 32768
_SORT_PROPERTIES = {
    "name": 0,
    "path": 1,
    "size": 2,
    "extension": 3,
    "type": 4,
    "date-modified": 5,
    "date-created": 6,
    "date-accessed": 7,
    "attributes": 8,
    "date-recently-changed": 9,
    "run-count": 10,
    "date-run": 11,
}


class EverythingError(RuntimeError):
    """An SDK load, connection, or search failure."""


def _sdk_error(dll):
    try:
        return int(dll.Everything3_GetLastError())
    except (AttributeError, TypeError, ValueError):
        return 0


def _set_prototype(function, restype, argtypes):
    try:
        function.restype = restype
        function.argtypes = argtypes
    except (AttributeError, TypeError):
        pass


def _load_dll():
    if os.name != "nt":
        raise EverythingError("Everything Search is available on Windows only")
    if ctypes.sizeof(ctypes.c_void_p) != 8:
        raise EverythingError("The bundled Everything SDK DLL requires 64-bit Python")
    dll_path = Path(__file__).with_name(SDK_DLL)
    try:
        return ctypes.WinDLL(str(dll_path))
    except OSError as exc:
        raise EverythingError(f"Cannot load the bundled Everything SDK DLL: {exc}") from exc


def _call_bool(dll, name, *args):
    function = getattr(dll, name)
    _set_prototype(function, ctypes.c_int, [ctypes.c_void_p, ctypes.c_int])
    if not function(*args):
        raise EverythingError(f"{name} failed (Everything SDK error 0x{_sdk_error(dll):08X})")


def _configure(dll):
    pointer = ctypes.c_void_p
    size = ctypes.c_size_t
    wchar_pointer = ctypes.c_wchar_p
    _set_prototype(dll.Everything3_ConnectW, pointer, [wchar_pointer])
    _set_prototype(dll.Everything3_CreateSearchState, pointer, [])
    _set_prototype(dll.Everything3_DestroySearchState, ctypes.c_int, [pointer])
    _set_prototype(dll.Everything3_DestroyClient, ctypes.c_int, [pointer])
    _set_prototype(dll.Everything3_DestroyResultList, ctypes.c_int, [pointer])
    _set_prototype(dll.Everything3_SetSearchTextW, ctypes.c_int, [pointer, wchar_pointer])
    _set_prototype(dll.Everything3_Search, pointer, [pointer, pointer])
    _set_prototype(dll.Everything3_GetResultListViewportCount, size, [pointer])
    _set_prototype(dll.Everything3_GetResultFullPathNameW, size, [pointer, size, ctypes.POINTER(ctypes.c_wchar), size])
    for name in (
        "Everything3_SetSearchMatchCase",
        "Everything3_SetSearchMatchDiacritics",
        "Everything3_SetSearchMatchWholeWords",
        "Everything3_SetSearchMatchPath",
        "Everything3_SetSearchMatchPrefix",
        "Everything3_SetSearchMatchSuffix",
        "Everything3_SetSearchIgnorePunctuation",
        "Everything3_SetSearchWhitespace",
        "Everything3_SetSearchRegex",
    ):
        _set_prototype(getattr(dll, name), ctypes.c_int, [pointer, ctypes.c_int])
    _set_prototype(dll.Everything3_ClearSearchSorts, ctypes.c_int, [pointer])
    _set_prototype(dll.Everything3_AddSearchSort, ctypes.c_int, [pointer, ctypes.c_uint32, ctypes.c_int])
    _set_prototype(dll.Everything3_GetLastError, ctypes.c_uint32, [])


def _full_path(dll, results, index):
    buffer_size = 512
    while buffer_size <= MAX_PATH_CHARS:
        buffer = ctypes.create_unicode_buffer(buffer_size)
        length = int(dll.Everything3_GetResultFullPathNameW(results, index, buffer, buffer_size))
        if length == 0:
            raise EverythingError(
                f"Could not read Everything result {index} "
                f"(Everything SDK error 0x{_sdk_error(dll):08X})"
            )
        if length < buffer_size:
            return buffer.value
        buffer_size = length + 1
    raise EverythingError(f"Everything result {index} exceeds the supported path length")


def search(query, options=None, checkpoint=None, progress=None, dll_loader=_load_dll):
    """Search Everything and return full result paths."""
    if not isinstance(query, str):
        raise ValueError("Search query must be a string")
    options = dict(options or {})
    dll = dll_loader()
    _configure(dll)
    client = None
    state = None
    results = None
    try:
        for instance in (None, "1.5a"):
            client = dll.Everything3_ConnectW(instance)
            if client:
                break
        if not client:
            error = _sdk_error(dll)
            raise EverythingError(
                "Could not connect to Everything. Make sure Everything 1.5 is running "
                f"with IPC enabled (SDK error 0x{error:08X})."
            )
        state = dll.Everything3_CreateSearchState()
        if not state:
            raise EverythingError(f"Could not create search state (SDK error 0x{_sdk_error(dll):08X})")
        if not dll.Everything3_SetSearchTextW(state, query):
            raise EverythingError(f"Could not set search query (SDK error 0x{_sdk_error(dll):08X})")
        for option, function in (
            ("match_case", "Everything3_SetSearchMatchCase"),
            ("match_diacritics", "Everything3_SetSearchMatchDiacritics"),
            ("whole_word", "Everything3_SetSearchMatchWholeWords"),
            ("match_path", "Everything3_SetSearchMatchPath"),
            ("prefix", "Everything3_SetSearchMatchPrefix"),
            ("suffix", "Everything3_SetSearchMatchSuffix"),
            ("ignore_punctuation", "Everything3_SetSearchIgnorePunctuation"),
            ("ignore_whitespace", "Everything3_SetSearchWhitespace"),
            ("regex", "Everything3_SetSearchRegex"),
        ):
            if option in options:
                _call_bool(dll, function, state, bool(options[option]))
        sorts = options.get("sort")
        if sorts:
            if not dll.Everything3_ClearSearchSorts(state):
                raise EverythingError(f"Could not clear search sorts (SDK error 0x{_sdk_error(dll):08X})")
            for name, ascending in sorts:
                property_id = _SORT_PROPERTIES.get(name)
                if property_id is None:
                    logger.warning("Unsupported Everything bookmark sort field %r; ignoring it", name)
                    continue
                if not dll.Everything3_AddSearchSort(state, property_id, bool(ascending)):
                    raise EverythingError(f"Could not set search sort (SDK error 0x{_sdk_error(dll):08X})")
        results = dll.Everything3_Search(client, state)
        if not results:
            raise EverythingError(f"Everything search failed (SDK error 0x{_sdk_error(dll):08X})")
        count = int(dll.Everything3_GetResultListViewportCount(results))
        paths = []
        for index in range(count):
            if checkpoint is not None and index % 256 == 0:
                checkpoint()
            if progress is not None and index % 256 == 0:
                progress(index, count)
            path = _full_path(dll, results, index)
            if path:
                paths.append(path)
        if progress is not None:
            progress(count, count)
        return paths
    finally:
        if results:
            dll.Everything3_DestroyResultList(results)
        if state:
            dll.Everything3_DestroySearchState(state)
        if client:
            dll.Everything3_DestroyClient(client)
