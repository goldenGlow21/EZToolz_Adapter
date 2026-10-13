import hashlib
import os
import time
import unittest
from pathlib import Path

from eztadapter.evidence import Scanner
from eztadapter.fsutil import long_path
from eztadapter.planner import Choice, plan
from eztadapter.staging import copy_evidence, stage

from helpers import catalog, hive_header, temp_folder

OLD_NS = 1_600_000_000_123_456_700  # 2020-09-13, well before the test runs


def write(path: Path, data: bytes, when_ns: int = OLD_NS) -> Path:
    os.makedirs(long_path(path.parent), exist_ok=True)
    with open(long_path(path), "wb") as handle:
        handle.write(data)
    os.utime(long_path(path), ns=(when_ns, when_ns))
    return path


class CopyEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = temp_folder(self)

    def test_copy_has_same_bytes_and_returns_its_sha256(self):
        source = write(self.folder / "src" / "$MFT", b"FILE0" + os.urandom(5000))
        digest = copy_evidence(source, self.folder / "dst" / "$MFT")
        self.assertEqual((self.folder / "dst" / "$MFT").read_bytes(), source.read_bytes())
        self.assertEqual(digest, hashlib.sha256(source.read_bytes()).hexdigest())

    def test_copy_keeps_modified_accessed_and_created_times(self):
        source = write(self.folder / "a.pf", b"MAM\x04data")
        before = os.stat(source)
        time.sleep(0.05)
        copy_evidence(source, self.folder / "copy" / "a.pf")
        copied = os.stat(self.folder / "copy" / "a.pf")
        self.assertEqual(copied.st_mtime_ns // 100, before.st_mtime_ns // 100)
        self.assertEqual(copied.st_atime_ns // 100, before.st_atime_ns // 100)
        if os.name == "nt":
            self.assertEqual(copied.st_birthtime_ns // 100, before.st_birthtime_ns // 100)

    def test_copy_never_overwrites(self):
        source = write(self.folder / "x", b"1")
        write(self.folder / "existing" / "x", b"2")
        with self.assertRaises(FileExistsError):
            copy_evidence(source, self.folder / "existing" / "x")

    def test_original_is_unchanged(self):
        source = write(self.folder / "SYSTEM", hive_header("SYSTEM"))
        before = (source.read_bytes(), os.stat(source).st_mtime_ns)
        copy_evidence(source, self.folder / "out" / "SYSTEM")
        self.assertEqual((source.read_bytes(), os.stat(source).st_mtime_ns), before)


class StageLayoutTests(unittest.TestCase):
    def setUp(self):
        self.root = temp_folder(self)
        self.evidence = self.root / "evidence"

    def scan(self):
        return Scanner(catalog()).scan(self.evidence)

    def test_folder_action_keeps_the_evidence_tree(self):
        write(self.evidence / "u1" / "Recent" / "a.lnk", bytes.fromhex("4C0000000114020000000000C000000000000046"))
        write(self.evidence / "u2" / "Recent" / "a.lnk", bytes.fromhex("4C0000000114020000000000C000000000000046"))
        items = self.scan()
        job = plan(catalog(), [Choice(catalog().action("lecmd"))], items, items)[0]
        staged = stage(job, self.root / "staging")
        self.assertEqual(staged.input, self.root / "staging" / "in")
        self.assertTrue((staged.input / "u1" / "Recent" / "a.lnk").is_file())
        self.assertTrue((staged.input / "u2" / "Recent" / "a.lnk").is_file())

    def test_file_action_gets_logs_beside_the_hive_and_pair_apart(self):
        write(self.evidence / "C" / "Windows" / "System32" / "sru" / "SRUDB.dat", bytes(4) + bytes.fromhex("EFCDAB89"))
        write(self.evidence / "C" / "Windows" / "System32" / "config" / "SOFTWARE", hive_header("SOFTWARE", dirty=True))
        write(self.evidence / "C" / "Windows" / "System32" / "config" / "SOFTWARE.LOG1", b"regf-log")
        items = self.scan()
        srum = [i for i in items if i.name == "SRUDB.dat"]
        job = plan(catalog(), [Choice(catalog().action("srumecmd"))], srum, items)[0]
        staged = stage(job, self.root / "staging")
        self.assertEqual(staged.input, self.root / "staging" / "in" / "SRUDB.dat")
        self.assertEqual(staged.pair, self.root / "staging" / "pair" / "SOFTWARE")
        self.assertTrue((self.root / "staging" / "pair" / "SOFTWARE.LOG1").is_file())
        self.assertEqual({f.role for f in staged.files}, {"input", "pair", "sidecar"})

    def test_paths_longer_than_260_characters(self):
        deep = self.evidence.joinpath(*["very_long_folder_name_" + str(n) for n in range(12)])
        write(deep / "Security.evtx", b"ElfFile\x00" + bytes(100))
        self.assertGreater(len(str(deep / "Security.evtx")), 260)
        items = self.scan()
        self.assertEqual(items[0].artifact.id, "evtx")
        job = plan(catalog(), [Choice(catalog().action("evtxecmd"))], items, items)[0]
        staged = stage(job, self.root / "staging")
        self.assertEqual(len(staged.files), 1)
        self.assertTrue(os.path.isfile(long_path(staged.files[0].staged)))


if __name__ == "__main__":
    unittest.main()
