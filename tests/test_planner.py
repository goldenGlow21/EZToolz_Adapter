import unittest
from dataclasses import replace

from eztadapter.catalog import ANY_ARTIFACT, Action, Catalog, Source, Step, Tool
from eztadapter.planner import Choice, coverage, merge_choices, plan

from helpers import catalog, item


def choices(*ids):
    return [Choice(catalog().action(action_id)) for action_id in ids]


def task_defaults(*task_ids):
    """(task, ticked action ids) pairs as the menu produces them with default ticks."""
    tasks = [catalog().task(task_id) for task_id in task_ids]
    return [(task, [step.action_id for step in task.steps if step.default]) for task in tasks]


class GroupingTests(unittest.TestCase):
    def test_folder_action_gets_one_job_for_all_files(self):
        prefetch = [item(f"C/Windows/Prefetch/A{n}.pf", "prefetch") for n in range(3)]
        jobs = plan(catalog(), choices("pecmd"), prefetch, prefetch)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(len(jobs[0].inputs), 3)
        self.assertEqual(jobs[0].title, "PECmd: Parse prefetch (3 files)")

    def test_file_action_gets_one_job_per_file(self):
        mfts = [item("host1/C/$MFT", "mft"), item("host2/C/$MFT", "mft")]
        jobs = plan(catalog(), choices("mftecmd-ntfs"), mfts, mfts)
        self.assertEqual([job.inputs[0].rel for job in jobs], ["host1/C/$MFT", "host2/C/$MFT"])

    def test_action_only_receives_its_artifact_types(self):
        files = [item("a.pf", "prefetch"), item("b.lnk", "lnk")]
        jobs = plan(catalog(), choices("pecmd", "lecmd"), files, files)
        self.assertEqual({job.action.id: [i.name for i in job.inputs] for job in jobs}, {"pecmd": ["a.pf"], "lecmd": ["b.lnk"]})

    def test_any_file_action_accepts_unrecognised_files(self):
        unknown = [item("notes.txt", None)]
        jobs = plan(catalog(), choices("strings"), unknown, unknown)
        self.assertEqual(len(jobs), 1)

    def test_unreadable_files_are_never_planned(self):
        broken = replace(item("locked.pf", "prefetch"), error="Permission denied")
        self.assertEqual(plan(catalog(), choices("pecmd"), [broken], [broken]), [])
        self.assertEqual(coverage(choices("pecmd"), [broken]), [])


class ForcedChoiceTests(unittest.TestCase):
    def test_forced_tool_gets_files_of_any_type_and_flags_them(self):
        files = [item("a.pf", "prefetch"), item("notes.txt", None), item("photo.jpg", "image_media")]
        job = plan(catalog(), [Choice(catalog().action("pecmd"), force=True)], files, files)[0]
        self.assertEqual([i.name for i in job.inputs], ["a.pf", "notes.txt", "photo.jpg"])
        self.assertEqual([i.name for i in job.unexpected_inputs], ["notes.txt", "photo.jpg"])

    def test_forced_tool_still_skips_unreadable_files(self):
        broken = replace(item("locked.bin", None), error="Permission denied")
        self.assertEqual(plan(catalog(), [Choice(catalog().action("strings"), force=True)], [broken], [broken]), [])

    def test_usual_inputs_are_not_flagged(self):
        files = [item("a.pf", "prefetch")]
        job = plan(catalog(), [Choice(catalog().action("pecmd"), force=True)], files, files)[0]
        self.assertEqual(job.unexpected_inputs, ())


class TaskMenuTests(unittest.TestCase):
    def test_a_task_narrows_a_shared_action_to_its_artifacts(self):
        files = [item("C/config/SAM", "hive_sam"), item("C/Users/a/NTUSER.DAT", "hive_ntuser")]
        jobs = plan(catalog(), merge_choices(catalog(), task_defaults("accounts-logons")), files, files)
        recmd = [job for job in jobs if job.action.id == "recmd-batch"]
        self.assertEqual([i.name for i in recmd[0].inputs], ["SAM"])

    def test_tasks_sharing_an_action_run_it_once_over_the_union(self):
        files = [item("C/config/SAM", "hive_sam"), item("C/Users/a/NTUSER.DAT", "hive_ntuser")]
        merged = merge_choices(catalog(), task_defaults("accounts-logons", "registry-deep-dive"))
        recmd = [choice for choice in merged if choice.action.id == "recmd-batch"]
        self.assertEqual(len(recmd), 1)
        self.assertIsNone(recmd[0].artifacts)
        jobs = [job for job in plan(catalog(), merged, files, files) if job.action.id == "recmd-batch"]
        self.assertEqual(sorted(i.name for i in jobs[0].inputs), ["NTUSER.DAT", "SAM"])

    def test_unticked_steps_are_left_out(self):
        task = catalog().task("executable-triage")
        merged = merge_choices(catalog(), [(task, ["sigcheck"])])
        self.assertEqual([choice.action.id for choice in merged], ["sigcheck"])

    def test_coverage_counts_files_a_task_would_process(self):
        files = [item("a.pf", "prefetch"), item("b.lnk", "lnk"), item("x.txt", None)]
        merged = merge_choices(catalog(), task_defaults("program-execution"))
        self.assertEqual([i.name for i in coverage(merged, files)], ["a.pf"])


