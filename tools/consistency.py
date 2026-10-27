"""What has to agree across the repository before CI is green (review 2026-10-27, Т10):

- the version in src/pultd.py is the newest numbered section of CHANGELOG.md or newer (between releases the next one
  is being made), and on a release tag (GITHUB_REF=refs/tags/vX.Y.Z) it is that very tag, with its section on top and
  nothing left under "Unreleased";
- the requirements are locked (tools/lock.py, Q91): every package pinned with its hashes, every version the .in file
  asks for in its lock, and what both locks hold at the same versions (the tests install both into one environment).

  python tools/consistency.py        exit 1 and the reasons, when something doesn't agree"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def vkey(v):
    return tuple(int(x) for x in v.split("."))


def norm(name):
    return name.lower().replace("_", "-")


def locked(path):
    """A requirements file as tools/lock.py makes it → ({name: {versions}}, [names without a hash]). An entry is a line
    "name==version [; marker] \\" with its hashes on the lines after it; a name may come twice, for two Pythons."""
    pins, bare, cur = {}, [], None
    for ln in path.read_text(encoding="utf-8").splitlines() + [""]:
        m = re.match(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s;\\]+)", ln)
        if m or not ln.startswith(" "):
            if cur and not cur[1]:
                bare.append(cur[0])
            cur = None
        if m:
            cur = [norm(m.group(1)), False]
            pins.setdefault(cur[0], set()).add(m.group(2))
        elif cur and ln.strip().startswith("--hash="):
            cur[1] = True
    return pins, bare


def asked_for(path):
    """name → version of each "name==version" line of a .in file; {} without one."""
    if not path.is_file():
        return {}
    return {norm(m.group(1)): m.group(2) for m in re.finditer(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==(\S+)",
                                                             path.read_text(encoding="utf-8"), re.M)}


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
    for got, asked in (("requirements.txt", "requirements.in"), ("relay/requirements.txt", "relay/requirements.in")):
        pins, bare = locked(root / got)
        out += ["%s: %s has no hash — make the file with tools/lock.py" % (got, name) for name in bare]
        for name, v in asked_for(root / asked).items():
            if v not in pins.get(name, ()):
                out.append("%s: %s==%s from %s isn't in it — run tools/lock.py" % (got, name, v, asked))
    mine, relay = locked(root / "requirements.txt")[0], locked(root / "relay" / "requirements.txt")[0]
    for name in sorted(set(mine) & set(relay)):
        if mine[name] != relay[name]:
            out.append("relay/requirements.txt has %s %s, requirements.txt %s — run tools/lock.py"
                       % (name, "/".join(sorted(relay[name])), "/".join(sorted(mine[name]))))
    return out


if __name__ == "__main__":
    bad = problems(ref=os.environ.get("GITHUB_REF"))
    for b in bad:
        print("✗", b)
    print("consistent" if not bad else "%d thing(s) don't agree" % len(bad))
    sys.exit(1 if bad else 0)
