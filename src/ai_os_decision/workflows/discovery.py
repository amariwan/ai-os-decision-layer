"""Bounded discovery of JSON exports, wrappers, datasets, JSONL and ZIP."""
from __future__ import annotations

import io
import json
import zipfile
import zlib
from pathlib import PurePosixPath

MAX_FILE = 64 * 1024 * 1024
MAX_ZIP_TOTAL = 512 * 1024 * 1024


def extract(value, pointer: str = "", depth: int = 0):
    if depth > 16:
        return
    if isinstance(value, dict):
        if isinstance(value.get("nodes"), list) and "connections" in value:
            yield pointer or "/", value
            return
        for key, child in value.items():
            yield from extract(child, pointer + "/" + str(key).replace("~", "~0").replace("/", "~1"), depth + 1)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from extract(child, pointer + "/" + str(index), depth + 1)
    elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            yield from extract(json.loads(value), pointer + "/@json", depth + 1)
        except (ValueError, RecursionError):
            pass


def documents(path: str, data: bytes):
    """Yield (logical path, bytes); archives are read in memory, never extracted."""
    if len(data) > MAX_FILE:
        yield path, None
        return
    if path.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                total = 0
                for member in archive.infolist():
                    name = PurePosixPath(member.filename)
                    if member.is_dir() or name.is_absolute() or ".." in name.parts or not name.suffix.lower() in {".json", ".jsonl"}:
                        continue
                    total += member.file_size
                    if member.file_size > MAX_FILE or total > MAX_ZIP_TOTAL:
                        yield path + "!" + member.filename, None
                        continue
                    try:
                        yield path + "!" + member.filename, archive.read(member)
                    except (zipfile.BadZipFile, RuntimeError, zlib.error, OSError, EOFError):
                        yield path + "!" + member.filename, None
        except (zipfile.BadZipFile, RuntimeError, zlib.error, OSError, EOFError):
            yield path, None
    elif path.lower().endswith((".json", ".jsonl")):
        yield path, data


def parse(path: str, data: bytes):
    if path.lower().endswith(".jsonl"):
        for index, line in enumerate(data.splitlines()):
            if line.strip():
                try:
                    yield from extract(json.loads(line), f"/line/{index + 1}")
                except (ValueError, RecursionError):
                    yield f"/line/{index + 1}", None
        return
    try:
        yield from extract(json.loads(data))
    except (ValueError, RecursionError):
        yield "/", None
