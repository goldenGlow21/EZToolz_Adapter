"""Stand-in for a forensic tool, driven by the runner tests.

Usage: fake_tool.py <behaviour> <input> <output>

Behaviours mirror what real tools do: write a result file, print without
writing anything, exit with an error, print the result to stdout, try to
modify their input, or run until stopped.
"""

import os
import sys
import time


def main() -> int:
    behaviour, source, output = sys.argv[1], sys.argv[2], sys.argv[3]
    files = [source] if os.path.isfile(source) else [
        os.path.join(folder, name) for folder, _, names in os.walk(source) for name in names
    ]
    print(f"fake tool saw {len(files)} file(s)", file=sys.stderr, flush=True)
    if behaviour == "write":
        with open(os.path.join(output, "result.csv"), "w", encoding="utf-8") as handle:
            handle.write("file,size\n")
            for path in files:
                handle.write(f"{os.path.relpath(path, source if os.path.isdir(source) else os.path.dirname(source))},{os.path.getsize(path)}\n")
        return 0
    if behaviour == "misnamed":
        with open(os.path.join(output, "C_analystpc_NTUSER.DAT"), "wb") as handle:
            handle.write(b"regf")
        return 0
    if behaviour == "nothing":
        print("Registry hive is dirty and no transaction logs were found. Aborting!!")
        return 0
    if behaviour == "fail":
        print("something broke", file=sys.stderr)
        return 3
    if behaviour == "partial":
        with open(os.path.join(output, "partial.csv"), "w", encoding="utf-8") as handle:
            handle.write("a,b\n1,2\n")
        return 2
    if behaviour == "stdout":
        sys.stdout.write("line one\nline two\n")
        return 0
    if behaviour == "stdout-error":
        sys.stdout.write("Unsatisfied requirement plugins.Info.kernel.layer_name\n")
        return 1
    if behaviour == "stdout-utf16":
        sys.stdout.buffer.write("Path,Verified\nC:\\x.exe,Signed\n".encode("utf-16-le"))
        return 0
    if behaviour == "tamper":
        for path in files:
            with open(path, "ab") as handle:
                handle.write(b"tampered")
        with open(os.path.join(output, "tampered.txt"), "w", encoding="utf-8") as handle:
            handle.write("done\n")
        return 0
    if behaviour == "stdin":
        data = sys.stdin.buffer.read()
        with open(os.path.join(output, "stdin.txt"), "w", encoding="utf-8") as handle:
            handle.write(f"{len(data)} bytes, starts {data[:4].hex()}\n")
        return 0
    if behaviour == "temp":
        temp = os.environ["TEMP"]
        with open(os.path.join(temp, "scratch.tmp"), "wb") as handle:
            handle.write(b"copy of evidence")
        with open(os.path.join(output, "temp.txt"), "w", encoding="utf-8") as handle:
            handle.write(temp)
        return 0
    if behaviour == "sleep":
        print("working", flush=True)
        time.sleep(60)
        return 0
    raise SystemExit(f"unknown behaviour {behaviour}")


if __name__ == "__main__":
    sys.exit(main())
