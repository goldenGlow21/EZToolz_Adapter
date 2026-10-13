import json
import shutil
import unittest
from pathlib import Path

from eztadapter.catalog import CATALOG_DIR, CatalogError, load_catalog
from eztadapter.workspace import Workspace, folder_conflict

from helpers import temp_folder


class CatalogValidationTests(unittest.TestCase):
    def setUp(self):
        self.folder = temp_folder(self)
        for name in ("artifacts.json", "tools.json", "tasks.json"):
            shutil.copy(CATALOG_DIR / name, self.folder / name)
        self.tools = json.loads((self.folder / "tools.json").read_text(encoding="utf-8"))
        self.tasks = json.loads((self.folder / "tasks.json").read_text(encoding="utf-8"))

    def load_error(self) -> str:
        (self.folder / "tools.json").write_text(json.dumps(self.tools), encoding="utf-8")
        (self.folder / "tasks.json").write_text(json.dumps(self.tasks), encoding="utf-8")
        with self.assertRaises(CatalogError) as raised:
            load_catalog(self.folder)
        return str(raised.exception)

    def broken_action(self, mutate) -> str:
        mutate(self.tools["tools"][1]["actions"][0])
        return self.load_error()

    def test_shipped_catalog_is_valid(self):
        catalog = load_catalog()
        self.assertGreater(len(catalog.tools), 30)
        self.assertGreater(len(catalog.tasks), 10)

    def test_unknown_placeholder_is_rejected(self):
        self.assertIn("{inptu}", self.broken_action(lambda action: action["steps"][0]["args"].append("{inptu}")))

    def test_name_placeholder_in_folder_action_is_rejected(self):
        self.assertIn("{name}", self.broken_action(lambda action: action["steps"][0]["args"].append("{name}")))

    def test_unknown_artifact_is_rejected(self):
        self.assertIn("prefech", self.broken_action(lambda action: action.update(artifacts=["prefech"])))

    def test_misspelled_key_is_rejected(self):
        self.assertIn("recomended", self.broken_action(lambda action: action.update(recomended=True)))

    def test_task_with_unknown_action_is_rejected(self):
        self.tasks["tasks"][0]["steps"].append({"action": "no-such-action", "default": False})
        self.assertIn("no-such-action", self.load_error())

    def test_task_narrowing_to_artifacts_the_action_cannot_read_is_rejected(self):
        self.tasks["tasks"][0]["steps"][0]["artifacts"] = ["evtx"]
        self.assertIn("does not accept", self.load_error())

    def test_action_missing_from_every_task_is_rejected(self):
        for task in self.tasks["tasks"]:
            task["steps"] = [step for step in task["steps"] if step["action"] != "floss"]
        self.assertIn("floss", self.load_error())

    def test_viewer_entry_must_be_extension_or_artifact(self):
        viewer = next(tool for tool in self.tools["tools"] if tool["id"] == "TimelineExplorer")
        viewer["views"].append("spreadsheet")
        self.assertIn("spreadsheet", self.load_error())

    def test_recommended_tools_follow_the_menu_defaults(self):
        catalog = load_catalog()
        self.assertTrue(catalog.tool("PECmd").recommended)
        self.assertFalse(catalog.tool("FLOSS").recommended)
        self.assertTrue(catalog.tool("TimelineExplorer").recommended)


class WorkspaceTests(unittest.TestCase):
    def test_defaults_live_under_home(self):
        home = temp_folder(self)
        workspace = Workspace.load(home)
        self.assertEqual(workspace.evidence_dir, home.resolve() / "evidence")
        self.assertTrue(workspace.tools_dir.is_dir() and workspace.evidence_dir.is_dir())

    def test_settings_round_trip(self):
        home = temp_folder(self)
        workspace = Workspace.load(home)
        workspace.change_folders(home / "case1" / "in", home / "case1" / "out")
        workspace.accepted_licenses.add("https://licence")
        workspace.save()
        again = Workspace.load(home)
        self.assertEqual(again.evidence_dir, (home / "case1" / "in").resolve())
        self.assertEqual(again.accepted_licenses, {"https://licence"})

    def test_nested_folders_are_refused(self):
        root = Path("D:/case")
        tools = Path("C:/adapter/tools")
        self.assertIsNotNone(folder_conflict(root, root / "output", tools))
        self.assertIsNotNone(folder_conflict(root / "evidence", root, tools))
        self.assertIsNotNone(folder_conflict(root, root, tools))
        self.assertIsNotNone(folder_conflict(Path("C:/adapter"), root, tools))
        self.assertIsNone(folder_conflict(root / "evidence", root / "output", tools))


if __name__ == "__main__":
    unittest.main()
