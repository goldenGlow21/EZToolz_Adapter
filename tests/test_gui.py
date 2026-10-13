import json
import os
import time
import unittest

from eztadapter.gui.app import App
from eztadapter.gui.pages.evidence import ToolPicker
from eztadapter.workspace import Workspace

from helpers import catalog, temp_folder


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.home = temp_folder(self)
        prefetch = self.home / "evidence" / "C" / "Windows" / "Prefetch"
        os.makedirs(prefetch)
        (prefetch / "CMD.EXE-D269B812.pf").write_bytes(b"MAM\x04" + bytes(200))
        (self.home / "evidence" / "notes.txt").write_text("text", encoding="utf-8")
        self.app = App(Workspace.load(self.home), catalog())
        self.app.withdraw()
        self.addCleanup(self.app.destroy)
        deadline = time.monotonic() + 10
        while not self.app.items and time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.05)
        self.app.update()

    def test_opens_on_the_overview(self):
        self.assertEqual(self.app.current_page, "overview")

    def test_evidence_is_grouped_by_artifact_type(self):
        page = self.app.pages["evidence"]
        self.assertEqual(page.tree.get_children(), ("group:prefetch", "group:_unrecognised"))

    def test_menu_offers_only_analyses_with_matching_evidence(self):
        page = self.app.pages["analyze"]
        self.app.navigate("analyze")
        self.assertEqual(page.available["program-execution"], 1)
        self.assertEqual(page.available["filesystem-timeline"], 0)
        page.toggle(catalog().task("filesystem-timeline"))
        self.assertNotIn("filesystem-timeline", page.selected)
        page.toggle(catalog().task("program-execution"))
        self.assertEqual(page.selected, {"program-execution"})
        self.assertEqual(str(page.run_button.cget("state")), "normal")
        self.assertIn("1 analysis", page.summary.cget("text"))

    def test_choosing_files_narrows_the_scope(self):
        evidence = self.app.pages["evidence"]
        evidence.tree.selection_set("group:_unrecognised")
        self.app.update()
        evidence._analyse_selection()
        page = self.app.pages["analyze"]
        self.assertEqual(self.app.current_page, "analyze")
        self.assertEqual([item.name for item in self.app.scope_items()], ["notes.txt"])
        self.assertEqual(page.available["program-execution"], 0)
        self.assertEqual(page.available["strings"], 1)

    def test_any_tool_can_be_forced_onto_any_file(self):
        notes = [item for item in self.app.items if item.name == "notes.txt"]
        captured = {}
        self.app.start_run = lambda choices, task_ids, items: captured.update(choices=choices, items=items)
        picker = ToolPicker(self.app, notes)
        picker.grab_release()
        iid = next(iid for iid, action in picker.actions.items() if action.id == "pecmd")
        picker.tree.selection_set(iid)
        self.app.update()
        picker._run()
        self.assertTrue(captured["choices"][0].force)
        self.assertEqual(captured["items"], notes)

    def test_results_group_jobs_under_their_analysis(self):
        run = self.home / "output" / "2026-10-14_120000"
        os.makedirs(run / "pecmd")
        (run / "pecmd" / "out.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        manifest = {
            "run": run.name, "tasks": ["program-execution"], "finished": "2026-10-14T12:01:00",
            "jobs": [
                {"title": "PECmd: Parse prefetch (1 file)", "action": "pecmd", "status": "ok", "message": "",
                 "outputs": ["out.csv"], "warnings": [], "folder": "pecmd"},
                {"title": "Strings - notes.txt", "action": "strings", "status": "failed", "message": "broke",
                 "outputs": [], "warnings": [], "folder": "strings/notes.txt"},
            ],
        }
        (run / "run.json").write_text(json.dumps(manifest), encoding="utf-8")
        page = self.app.pages["results"]
        self.app.navigate("results")
        page.runs_changed()
        self.app.update()
        labels = [widget.cget("text") for widget in _labels(page.report.body)]
        self.assertIn("Program execution", labels)
        self.assertIn("Individual tools", labels)
        self.assertIn("out.csv", labels)


def _labels(widget):
    for child in widget.winfo_children():
        if child.winfo_class() == "Label":
            yield child
        yield from _labels(child)


if __name__ == "__main__":
    unittest.main()
