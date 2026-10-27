"""What has to agree across the repository before CI is green (review 2026-10-27, Т10):

- the version in src/pultd.py is the newest numbered section of CHANGELOG.md or newer (between releases the next one
  is being made), and on a release tag (GITHUB_REF=refs/tags/vX.Y.Z) it is that very tag, with its section on top and
  nothing left under "Unreleased";
- the relay's requirements are met by the computer's pinned ones (the tests install both into one environment).

  python tools/consistency.py        exit 1 and the reasons, when something doesn't agree"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def vkey(v):
    return tuple(int(x) for x in v.split("."))


def problems(root=ROOT, ref=None):
    out = []
    m = re.search(r'^VERSION = "(\d+\.\d+\.\d+)"', (root / "src" / "pultd.py").read_text(encoding="utf-8"), re.M)
    if not m:
        return ["src/pultd.py: no VERSION"]
    version = m.group(1)
    log = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    sections = re.findall(r"^## (\S+)", log, re.M)
    numbered = [s for s in sections if re.fullmatch(r"\d+\.\d+\.\d+", s)]
    if not numbered:
        out.append("CHANGELOG.md: no numbered section")
    elif vkey(version) < vkey(numbered[0]):
        out.append("VERSION %s is older than CHANGELOG's newest section %s" % (version, numbered[0]))
    tag = re.fullmatch(r"refs/tags/v(\d+\.\d+\.\d+)", ref or "")
    if tag:
        if tag.group(1) != version:
            out.append("tag v%s, but VERSION is %s" % (tag.group(1), version))
        if not numbered or numbered[0] != tag.group(1):
            out.append("tag v%s, but CHANGELOG's newest section is %s" % (tag.group(1), numbered[0] if numbered else None))
        unreleased = re.search(r"^## Unreleased\n(.*?)(?=^## )", log, re.M | re.S)
        if unreleased and unreleased.group(1).strip():
            out.append("tag v%s, but CHANGELOG still has entries under Unreleased" % tag.group(1))
    pins = {}
    for ln in (root / "requirements.txt").read_text(encoding="utf-8").splitlines():
        p = re.fullmatch(r"\s*([A-Za-z0-9_.-]+)==([\d.]+)\s*", ln)
        if p:
            pins[p.group(1).lower()] = p.group(2)
    for ln in (root / "relay" / "requirements.txt").read_text(encoding="utf-8").splitlines():
        r = re.fullmatch(r"\s*([A-Za-z0-9_.-]+)(>=|==)([\d.]+)\s*", ln)
        if not r or r.group(1).lower() not in pins:
            continue
        have, op, want = pins[r.group(1).lower()], r.group(2), r.group(3)
        if op == "==" and have != want or op == ">=" and vkey(have) < vkey(want):
            out.append("relay/requirements.txt wants %s%s%s, requirements.txt pins %s" % (r.group(1), op, want, have))
    return out


if __name__ == "__main__":
    bad = problems(ref=os.environ.get("GITHUB_REF"))
    for b in bad:
        print("✗", b)
    print("consistent" if not bad else "%d thing(s) don't agree" % len(bad))
    sys.exit(1 if bad else 0)