class RegistryLogTests(unittest.TestCase):
    def test_transaction_logs_follow_their_hive(self):
        hive = item("C/Users/a/NTUSER.DAT", "hive_ntuser", dirty=True)
        log1 = item("C/Users/a/ntuser.dat.LOG1", "registry_log")
        log2 = item("C/Users/a/ntuser.dat.LOG2", "registry_log")
        other_users_log = item("C/Users/b/ntuser.dat.LOG1", "registry_log")
        everything = [hive, log1, log2, other_users_log]
        job = plan(catalog(), choices("recmd-batch"), [hive], everything)[0]
        self.assertEqual({log.rel for log in job.sidecars}, {log1.rel, log2.rel})
        self.assertEqual(job.hives_without_logs, ())

    def test_dirty_hive_without_logs_is_flagged(self):
        hive = item("C/Windows/System32/config/SYSTEM", "hive_system", dirty=True)
        empty_log = item("C/Windows/System32/config/SYSTEM.LOG1", "registry_log", size=0)
        job = plan(catalog(), choices("appcompatcacheparser"), [hive], [hive, empty_log])[0]
        self.assertEqual(job.sidecars, ())
        self.assertEqual(job.hives_without_logs, (hive,))

    def test_log_selected_as_input_is_not_staged_twice(self):
        any_file = Action("all", "All", "T", (ANY_ARTIFACT,), "folder", (Step(("{input}",)),))
        tool = Tool("T", "g", "", "", Source("url", url="u"), "t.exe", (any_file,), False)
        local = Catalog(catalog().artifacts, (tool,), ())
        hive = item("C/SYSTEM", "hive_system", dirty=True)
        log = item("C/SYSTEM.LOG1", "registry_log")
        job = plan(local, [Choice(any_file)], [hive, log], [hive, log])[0]
        self.assertEqual(job.inputs, (hive, log))
        self.assertEqual(job.sidecars, ())
        self.assertEqual(job.hives_without_logs, ())

    def test_clean_hive_without_logs_is_not_flagged(self):
        hive = item("C/Windows/System32/config/SAM", "hive_sam", dirty=False)
        job = plan(catalog(), choices("recmd-batch"), [hive], [hive])[0]
        self.assertEqual(job.hives_without_logs, ())


class PairTests(unittest.TestCase):
    def test_pair_comes_from_the_same_machine(self):
        journal = item("host2/C/$Extend/$J", "usn_journal")
        everything = [item("host1/C/$MFT", "mft"), item("host2/C/$MFT", "mft"), journal]
        job = plan(catalog(), choices("mftecmd-usn"), [journal], everything)[0]
        self.assertEqual(job.pair.rel, "host2/C/$MFT")

    def test_pair_does_not_need_to_be_selected(self):
        srum = item("C/Windows/System32/sru/SRUDB.dat", "srum")
        software = item("C/Windows/System32/config/SOFTWARE", "hive_software")
        job = plan(catalog(), choices("srumecmd"), [srum], [srum, software])[0]
        self.assertEqual(job.pair, software)

    def test_optional_pair_missing_still_runs(self):
        journal = item("C/$Extend/$J", "usn_journal")
        job = plan(catalog(), choices("mftecmd-usn"), [journal], [journal])[0]
        self.assertIsNone(job.pair)
        self.assertIsNone(job.skip_reason)

    def test_required_pair_missing_skips_with_reason(self):
        srum = item("SRUDB.dat", "srum")
        job = plan(catalog(), choices("chainsaw-srum"), [srum], [srum])[0]
        self.assertIn("SOFTWARE", job.skip_reason)


class CatalogCoverageTests(unittest.TestCase):
    def test_every_artifact_type_is_handled_by_a_default_task_step(self):
        handled = set()
        for task in catalog().tasks:
            for step in task.steps:
                action = catalog().action(step.action_id)
                if step.default and ANY_ARTIFACT not in action.artifacts:
                    handled |= step.artifacts or set(action.artifacts)
        missing = {artifact.id for artifact in catalog().artifacts} - handled - {"registry_log"}
        self.assertEqual(missing, set())


if __name__ == "__main__":
    unittest.main()
