import functools
import hashlib
import http.server
import io
import json
import threading
import unittest
import zipfile
from pathlib import Path

from eztadapter.catalog import Source, Tool
from eztadapter.installer import (
    RECORD_NAME,
    InstallError,
    Release,
    _published_sha256,
    install,
    read_record,
    resolve,
)

from helpers import temp_folder


def make_zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def tool(exe="Tool.exe", gui=None, exclude=(), rename=()) -> Tool:
    return Tool(
        id="Tool",
        group="Test",
        about="",
        homepage="",
        source=Source(kind="url", url="http://unused", exclude=exclude, rename=rename),
        exe=exe,
        actions=(),
        recommended=False,
        gui=gui,
    )


class LocalServer:
    """Serves files from a folder on 127.0.0.1, like a vendor download site."""

    def __init__(self, folder: Path):
        handler = functools.partial(_QuietHandler, directory=str(folder))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def url(self, name: str) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/{name}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.site = temp_folder(self)
        self.tools = temp_folder(self)
        self.server = LocalServer(self.site)
        self.addCleanup(self.server.close)

    def publish(self, name: str, data: bytes, sha256: str | None = None) -> Release:
        (self.site / name).write_bytes(data)
        return Release(version="1.0", fingerprint="1.0", url=self.server.url(name), file_name=name, sha256=sha256)

    def install(self, release: Release, spec: Tool | None = None):
        return install(spec or tool(), release, self.tools, lambda done, total: None, threading.Event())

    def test_zip_is_unpacked_and_exe_recorded(self):
        release = self.publish("Tool.zip", make_zip({"Tool/Tool.exe": b"MZ", "Tool/Maps/a.map": b"x"}))
        record = self.install(release)
        self.assertEqual(record.exe, "Tool/Tool.exe")
        self.assertTrue((self.tools / "Tool" / "Tool" / "Maps" / "a.map").is_file())
        self.assertEqual(read_record(tool(), self.tools), record)
        self.assertFalse((self.tools / ".downloads").exists())

    def test_wildcard_exe_and_gui(self):
        release = self.publish("h.zip", make_zip({"hayabusa-4.2.0-win-x64.exe": b"MZ", "gui/die.exe": b"MZ"}))
        record = self.install(release, tool(exe="hayabusa-*-win-x64.exe", gui="die.exe"))
        self.assertEqual((record.exe, record.gui), ("hayabusa-4.2.0-win-x64.exe", "gui/die.exe"))

    def test_excluded_members_are_not_extracted(self):
        archive = make_zip({"c/c.exe": b"MZ", "c/EVTX-ATTACK-SAMPLES/x.evtx": b"E", "c/sigma/linux/r.yml": b"r"})
        self.install(self.publish("c.zip", archive), tool(exe="c.exe", exclude=("*/EVTX-ATTACK-SAMPLES/*",)))
        self.assertFalse((self.tools / "Tool" / "c" / "EVTX-ATTACK-SAMPLES").exists())
        self.assertTrue((self.tools / "Tool" / "c" / "sigma" / "linux" / "r.yml").is_file())

    def test_rename_after_unpacking(self):
        archive = make_zip({"exiftool-13.59_64/exiftool(-k).exe": b"MZ"})
        record = self.install(self.publish("e.zip", archive), tool(exe="exiftool.exe", rename=(("exiftool(-k).exe", "exiftool.exe"),)))
        self.assertEqual(record.exe, "exiftool-13.59_64/exiftool.exe")

    def test_single_file_download_becomes_the_exe(self):
        record = self.install(self.publish("sidr.exe", b"MZ-not-a-zip"), tool(exe="sidr.exe"))
        self.assertEqual((self.tools / "Tool" / record.exe).read_bytes(), b"MZ-not-a-zip")

    def test_path_traversal_in_archive_is_refused(self):
        release = self.publish("evil.zip", make_zip({"../escape.exe": b"MZ", "Tool.exe": b"MZ"}))
        with self.assertRaises(InstallError):
            self.install(release)
        self.assertFalse((self.tools / "Tool").exists())
        self.assertFalse((self.tools.parent / "escape.exe").exists())

    def test_hash_mismatch_discards_the_download(self):
        release = self.publish("Tool.zip", make_zip({"Tool.exe": b"MZ"}), sha256="0" * 64)
        with self.assertRaisesRegex(InstallError, "SHA-256"):
            self.install(release)
        self.assertFalse((self.tools / "Tool").exists())

    def test_matching_vendor_hash_is_accepted(self):
        data = make_zip({"Tool.exe": b"MZ"})
        record = self.install(self.publish("Tool.zip", data, sha256=hashlib.sha256(data).hexdigest()))
        self.assertEqual(record.sha256, hashlib.sha256(data).hexdigest())

    def test_missing_exe_names_the_problem(self):
        with self.assertRaisesRegex(InstallError, "does not contain Tool.exe"):
            self.install(self.publish("Tool.zip", make_zip({"readme.txt": b"hi"})))

    def test_reinstall_replaces_the_previous_version(self):
        self.install(self.publish("v1.zip", make_zip({"Tool.exe": b"v1", "old-only.txt": b"x"})))
        self.install(self.publish("v2.zip", make_zip({"Tool.exe": b"v2"})))
        self.assertEqual((self.tools / "Tool" / "Tool.exe").read_bytes(), b"v2")
        self.assertFalse((self.tools / "Tool" / "old-only.txt").exists())
        self.assertTrue((self.tools / "Tool" / RECORD_NAME).is_file())

    def test_url_source_version_comes_from_last_modified(self):
        (self.site / "Tool.zip").write_bytes(b"data")
        release = resolve(Source(kind="url", url=self.server.url("Tool.zip")))
        self.assertRegex(release.version, r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(release.file_name, "Tool.zip")


class FakeResponse(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {}


def fake_fetch(pages: dict[str, bytes]):
    def fetch(url, method="GET", accept=None):
        return FakeResponse(pages[url])

    return fetch


class ResolveTests(unittest.TestCase):
    def test_github_release_with_published_digest(self):
        api = {
            "tag_name": "v4.2.0",
            "assets": [
                {"name": "hayabusa-4.2.0-win-x64.zip", "browser_download_url": "https://x/h.zip", "digest": "sha256:" + "ab" * 32},
                {"name": "hayabusa-4.2.0-win-x64-live-response.zip", "browser_download_url": "https://x/l.zip"},
            ],
        }
        fetch = fake_fetch({"https://api.github.com/repos/Y/hayabusa/releases/latest": json.dumps(api).encode()})
        release = resolve(Source(kind="github", repo="Y/hayabusa", asset=r"^hayabusa-[0-9.]+-win-x64\.zip$"), fetch)
        self.assertEqual((release.version, release.url, release.sha256), ("v4.2.0", "https://x/h.zip", "ab" * 32))

    def test_github_release_with_ambiguous_assets_is_refused(self):
        api = {"tag_name": "v1", "assets": [{"name": "a.zip", "browser_download_url": "u"}, {"name": "b.zip", "browser_download_url": "u"}]}
        fetch = fake_fetch({"https://api.github.com/repos/o/r/releases/latest": json.dumps(api).encode()})
        with self.assertRaisesRegex(InstallError, "2 files matching"):
            resolve(Source(kind="github", repo="o/r", asset=r"\.zip$"), fetch)

    def test_versioned_source_reads_version_and_vendor_checksum(self):
        checksums = (
            "SHA1(exiftool-13.59_64.zip)= 022b902bb3d01b171d5108e2c4be59491eb64444\n"
            "SHA2-256(exiftool-13.59_64.zip)= 44b512b25af500724ba579d0a53c8fc5851628b692dd5e5d94ae4a15c2cba9ec\n"
            "MD5 (exiftool-13.59_64.zip) = df4fa1b736f0b8d39bd09b15fbdb865c\n"
        )
        fetch = fake_fetch({"https://e/ver.txt": b"13.59\n", "https://e/checksums-13.59.txt": checksums.encode()})
        source = Source(
            kind="versioned",
            version_url="https://e/ver.txt",
            url="https://dl/exiftool-{version}_64.zip/download",
            file="exiftool-{version}_64.zip",
            sha256_url="https://e/checksums-{version}.txt",
        )
        release = resolve(source, fetch)
        self.assertEqual(release.url, "https://dl/exiftool-13.59_64.zip/download")
        self.assertEqual(release.sha256, "44b512b25af500724ba579d0a53c8fc5851628b692dd5e5d94ae4a15c2cba9ec")

    def test_versioned_source_rejects_garbage_version(self):
        fetch = fake_fetch({"https://e/ver.txt": b"<html>error page</html>"})
        source = Source(kind="versioned", version_url="https://e/ver.txt", url="u", file="f")
        with self.assertRaises(InstallError):
            resolve(source, fetch)

    def test_sha256sum_format_is_understood(self):
        listing = f"{'cd' * 32}  tool.zip\n{'ef' * 32}  other.zip\n"
        self.assertEqual(_published_sha256(listing, "tool.zip"), "cd" * 32)
        self.assertIsNone(_published_sha256(listing, "missing.zip"))


if __name__ == "__main__":
    unittest.main()
