import unittest

from eztadapter.identify import classify, hive_embedded_name, hive_is_dirty

from helpers import catalog, hive_header, padded

LNK = bytes.fromhex("4C0000000114020000000000C000000000000046")
EVTX = b"ElfFile\x00"
SQLITE = b"SQLite format 3\x00"


def kind(name: str, header: bytes) -> str | None:
    artifact = classify(catalog(), name, header)
    return artifact.id if artifact else None


class RegistryTests(unittest.TestCase):
    def test_renamed_hive_is_recognised_by_its_embedded_name(self):
        self.assertEqual(kind("host1_user.bin", hive_header("\\??\\C:\\Users\\eric\\ntuser.dat")), "hive_ntuser")

    def test_hive_is_recognised_by_file_name_when_embedded_name_is_bare(self):
        self.assertEqual(kind("SYSTEM", hive_header("SYSTEM")), "hive_system")
        self.assertEqual(kind("SOFTWARE", hive_header("emRoot\\System32\\Config\\SOFTWARE")), "hive_software")

    def test_amcache_wins_over_generic_hive(self):
        self.assertEqual(kind("Amcache.hve", hive_header("\\??\\C:\\Windows\\AppCompat\\Programs\\Amcache.hve")), "hive_amcache")

    def test_transaction_log_is_not_mistaken_for_its_hive(self):
        self.assertEqual(kind("SYSTEM.LOG1", hive_header("SYSTEM")), "registry_log")
        self.assertEqual(kind("NTUSER.DAT.LOG2", b""), "registry_log")

    def test_text_log_named_dot_log_is_not_a_registry_log(self):
        self.assertIsNone(kind("setupapi.dev.log", b"[Device Install Log]\r\n"))

    def test_unknown_hive_falls_back_to_other_hive(self):
        self.assertEqual(kind("BCD", hive_header("\\Device\\HarddiskVolume1\\Boot\\BCD")), "hive_other")

    def test_embedded_name_and_dirty_flag(self):
        self.assertEqual(hive_embedded_name(hive_header("\\??\\C:\\Users\\eric\\ntuser.dat")), "ntuser.dat")
        self.assertIsNone(hive_embedded_name(b"MZ" + bytes(200)))
        self.assertTrue(hive_is_dirty(hive_header("SAM", dirty=True)))
        self.assertFalse(hive_is_dirty(hive_header("SAM", dirty=False)))
        self.assertFalse(hive_is_dirty(b"MZ"))


class FileSystemTests(unittest.TestCase):
    def test_ntfs_metadata_files_by_name(self):
        self.assertEqual(kind("$MFT", b""), "mft")
        self.assertEqual(kind("$J", bytes(64)), "usn_journal")
        self.assertEqual(kind("$UsnJrnl%3A$J", bytes(64)), "usn_journal")
        self.assertEqual(kind("$Boot", padded(b"\xebR\x90NTFS    ")), "ntfs_boot")
        self.assertEqual(kind("$Secure_$SDS", bytes(64)), "ntfs_sds")
        self.assertEqual(kind("$I30", bytes(64)), "ntfs_i30")

    def test_renamed_mft_is_recognised_by_record_signature(self):
        self.assertEqual(kind("mft_copy.bin", padded(b"FILE0")), "mft")

    def test_i30_is_not_taken_for_a_recycle_bin_record(self):
        self.assertEqual(kind("$I30", padded(b"\x02" + bytes(7))), "ntfs_i30")


class ExecutionAndAccessTests(unittest.TestCase):
    def test_prefetch_compressed_and_uncompressed(self):
        self.assertEqual(kind("CMD.EXE-D269B812.pf", padded(b"MAM\x04")), "prefetch")
        self.assertEqual(kind("renamed.bin", padded(b"SCCA", offset=4)), "prefetch")

    def test_pf_extension_alone_is_not_prefetch(self):
        self.assertIsNone(kind("fake.pf", padded(b"hello")))

    def test_lnk_by_header_even_when_renamed(self):
        self.assertEqual(kind("05 - Interface.docx.lnk.test", padded(LNK)), "lnk")

    def test_jumplists_by_name(self):
        self.assertEqual(kind("f01b4d95cf55d32a.automaticDestinations-ms", padded(bytes.fromhex("D0CF11E0A1B11AE1"))), "jumplist")
        self.assertEqual(kind("28c8b86deab549a1.customDestinations-ms", bytes(32)), "jumplist")

    def test_recycle_bin_records(self):
        self.assertEqual(kind("$I2JRX90", padded(b"\x02" + bytes(7))), "recycle_bin")
        self.assertEqual(kind("$IFATB0K.docx", padded(b"\x01" + bytes(7))), "recycle_bin")
        self.assertEqual(kind("INFO2", bytes(20)), "recycle_bin")

    def test_recentfilecache(self):
        self.assertEqual(kind("RecentFileCache.bcf", padded(bytes.fromhex("FEFFEEFF"))), "recentfilecache")


class DatabaseTests(unittest.TestCase):
    def test_named_sqlite_databases_win_over_generic_sqlite(self):
        self.assertEqual(kind("ActivitiesCache.db", padded(SQLITE)), "activities_cache")
        self.assertEqual(kind("Windows.db", padded(SQLITE)), "windows_search")
        self.assertEqual(kind("History", padded(SQLITE)), "sqlite")

    def test_ese_databases(self):
        ese = padded(bytes.fromhex("EFCDAB89"), offset=4)
        self.assertEqual(kind("SRUDB.dat", ese), "srum")
        self.assertEqual(kind("Windows.edb", ese), "windows_search")
        self.assertEqual(kind("Current.mdb", ese), "sum_ual")
        self.assertEqual(kind("{B3E2F1A0-0000-0000-0000-000000000000}.mdb", ese), "sum_ual")

    def test_event_log(self):
        self.assertEqual(kind("Security.evtx", padded(EVTX)), "evtx")
        self.assertEqual(kind("renamed", padded(EVTX)), "evtx")


class OtherTypesTests(unittest.TestCase):
    def test_memory_images(self):
        self.assertEqual(kind("MEMORY.DMP", padded(b"PAGEDU64")), "memory_image")
        self.assertEqual(kind("host.raw", bytes(64)), "memory_image")

    def test_executables(self):
        self.assertEqual(kind("evil.dll", padded(b"MZ")), "pe")

    def test_documents_need_matching_container_and_extension(self):
        self.assertEqual(kind("report.pdf", padded(b"%PDF-1.7")), "document")
        self.assertEqual(kind("report.docx", padded(b"PK\x03\x04")), "document")
        self.assertIsNone(kind("archive.zip", padded(b"PK\x03\x04")))
        self.assertEqual(kind("old.doc", padded(bytes.fromhex("D0CF11E0A1B11AE1"))), "document")

    def test_images(self):
        self.assertEqual(kind("photo.jpg", padded(b"\xff\xd8\xff\xe0")), "image_media")
        self.assertEqual(kind("clip.mp4", padded(b"ftypisom", offset=4)), "image_media")

    def test_unknown_file(self):
        self.assertIsNone(kind("notes.txt", b"just some text"))
        self.assertIsNone(kind("empty", b""))


if __name__ == "__main__":
    unittest.main()
