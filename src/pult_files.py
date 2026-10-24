"""Files to and from the phone (stage F): where a file from Telegram goes and under what name, which file may go back
to Telegram, which files a turn made or changed. Standard library only; pultd downloads, sends and asks. Design:
docs/project.html, stage F.
"""
import fnmatch, os, re, time, unicodedata, urllib.parse, zipfile

TG_GET_MAX = 20 * 1024 * 1024      # Telegram hands bots files up to this (Bot API, getFile)
TG_SEND_MAX = 50 * 1024 * 1024     # and takes documents from bots up to this (sendDocument)
SEND_MANY = 10                     # files in one `pult send`
HOLD = 600                         # s: files that came without words wait this long for the owner's next message
INBOX = "inbox"                    # <project>/inbox/<date>/ — files from the owner (decision Q38)
NAME_MAX = 120
TURN_FILES_MAX = 100               # files a turn made, newest first (stage F4: 30 → 100)
ZIP_RAW_MAX = 200 * 1024 * 1024    # bytes of files packed into one archive, at most: past it nothing is packed
# already packed: into an archive as they are, no second squeeze
STORED_EXT = {".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic",
              ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".mp3", ".m4a", ".ogg", ".opus", ".docx", ".xlsx", ".pptx",
              ".odt", ".ods", ".odp", ".epub", ".jar", ".apk"}
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
# a project's file opened in the app from a link in Claude's words (stage F5): text in full up to this, a longer one
# shows its start; a picture up to this — in base64 it must fit the relay's 8 MB frame; a folder's entries up to this
SHOW_TEXT_MAX = 1024 * 1024
SHOW_PIC_MAX = 5 * 1024 * 1024
SHOW_DIR_MAX = 500
SHOW_AS = {".md": "md", ".markdown": "md", ".html": "html", ".htm": "html"}
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


def link_target(project, link, base=""):
    """A link to a file in Claude's words → the path it means. Claude writes them from the working folder, which is
    the project's; a link inside a project file's own page counts from that file's folder (base, inside the project).
    An absolute path or ~ stays as it is; %-escapes and file:// are undone, a #L12 anchor is dropped."""
    p = urllib.parse.unquote(str(link or "").split("#", 1)[0])
    if p.lower().startswith("file://"):
        p = p[7:]
    p = os.path.expanduser(p)
    return os.path.normpath(p if os.path.isabs(p) else os.path.join(project, str(base or ""), p))


def why_not_show(path, project):
    """Why the app may not open this file or folder — an i18n key — or None if it may: the same rule as for Telegram,
    inside the session's project folder (after links), nothing on the way or in the name like keys or settings."""
    root = os.path.realpath(project)
    real = os.path.realpath(path)
    if real != root and not real.startswith(root.rstrip(os.sep) + os.sep):
        return "send.err.outside"
    if not os.path.exists(real):
        return "send.err.none"
    rel = os.path.relpath(real, root)
    if rel != "." and (secret_like(rel + (os.sep + "x" if os.path.isdir(real) else "")) or secret_like(os.path.basename(path))):
        return "show.err.secret"
    return None


def image_kind(blob):
    """png / jpg / gif / webp by the first bytes of the file, else None: only pictures are taken from the app."""
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if blob[:3] == b"\xff\xd8\xff":
        return "jpg"
    if blob[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "webp"
    return None


def show_file(real):
    """A project file for the app's screen: {kind, size, mt} and what to show. kind "pic" with data (its bytes) and
    pic (png / jpg / gif / webp, told by the bytes, at most SHOW_PIC_MAX); "md", "html" (by the extension) or "text"
    with text — UTF-8 with no NUL, at most SHOW_TEXT_MAX bytes, cut at a line's end (cut: the rest is left out);
    anything else is "other": Telegram opens it."""
    st = os.stat(real)
    out = {"size": st.st_size, "mt": int(st.st_mtime)}
    with open(real, "rb") as f:
        blob = f.read(SHOW_TEXT_MAX + 1)
        pic = image_kind(blob[:16])
        if pic:
            if st.st_size > SHOW_PIC_MAX:
                return dict(out, kind="other")
            return dict(out, kind="pic", pic=pic, data=blob + f.read())
    cut = len(blob) > SHOW_TEXT_MAX
    if cut:
        blob = blob[:blob.rfind(b"\n", 0, SHOW_TEXT_MAX) + 1 or SHOW_TEXT_MAX]
    if b"\0" in blob:
        return dict(out, kind="other")
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError as e:
        if not cut or e.start < len(blob) - 3:            # a letter cut in two at the very end is no reason
            return dict(out, kind="other")
        text = blob[:e.start].decode("utf-8")
    return dict(out, kind=SHOW_AS.get(os.path.splitext(real)[1].lower(), "text"), text=text, cut=cut)


def show_dir(real):
    """A project folder for the app's screen: its entries [{n, dir, size, lock}] — folders first, then by name, no
    lock or temporary files — at most SHOW_DIR_MAX, and how many there are. lock: like keys or settings, not opened."""
    out = []
    with os.scandir(real) as it:
        for e in it:
            if temp_like(e.name):
                continue
            try:
                d = e.is_dir()
                size = 0 if d else e.stat().st_size
            except OSError:
                continue
            out.append({"n": e.name, "dir": d, "size": size,
                        "lock": e.name.lower() in SECRET_DIRS if d else secret_like(e.name)})
    out.sort(key=lambda x: (not x["dir"], x["n"].casefold()))
    return out[:SHOW_DIR_MAX], len(out)


def size_text(n):
    """A size for the log: 436 B, 12 KB, 2.3 MB — a small file is not "0 KB"."""
    return "%d B" % n if n < 1024 else "%d KB" % round(n / 1024) if n < 1024 * 1024 else "%.1f MB" % (n / 1048576)


def temp_like(name):
    return any(fnmatch.fnmatchcase(name, pat) for pat in TEMP_NAMES)


def turn_files(project, since, until=None):
    """The project's files made or changed from `since` (a turn's start) to `until`: ([{p: path inside the project,
    size, mt}] newest first, at most TURN_FILES_MAX; how many there were in all). Hidden folders, dependencies and
    caches, the owner's inbox and lock files are skipped; the walk stops after SCAN_MAX entries or SCAN_TIME s."""
    root = os.path.realpath(project)
    if not os.path.isdir(root):
        return [], 0
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
    return [{"p": rel, "size": size, "mt": round(mt, 1)} for mt, rel, size in out[:TURN_FILES_MAX]], len(out)


def zip_name(project, now=None):
    """An archive of a project's files: <project>-YYYY-MM-DD-HHMM.zip."""
    stem = safe_name(os.path.basename(os.path.realpath(project).rstrip(os.sep)), "files")
    return "%s-%s.zip" % (stem, time.strftime("%Y-%m-%d-%H%M", time.localtime(now)))


def make_zip(project, paths, dest, limit=TG_SEND_MAX):
    """Files of a project (checked: real paths inside it) → a zip at dest, each under its path inside the project, so
    two README.md from different folders stay apart. → the archive's size, or None as soon as it outgrows limit."""
    root = os.path.realpath(project)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            packed = os.path.splitext(p)[1].lower() in STORED_EXT
            z.write(p, os.path.relpath(p, root), compress_type=zipfile.ZIP_STORED if packed else zipfile.ZIP_DEFLATED)
            if z.fp.tell() > limit:
                return None
    size = os.path.getsize(dest)
    return size if size <= limit else None
