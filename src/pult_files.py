"""Files to and from the phone (stage F): where a file from Telegram goes and under what name, which file may go back
to Telegram, which files a turn made or changed. Standard library only; pultd downloads, sends and asks. Design:
docs/project.html, stage F.
"""
import fnmatch, os, re, time, unicodedata

TG_GET_MAX = 20 * 1024 * 1024      # Telegram hands bots files up to this (Bot API, getFile)
TG_SEND_MAX = 50 * 1024 * 1024     # and takes documents from bots up to this (sendDocument)
SEND_MANY = 10                     # files in one `pult send`
HOLD = 600                         # s: files that came without words wait this long for the owner's next message
INBOX = "inbox"                    # <project>/inbox/<date>/ — files from the owner (decision Q38)
NAME_MAX = 120
TURN_FILES_MAX = 30                # files a turn made, newest first
SCAN_MAX = 20000                   # entries walked in a project at a turn's end, at most
SCAN_TIME = 1.0                    # s, at most
SKIP_DIRS = {"node_modules", "__pycache__", "venv", "site-packages", "dist-packages"}   # deliverables may sit in build/: kept
# never sent: folders and names of keys, passwords and settings (any case); the project's own .git as well
SECRET_DIRS = {".ssh", ".aws", ".gnupg", ".config", ".kube", ".docker", ".git", ".azure", ".gcloud"}
SECRET_NAMES = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "*.kdbx", "*.keychain", "*.keychain-db",
                "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*", ".netrc", ".npmrc", ".pypirc", ".pgpass",
                "credentials", "credentials.*", "*.ovpn")
# a document's lock and temporary files: never "made by the turn"
TEMP_NAMES = ("~$*", ".~lock*", "*.tmp", "*.swp", "*.swx", ".DS_Store", "Thumbs.db", "*.crdownload", "*.part")
# names Windows won't give a file, with or without an extension
RESERVED = {"con", "prn", "aux", "nul"} | {"com%d" % i for i in range(1, 10)} | {"lpt%d" % i for i in range(1, 10)}


def safe_name(name, fallback="file"):
    """A file's name from Telegram or the app, fit for a folder on any system: its last part only (no folders), no
    control or reserved characters, not hidden, at most NAME_MAX characters with the extension kept."""
    n = unicodedata.normalize("NFC", str(name or "")).replace("\\", "/").split("/")[-1]
    n = re.sub(r'[\x00-\x1f\x7f<>:"|?*]', "_", n).strip().lstrip(".-").rstrip(". ")
    if not n:
        n = fallback
    if n.split(".")[0].lower() in RESERVED:
        n = "_" + n
    if len(n) > NAME_MAX:
        stem, ext = os.path.splitext(n)
        ext = ext if len(ext) <= 16 else ""
        n = stem[:NAME_MAX - len(ext)].rstrip(". ") + ext
    return n


def unique(folder, name):
    """folder/name, or folder/"name (2).ext", "name (3).ext"… when it is taken."""
    stem, ext = os.path.splitext(name)
    p, k = os.path.join(folder, name), 2
    while os.path.lexists(p):
        p = os.path.join(folder, "%s (%d)%s" % (stem, k, ext))
        k += 1
    return p


def drop_dir(project, now=None):
    """Where the owner's files go in a project: inbox/<YYYY-MM-DD>/."""
    return os.path.join(project, INBOX, time.strftime("%Y-%m-%d", time.localtime(now)))


def exclude_inbox(project):
    """A git project: inbox/ goes into .git/info/exclude — ignored on this computer only, never into the repository.
    True if the line was added."""
    git = os.path.join(project, ".git")
    if not os.path.isdir(git):                  # not git, or a worktree (.git is a file there): left alone
        return False
    p = os.path.join(git, "info", "exclude")
    try:
        lines = []
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                lines = f.read().splitlines()
    except OSError:
        return False
    if any(ln.strip() in ("inbox", "inbox/", "/inbox", "/inbox/") for ln in lines):
        return False
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(("\n" if lines and lines[-1].strip() else "") + "# files from the owner's phone (Pult)\n/inbox/\n")
    except OSError:
        return False
    return True


def secret_like(rel):
    """A path inside a project that looks like keys or settings: a secret folder on the way, or a secret name."""
    parts = [p for p in re.split(r"[\\/]", rel) if p]
    if any(p.lower() in SECRET_DIRS for p in parts[:-1]):
        return True
    name = parts[-1].lower() if parts else ""
    return any(fnmatch.fnmatchcase(name, pat) for pat in SECRET_NAMES)


def why_not_send(path, project):
    """Why this file may not go to Telegram — an i18n key — or None if it may: a file inside the session's project
    folder (after links), not like a secret by its given or its real name, not empty, at most TG_SEND_MAX."""
    root = os.path.realpath(project)
    real = os.path.realpath(path)
    if not real.startswith(root.rstrip(os.sep) + os.sep):
        return "send.err.outside"
    if not os.path.isfile(real):
        return "send.err.none"
    if secret_like(os.path.relpath(real, root)) or secret_like(os.path.basename(path)):
        return "send.err.secret"
    size = os.path.getsize(real)
    if not size:
        return "send.err.empty"
    if size > TG_SEND_MAX:
        return "send.err.big"
    return None


def temp_like(name):
    return any(fnmatch.fnmatchcase(name, pat) for pat in TEMP_NAMES)


def turn_files(project, since, until=None):
    """The project's files made or changed from `since` (a turn's start) to `until`: [{p: path inside the project,
    size, mt}], newest first, at most TURN_FILES_MAX. Hidden folders, dependencies and caches, the owner's inbox and
    lock files are skipped; the walk stops after SCAN_MAX entries or SCAN_TIME s."""
    root = os.path.realpath(project)
    if not os.path.isdir(root):
        return []
    t0, seen, out = time.monotonic(), 0, []
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            it = os.scandir(d)
        except OSError:
            continue
        with it:
            for e in it:
                seen += 1
                if seen > SCAN_MAX or time.monotonic() - t0 > SCAN_TIME:
                    stack = []
                    break
                name = e.name
                try:
                    if e.is_dir(follow_symlinks=False):
                        if not (name.startswith(".") or name in SKIP_DIRS or (d == root and name == INBOX)):
                            stack.append(e.path)
                        continue
                    if not e.is_file(follow_symlinks=False) or name.startswith(".") or temp_like(name):
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if st.st_mtime >= since - 1 and (until is None or st.st_mtime <= until + 1):
                    out.append((st.st_mtime, os.path.relpath(e.path, root), st.st_size))
    out.sort(reverse=True)
    return [{"p": rel, "size": size, "mt": round(mt, 1)} for mt, rel, size in out[:TURN_FILES_MAX]]
