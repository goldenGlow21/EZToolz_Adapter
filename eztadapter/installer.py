"""Download, verify and unpack tools into the tools folder.

Each tool lives in tools/<tool id>/ next to a record of what was installed.
Installation is all-or-nothing: the download is unpacked into a temporary
folder and moved into place only after the tool's executable is found, so a
failed or interrupted install never leaves a half-working tool behind.

Security tools are often flagged by antivirus software because they contain
detection rules or offensive test data. When Windows Security blocks a file,
the error says so plainly instead of reporting a corrupt download.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Callable

from . import __version__
from .catalog import Source, Tool
from .fsutil import long_path, remove_tree

RECORD_NAME = ".install.json"
DOWNLOADS_DIR_NAME = ".downloads"
USER_AGENT = f"EZToolzAdapter/{__version__}"
GITHUB_API = "https://api.github.com"
_TIMEOUT = 60
_CHUNK = 256 * 1024
# Win32 errors raised when Windows Security blocks or removes a file as a threat.
_ANTIVIRUS_ERRORS = {225, 226}
_VERSION_RE = re.compile(r"^[0-9A-Za-z._-]{1,40}$")
_SHA256_RE = re.compile(r"\b[0-9a-fA-F]{64}\b")

Progress = Callable[[int, int | None], None]


class InstallError(Exception):
    """A tool could not be installed; the message says why and what to do."""


@dataclass(frozen=True)
class Release:
    """The newest downloadable build of a tool."""

    # Shown to people: a release tag, a version number or a publication date.
    version: str
    # Compared to decide whether an installed tool is out of date.
    fingerprint: str
    url: str
    file_name: str
    # Published by the vendor; None when the vendor publishes no hash.
    sha256: str | None = None


@dataclass(frozen=True)
class InstallRecord:
    version: str
    fingerprint: str
    url: str
    # SHA-256 of the downloaded file, whether or not the vendor published one.
    sha256: str
    installed: str
    # Paths inside the tool folder, found once at install time.
    exe: str
    gui: str | None = None


# Opens a URL and returns the response; tests replace it to avoid the network.
Fetch = Callable[..., object]


def http_open(url: str, method: str = "GET", accept: str | None = None):
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    request = urllib.request.Request(url, method=method, headers=headers)
    try:
        return urllib.request.urlopen(request, timeout=_TIMEOUT)
    except urllib.error.HTTPError as error:
        if url.startswith(GITHUB_API) and error.headers.get("X-RateLimit-Remaining") == "0":
            reset = datetime.fromtimestamp(int(error.headers.get("X-RateLimit-Reset", "0")))
            raise InstallError(
                f"GitHub allows 60 release lookups per hour from one address and that limit is used up. "
                f"It resets at {reset:%H:%M}; try again after that."
            ) from error
        raise InstallError(f"{url} answered HTTP {error.code} {error.reason}.") from error
    except urllib.error.URLError as error:
        raise InstallError(f"Cannot reach {url}: {error.reason}. Check the internet connection or proxy.") from error


def resolve(source: Source, fetch: Fetch = http_open) -> Release:
    """Find the newest release of a tool without downloading it."""
    if source.kind == "github":
        return _resolve_github(source, fetch)
    if source.kind == "versioned":
        return _resolve_versioned(source, fetch)
    return _resolve_url(source, fetch)


def _resolve_url(source: Source, fetch: Fetch) -> Release:
    with fetch(source.url, method="HEAD") as response:
        etag = response.headers.get("ETag", "")
        modified = response.headers.get("Last-Modified", "")
        final_url = response.geturl()
    version = parsedate_to_datetime(modified).strftime("%Y-%m-%d") if modified else "latest"
    file_name = PurePosixPath(urllib.request.urlparse(final_url).path).name or "download"
    return Release(version=version, fingerprint=etag or modified, url=source.url, file_name=file_name)


def _resolve_github(source: Source, fetch: Fetch) -> Release:
    with fetch(f"{GITHUB_API}/repos/{source.repo}/releases/latest", accept="application/vnd.github+json") as response:
        release = json.load(response)
    pattern = re.compile(source.asset)
    assets = [asset for asset in release.get("assets", []) if pattern.search(asset["name"])]
    if len(assets) != 1:
        names = ", ".join(asset["name"] for asset in release.get("assets", [])) or "none"
        raise InstallError(
            f"Release {release.get('tag_name')} of {source.repo} has {len(assets)} files matching "
            f"{source.asset!r} (expected 1). Files: {names}"
        )
    asset = assets[0]
    digest = asset.get("digest") or ""
    sha256 = digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None
    tag = release["tag_name"]
    return Release(version=tag, fingerprint=tag, url=asset["browser_download_url"], file_name=asset["name"], sha256=sha256)


def _resolve_versioned(source: Source, fetch: Fetch) -> Release:
    with fetch(source.version_url) as response:
        version = response.read(200).decode("ascii", errors="replace").strip()
    if not _VERSION_RE.match(version):
        raise InstallError(f"{source.version_url} returned an unexpected version string: {version[:40]!r}")
    file_name = source.file.replace("{version}", version)
    sha256 = None
    if source.sha256_url:
        with fetch(source.sha256_url.replace("{version}", version)) as response:
            listing = response.read(1_000_000).decode("utf-8", errors="replace")
        sha256 = _published_sha256(listing, file_name)
        if sha256 is None:
            raise InstallError(f"The vendor's checksum list does not include {file_name}.")
    return Release(
        version=version, fingerprint=version, url=source.url.replace("{version}", version), file_name=file_name, sha256=sha256
    )


def _published_sha256(listing: str, file_name: str) -> str | None:
    """Find the SHA-256 of file_name in a checksum list.

    Lists mix algorithms ("SHA2-256(f)= <hex>", "MD5 (f) = <hex>", "<hex>  f");
    a SHA-256 is the only one written as exactly 64 hex digits.
    """
    for line in listing.splitlines():
        if file_name in line:
            match = _SHA256_RE.search(line)
            if match:
                return match.group(0).lower()
    return None


def install(
    tool: Tool,
    release: Release,
    tools_dir: Path,
    progress: Progress,
    cancel: threading.Event,
    fetch: Fetch = http_open,
) -> InstallRecord:
    download_dir = tools_dir / DOWNLOADS_DIR_NAME / tool.id
    staging = tools_dir / f".{tool.id}.new"
    remove_tree(download_dir)
    remove_tree(staging)
    os.makedirs(long_path(download_dir))
    try:
        archive = download_dir / _safe_file_name(release.file_name)
        digest = _download(release.url, archive, progress, cancel, fetch)
        if release.sha256 and digest != release.sha256:
            raise InstallError(
                f"The download of {tool.id} does not match the SHA-256 the vendor published "
                f"({digest} instead of {release.sha256}). It was discarded; try again later."
            )
        exe, gui = _unpack(tool, archive, staging, tools_dir)
        record = InstallRecord(
            version=release.version,
            fingerprint=release.fingerprint,
            url=release.url,
            sha256=digest,
            installed=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            exe=exe,
            gui=gui,
        )
        (staging / RECORD_NAME).write_text(json.dumps(record.__dict__, indent=2), encoding="utf-8")
        _swap_into_place(tool, staging, tools_dir / tool.id)
        return record
    except OSError as error:
        if getattr(error, "winerror", None) in _ANTIVIRUS_ERRORS:
            raise InstallError(_antivirus_message(tool, tools_dir)) from error
        raise
    finally:
        remove_tree(download_dir)
        remove_tree(staging)
        downloads = tools_dir / DOWNLOADS_DIR_NAME
        if os.path.isdir(downloads) and not os.listdir(downloads):
            os.rmdir(downloads)


def _download(url: str, target: Path, progress: Progress, cancel: threading.Event, fetch: Fetch) -> str:
    digest = hashlib.sha256()
    with fetch(url) as response, open(long_path(target), "wb") as writer:
        length = response.headers.get("Content-Length")
        total = int(length) if length and length.isdigit() else None
        done = 0
        progress(done, total)
        while chunk := response.read(_CHUNK):
            if cancel.is_set():
                raise InstallError("Installation cancelled.")
            writer.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            progress(done, total)
    if total is not None and done != total:
        raise InstallError(f"The download stopped early ({done:,} of {total:,} bytes). Try again.")
    return digest.hexdigest()


def _unpack(tool: Tool, archive: Path, staging: Path, tools_dir: Path) -> tuple[str, str | None]:
    """Unpack into staging and return the exe and gui paths relative to it."""
    if not os.path.exists(long_path(archive)):
        raise InstallError(_antivirus_message(tool, tools_dir))
    os.makedirs(long_path(staging))
    if zipfile.is_zipfile(long_path(archive)):
        listed = _extract_zip(archive, staging, tool.source.exclude)
    else:
        if any(char in tool.exe for char in "*?["):
            raise InstallError(f"{tool.id}: a single-file download needs a literal exe name, not {tool.exe!r}.")
        target = staging / tool.exe
        with open(long_path(archive), "rb") as reader, open(long_path(target), "wb") as writer:
            while chunk := reader.read(_CHUNK):
                writer.write(chunk)
        listed = [tool.exe]

    for old_name, new_name in tool.source.rename:
        found = _find_files(staging, old_name)
        if not found:
            raise InstallError(f"{tool.id}: expected {old_name} in the download to rename it, but it is missing.")
        os.replace(long_path(found[0]), long_path(found[0].with_name(new_name)))
        listed.append(new_name)

    paths = []
    for pattern in (tool.exe, tool.gui):
        if pattern is None:
            paths.append(None)
            continue
        found = _find_files(staging, pattern)
        if not found:
            if any(fnmatchcase(PurePosixPath(name).name.casefold(), pattern.casefold()) for name in listed):
                raise InstallError(_antivirus_message(tool, tools_dir))
            raise InstallError(f"The download of {tool.id} does not contain {pattern}. The vendor may have changed its layout.")
        paths.append(Path(os.path.relpath(found[0], long_path(staging))).as_posix())
    return paths[0], paths[1]


def _extract_zip(archive: Path, staging: Path, exclude: tuple[str, ...]) -> list[str]:
    """Extract every member, refusing any whose path would escape the target folder."""
    listed = []
    with zipfile.ZipFile(long_path(archive)) as bundle:
        for member in bundle.infolist():
            name = member.filename.replace("\\", "/")
            if any(fnmatchcase(name, pattern) for pattern in exclude):
                continue
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
                raise InstallError(f"The archive contains an unsafe path {member.filename!r}; it was not installed.")
            if member.is_dir():
                continue
            target = staging.joinpath(*parts)
            os.makedirs(long_path(target.parent), exist_ok=True)
            with bundle.open(member) as reader, open(long_path(target), "wb") as writer:
                while chunk := reader.read(_CHUNK):
                    writer.write(chunk)
            listed.append(name)
    return listed


def _swap_into_place(tool: Tool, staging: Path, final: Path) -> None:
    previous = final.with_name(f".{tool.id}.old")
    remove_tree(previous)
    if os.path.exists(long_path(final)):
        try:
            os.replace(long_path(final), long_path(previous))
        except PermissionError as error:
            raise InstallError(f"{tool.id} is in use. Close it and try again.") from error
    os.replace(long_path(staging), long_path(final))
    remove_tree(previous)


def _antivirus_message(tool: Tool, tools_dir: Path) -> str:
    return (
        f"Windows Security blocked or removed {tool.id} as a threat. Forensic tools are often flagged because "
        f"they contain detection rules. To use it, allow it under Windows Security > Protection history, or add "
        f"an exclusion for {tools_dir}, then install again."
    )


def _safe_file_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name) or "download"


def _find_files(root: Path, pattern: str) -> list[Path]:
    found = []
    top = long_path(root)
    for current, subfolders, files in os.walk(top):
        subfolders.sort()
        for file_name in sorted(files):
            if fnmatchcase(file_name.casefold(), pattern.casefold()):
                found.append(Path(os.path.join(current, file_name)))
    # Shallowest first, so a tool's main exe wins over copies in subfolders.
    return sorted(found, key=lambda path: (len(path.parts), str(path).casefold()))


def read_record(tool: Tool, tools_dir: Path) -> InstallRecord | None:
    path = tools_dir / tool.id / RECORD_NAME
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return InstallRecord(**data)


def uninstall(tool: Tool, tools_dir: Path) -> None:
    folder = tools_dir / tool.id
    try:
        remove_tree(folder)
    except PermissionError as error:
        raise InstallError(f"{tool.id} is in use. Close it and try again.") from error
