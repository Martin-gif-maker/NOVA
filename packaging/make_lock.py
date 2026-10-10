#!/usr/bin/env python3
"""Rewrite requirements.lock from the environment this runs in:  .venv/bin/python packaging/make_lock.py

Every installed package is pinned to its exact version. Packages NOVA itself needs (everything that
requirements.txt pulls in) are listed first; tools only used for testing and building come after."""
import os, re, sys, platform
from importlib import metadata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
norm = lambda n: re.sub(r"[-_.]+", "-", n).lower()


def direct(path):
    names = []
    for line in open(path, encoding="utf-8"):
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"): continue
        marker = line.split(";", 1)[1] if ";" in line else ""
        if "win32" in marker: continue                      # this lock is for the Mac
        names.append(norm(re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0]))
    return names


def closure(names):
    seen, todo = set(), list(names)
    while todo:
        n = todo.pop()
        if n in seen: continue
        try: dist = metadata.distribution(n)
        except metadata.PackageNotFoundError: continue
        seen.add(n)
        for req in dist.requires or []:
            if "extra ==" in req: continue                  # optional extras are not installed by default
            if "sys_platform" in req and "win32" in req and "!=" not in req: continue
            todo.append(norm(re.split(r"[<>=!~\[; (]", req, maxsplit=1)[0]))
    return seen


def main():
    app = closure(direct(os.path.join(ROOT, "requirements.txt")))
    installed = {norm(d.metadata["Name"]): f'{d.metadata["Name"]}=={d.version}' for d in metadata.distributions() if d.metadata["Name"]}
    skip = {"pip", "setuptools", "wheel"}
    app_lines = sorted((v for k, v in installed.items() if k in app and k not in skip), key=str.lower)
    dev_lines = sorted((v for k, v in installed.items() if k not in app and k not in skip), key=str.lower)
    head = ("# NOVA - exact versions of every package (direct and indirect) the test-suite passes with.\n"
            f"# Python {platform.python_version()} on macOS {platform.mac_ver()[0]} ({platform.machine()}).\n"
            "# Install:  pip install -r requirements.lock      Refresh:  .venv/bin/python packaging/make_lock.py\n")
    with open(os.path.join(ROOT, "requirements.lock"), "w", encoding="utf-8") as f:
        f.write(head + "\n".join(app_lines) + "\n\n# -- only needed to run the tests / build the app --\n" + "\n".join(dev_lines) + "\n")
    print(f"{len(app_lines)} app packages, {len(dev_lines)} test/build packages pinned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
