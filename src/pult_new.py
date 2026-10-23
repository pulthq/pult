"""A new project from the phone (stage S): its folder's name from any title, the checks, the clone link, the folders
to pick a place from, the first prompt of a project "with a description". Standard library only; pultd makes the
folder, runs git and starts the session. Design: docs/project.html, stage S.
"""
import os, re, unicodedata

# Russian and Ukrainian letters → Latin, the way people spell them by hand: дача → dacha, щука → shchuka; ё as e,
# the soft and the hard sign dropped (')
CYR = {c: "" if v == "'" else v for c, v in zip(
    "абвгдеёжзийклмнопрстуфхцчшщъыьэюяіїєґ",
    "a b v g d e e zh z i y k l m n o p r s t u f kh ts ch sh shch ' y ' e yu ya i yi ye g".split())}
NAME_MAX = 64
NAME_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,%d}[A-Za-z0-9_-])?" % (NAME_MAX - 2))
# names Windows won't give a folder, with or without an extension
RESERVED = {"con", "prn", "aux", "nul"} | {"com%d" % i for i in range(1, 10)} | {"lpt%d" % i for i in range(1, 10)}
BIG_MB = 1024           # a repository bigger than this: ask before cloning
CLONE_LIMIT = 15 * 60   # s: a clone that takes longer is stopped
DIRS_MAX = 300          # folders shown in one place of the picker

# what the first turn of a project "with a description" asks; the owner's words go as they are
DESCRIBE = """This is a new project, created a moment ago from the owner's phone: the folder holds nothing yet but an \
empty git repository. The owner calls it "{title}" and describes it like this:

{about}

Write CLAUDE.md for this project in the language of the description: what the project is for, what is already known, \
how to work in it. Keep it short and stay with what the description says — invent no details, tools or plans. Then \
tell the owner in two or three sentences what you wrote and what you would ask them first."""


def folder_name(title):
    """A folder's name from any title: lower case, Russian and Ukrainian letters in Latin, accents dropped, spaces
    and marks as "_". Letters of other scripts drop out — "" then, and the owner types a Latin name."""
    out = []
    for ch in (title or "").strip().lower():
        if ch in CYR:
            out.append(CYR[ch])
        elif ch.isascii():
            out.append(ch if ch.isalnum() or ch in "-." else "_")
        else:
            plain = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
            out.append(plain if plain.isalnum() else "" if ch.isalpha() else "_")
    s = re.sub(r"_+", "_", "".join(out))
    return re.sub(r"^[._-]+|[._-]+$", "", s)[:NAME_MAX].rstrip("._-")


def bad_name(name):
    """Why a folder's name won't do: an error key of pult_i18n, None if it is fine."""
    if not name or not NAME_RE.fullmatch(name):
        return "new.err.name"
    if name.split(".")[0].lower() in RESERVED:
        return "new.err.name"
    return None


def repo(link):
    """A clone link → (https URL, the repository's name, "owner/name" on GitHub or None); None if it isn't one.
    git@host:path and ssh:// become https — port 22 may be shut (a VPN that blocks it, seen 2026-07); only https
    reaches git, so a link can't pick a transport that runs commands (ext::). A GitHub page deeper than the
    repository (…/tree/main) clones the repository."""
    s = re.split(r"[?#]", (link or "").strip())[0]
    m = (re.fullmatch(r"(?:ssh://)?git@([A-Za-z0-9.-]+)[:/]([\w./-]+?)/?", s, re.A)
         or re.fullmatch(r"(?:https?://)?([A-Za-z0-9.-]+\.[A-Za-z]{2,})/([\w./-]+?)/?", s, re.A))
    if not m:
        return None
    host, path = m.group(1).lower(), m.group(2)
    parts = path.split("/")
    if host in ("github.com", "www.github.com"):
        host, parts = "github.com", parts[:2]
    if parts[-1].endswith(".git"):
        parts[-1] = parts[-1][:-4]
    if len(parts) < 2 or any(p in ("", ".", "..") or p.startswith(("-", ".")) for p in parts):
        return None
    path = "/".join(parts)
    return ("https://%s/%s.git" % (host, path), parts[-1], path if host == "github.com" else None)


def describe_prompt(title, about):
    return DESCRIBE.format(title=title.strip(), about=about.strip())


def inside(path, home):
    """path is home or inside it, after links are followed."""
    p, h = os.path.realpath(path), os.path.realpath(home)
    return p == h or p.startswith(h.rstrip(os.sep) + os.sep)


def dirs(path):
    """The folders in path a project can go into: visible ones, by name; at most DIRS_MAX."""
    out = []
    try:
        with os.scandir(path) as it:
            for e in it:
                if e.name.startswith(".") or e.name.startswith("$"):
                    continue
                try:
                    if e.is_dir():
                        out.append(e.name)
                except OSError:
                    continue
    except OSError:
        return []
    return sorted(out, key=str.lower)[:DIRS_MAX]


def progress(text):
    """git clone --progress output → (step, %) of its last line: ("receive", 45), ("resolve", 80), ("files", 100)."""
    last = None
    for m in re.finditer(r"(Receiving objects|Resolving deltas|Updating files):\s+(\d+)%", text or ""):
        last = ({"Receiving objects": "receive", "Resolving deltas": "resolve", "Updating files": "files"}[m.group(1)],
                int(m.group(2)))
    return last
