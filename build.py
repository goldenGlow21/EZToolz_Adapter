"""Build EZToolzAdapter.exe: one file that runs on Windows without Python installed.

Usage: python build.py

PyInstaller and its dependencies, pinned with hashes in build-requirements.txt,
are installed into a throwaway virtual environment under the system temp
folder, so the Python installation running this script is left unchanged. The
temp folder is short on purpose: PyInstaller's hook files have long names and
break the 260 character path limit inside deep folders. The finished exe is
written next to this script; everything else is deleted.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXE_NAME = "EZToolzAdapter"

sys.path.insert(0, str(ROOT))
from eztadapter import __version__  # noqa: E402
from eztadapter.fsutil import remove_tree  # noqa: E402

# Shown in the exe's Properties > Details tab.
VERSION_RESOURCE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', 'EZToolz Adapter'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', '{name}'),
      StringStruct('OriginalFilename', '{name}.exe'),
      StringStruct('ProductName', 'EZToolz Adapter'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

ENTRY_SCRIPT = """import sys

from eztadapter.__main__ import main

sys.exit(main())
"""


def main() -> int:
    if sys.platform != "win32":
        print("The exe can only be built on Windows.", file=sys.stderr)
        return 1
    work = Path(tempfile.mkdtemp(prefix="ezta-"))
    try:
        python = _virtual_environment(work)
        exe = _pyinstaller(python, work)
        target = ROOT / f"{EXE_NAME}.exe"
        try:
            shutil.copy2(exe, target)
        except PermissionError:
            print(f"{target} is in use. Close EZToolz Adapter and run the build again.", file=sys.stderr)
            return 1
        print(f"Built {target} ({target.stat().st_size / 1_000_000:.1f} MB)")
        return 0
    except subprocess.CalledProcessError as error:
        print(f"Build step failed with exit code {error.returncode}: {' '.join(map(str, error.cmd))}", file=sys.stderr)
        return 1
    finally:
        remove_tree(work)


def _virtual_environment(work: Path) -> Path:
    print("Creating a build environment...")
    subprocess.run([sys.executable, "-m", "venv", str(work / "venv")], check=True)
    python = work / "venv" / "Scripts" / "python.exe"
    print("Installing PyInstaller (pinned, hash-checked)...")
    subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--quiet", "--only-binary", ":all:",
         "--require-hashes", "-r", str(ROOT / "build-requirements.txt")],
        check=True,
    )
    return python


def _pyinstaller(python: Path, work: Path) -> Path:
    numbers = tuple(int(part) for part in __version__.split(".")) + (0,)
    (work / "version.txt").write_text(
        VERSION_RESOURCE.format(numbers=numbers, version=__version__, name=EXE_NAME), encoding="utf-8"
    )
    (work / "entry.py").write_text(ENTRY_SCRIPT, encoding="utf-8")
    package = ROOT / "eztadapter"
    print("Bundling with PyInstaller...")
    subprocess.run(
        [
            str(python), "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed", "--log-level", "WARN",
            "--name", EXE_NAME,
            "--icon", str(package / "assets" / "app.ico"),
            "--version-file", str(work / "version.txt"),
            "--add-data", f"{package / 'data'};eztadapter/data",
            "--add-data", f"{package / 'assets'};eztadapter/assets",
            "--paths", str(ROOT),
            "--distpath", str(work / "dist"),
            "--workpath", str(work / "build"),
            "--specpath", str(work),
            str(work / "entry.py"),
        ],
        check=True,
    )
    return work / "dist" / f"{EXE_NAME}.exe"


if __name__ == "__main__":
    sys.exit(main())
