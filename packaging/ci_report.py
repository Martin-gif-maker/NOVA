"""Show the test result on the GitHub run page.

The test run writes every failure to test-failures.txt (see tests/conftest.py) and its output to test-output.txt.
On GitHub this script turns them into annotations on the run: the summary line ("591 passed, 35 skipped"), the
short reason of every failed test and, if the run broke off, its last lines - readable on the run's summary page
without opening the full log.   Usage: python packaging/ci_report.py"""
import os, sys

CHUNK = 1800           # characters per annotation
PER_KIND = 10          # GitHub shows at most ten annotations of each kind per step


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def _read(path: str) -> str:
    if not os.path.exists(path): return ""
    with open(path, encoding="utf-8", errors="replace") as f: return f.read().strip()


def main() -> int:
    system = f"{sys.platform} · Python {sys.version_info.major}.{sys.version_info.minor}"
    output, failures, selftest = _read("test-output.txt"), _read("test-failures.txt"), _read("selftest-output.txt")
    lines = [l for l in output.splitlines() if l.strip()]
    summary = next((l for l in reversed(lines) if " passed" in l or " failed" in l or " error" in l), "")
    if summary: print(f"::notice title=Tests ({system})::{_escape(summary.strip(' ='))}")
    if selftest: print(f"::notice title=Self-test ({system})::{_escape(selftest[-600:])}")
    if failures:
        chunks = [failures[i:i + CHUNK] for i in range(0, len(failures), CHUNK)]
        kinds = ["error"] * PER_KIND + ["warning"] * (PER_KIND - 1)
        for n, (kind, chunk) in enumerate(zip(kinds, chunks), 1):
            print(f"::{kind} title=Failed tests ({system}) {n}/{len(chunks)}::{_escape(chunk)}")
    if output and (not summary or "INTERNALERROR" in output or "Timeout" in output):
        print(f"::warning title=The test run broke off ({system}) - its last lines::{_escape(output[-CHUNK:])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
