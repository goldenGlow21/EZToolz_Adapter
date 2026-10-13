# EZToolz Adapter

EZToolz Adapter is a Windows workbench for forensic triage. It downloads
Eric Zimmerman's tools, Sysinternals utilities, Hayabusa, Chainsaw,
Volatility 3, RegRipper, ExifTool and others from their publishers. It
recognises the artifacts you put into an evidence folder and offers a menu
of investigative questions, such as "Which programs ran?". It runs the tools
that answer each question and opens their results in a fitting viewer. The
evidence itself is never modified: every tool works on a copy.

## Getting started

1. Get `EZToolzAdapter.exe` (see [Building the exe](#building-the-exe)) and put
   it in a folder you can write to, such as Documents or a USB drive. It keeps
   its tools, evidence and results in `tools`, `evidence` and `output` folders
   next to itself, so the whole kit can be copied as one folder.
2. Double-click it. Python does not need to be installed.
3. On the **Overview** page, press *Install recommended* (about 320 MB). The
   Tools page reports whether the .NET 9 runtimes that Eric Zimmerman's tools
   need are installed, and links the Microsoft download if they are not.

Requirements: Windows 10 or 11 (x64). Running from source instead of the exe
needs Python 3.10 or newer: `python -m eztadapter`.

## Working with it

The sidebar pages follow the order of the work.

- **Overview**: where the case stands, three steps to a first result, recent analyses.
- **Evidence**: copy files into the evidence folder in any structure; a KAPE
  or other triage collection works as is. Files are grouped by what they
  are, recognised by content rather than extension. Select files or groups to
  *Analyse these files* only, or to *Run a tool* of your choice on them.
- **Analyze**: the menu. Each card is one question; pick the ones you want and
  press *Run*. The details panel shows the evidence each analysis will use,
  lets you add or drop individual tools, and says how to read the results.
  Missing tools are downloaded first.
- **Results**: every analysis, with its tasks grouped by question, statuses,
  output files and logs. *Preview* shows CSV and text results inside the
  window (sortable, filterable); *Open* uses the best viewer: Timeline
  Explorer for CSV, Registry Explorer for hives, the browser for HTML reports.
- **Tools** and **Settings**: install, update, start or remove tools; move the
  evidence and output folders.

### The analysis menu

| Question | Tools ticked by default | Optional |
|---|---|---|
| Program execution | PECmd, AmcacheParser, AppCompatCacheParser, RecentFileCacheParser | |
| Files and folders opened | LECmd, JLECmd, SBECmd, SIDR | |
| Accounts and logons | Hayabusa logon summary, RECmd (SAM), SumECmd | |
| File system timeline | MFTECmd ($MFT, $Boot, $SDS, $I30, $J) | |
| Deleted files | RBCmd | MFTECmd ($J) |
| Application and network usage | SrumECmd, WxTCmd | Chainsaw SRUM |
| Browser and app databases | SQLECmd | |
| Threat detection | Hayabusa Sigma timeline | Chainsaw hunt |
| Event log review | EvtxECmd, Hayabusa event ID statistics, Chainsaw gap detection | |
| Executable triage | Sigcheck, Detect It Easy | FLOSS |
| Memory analysis | Volatility 3 (info, processes, command lines, network, services, malfind) | |
| Registry deep dive | RECmd Kroll batch | RegRipper report and TLN, rla |
| Document and media metadata | ExifTool | |
| Strings | bstrings | Sysinternals Strings |

A tool shared by several chosen analyses runs once over all of their inputs.

### Running any tool on any file

*Run a tool* on the Evidence page lists every tool. For each one it shows how
many of the selected files are its usual input. Files of other types can be
given to it on request, and a tool with no usual input among them always gets
all of them. When a tool cannot read such a file, its task reports the error
and the results list each file that was not a usual input.

## How the evidence stays intact

- Evidence files are only ever opened for reading.
- Before a task runs, its files are copied into a working folder inside the
  run folder. The copies keep their created, modified and accessed times, so
  parsers report the evidence's timestamps, not the copy's. The tool only
  sees the copy, and the copy is deleted when the task ends. Tools also get
  their `TEMP` folder inside that working folder, so temporary copies they
  make (bstrings copies its whole input) are deleted with it.
- Each copy is hashed while it is written. `run.json` records the SHA-256 of
  every input together with the exact command lines, exit codes and output
  files, so each result can be traced to the evidence that produced it.
- Viewers get a copy too, so Registry Explorer offering to save a replayed
  hive cannot touch the original. Evidence with no viewer is shown in
  Explorer rather than started, since it may be malware.
- Source paths inside tool output point to the working copy, for example
  `...\_staging\3\in\C\Windows\Prefetch\CMD.EXE-1.pf`. The part after `in\` is
  the file's location in the evidence folder.

Registry transaction logs (`.LOG1`, `.LOG2`) next to a hive are copied with it.
When a hive is dirty and its logs are missing, the task still runs and says
that the newest changes may be missing.

## Results

```
output/
  2026-10-14_153012/            one folder per analysis
    run.json                    inputs with SHA-256, commands, statuses
    pecmd/                      a task that processes all files at once
      job.log                   everything the tool printed
      20261014063012_PECmd_Output.csv
    mftecmd-ntfs/$MFT/          a task that processes one file at a time
```

Statuses: **OK**; **Warnings** (output was written but the tool reported an
error); **No output** (the tool ran but wrote nothing; the log says why);
**Failed**; **Skipped** (for example Chainsaw SRUM without a SOFTWARE hive);
**Cancelled**.

## Downloads and updates

Tools come from the publishers' own download sites or GitHub releases and are
unpacked into `tools/<tool>/`. A download is checked against the SHA-256 its
publisher states where there is one (GitHub release digests, ExifTool's
checksum list) and discarded on a mismatch. *Check for updates* compares the
installed builds with the newest ones. Each tool keeps its own licence; the
Sysinternals tools ask for their licence terms to be accepted once.

## Troubleshooting

- **Windows Security blocked a tool.** Detection tools contain malware
  signatures and rules, so antivirus software sometimes quarantines them. The
  adapter says so instead of reporting a broken download. Allow the file under
  Windows Security > Protection history, or add an exclusion for the tools
  folder, then install again.
- **GitHub rate limit.** GitHub allows 60 release lookups per hour from one
  address. The message gives the time it resets.
- **Volatility needs internet on first use** to download the Windows symbol
  tables that match the memory image.
- **A tool needs .NET 9.** Install the runtime from the link on the Tools page.
- **The exe cannot start in Program Files.** It writes its tools and results
  beside itself; move it to a folder you can write to.

## Extending the catalog

The catalog is data in `eztadapter/data/`:

- `artifacts.json`: how files are recognised (names, byte signatures, hive names).
- `tools.json`: where each tool is downloaded and how each of its actions is invoked.
- `tasks.json`: the analysis menu, mapping each question to actions.

A new tool is one entry in `tools.json` plus a step in the task it serves, for example:

```json
{
  "id": "MyParser",
  "group": "Other",
  "about": "What it does.",
  "homepage": "https://example.org/myparser",
  "source": {"kind": "github", "repo": "owner/myparser", "asset": "^myparser-.*-windows\\.zip$"},
  "exe": "myparser.exe",
  "actions": [
    {
      "id": "myparser",
      "label": "Parse something",
      "artifacts": ["prefetch"],
      "input": "folder",
      "steps": [{"args": ["--in", "{input}", "--out", "{output}"]}]
    }
  ]
}
```

The comments at the top of each file list every field and placeholder. The
catalog is validated at start-up, so a mistake is reported with the entry it
is in.

## Development

```
eztadapter/
  catalog.py      typed, validated view of the JSON catalog
  identify.py     artifact recognition from file name and header bytes
  evidence.py     evidence folder scanning
  planner.py      chosen tasks and tools -> jobs, with logs and companion files
  staging.py      timestamp-preserving, hashing copies of the evidence
  runner.py       runs jobs, collects outputs, writes run.json
  history.py      past runs read back from run.json
  installer.py    download, verification and unpacking of tools
  toolbox.py      installed state of each tool and the viewer for a file
  requirements.py .NET runtime detection
  workspace.py    folders and settings
  gui/            the window: theme, widgets and one module per page
tests/            unit, end-to-end and window tests with a stand-in tool
build.py          builds EZToolzAdapter.exe
```

Run the tests with:

```bash
python -m unittest discover -s tests
```

### Building the exe

```bash
python build.py
```

The script installs PyInstaller, pinned with hashes in
`build-requirements.txt`, into a throwaway virtual environment, and writes
`EZToolzAdapter.exe` next to itself. The adapter itself uses only the Python
standard library.
