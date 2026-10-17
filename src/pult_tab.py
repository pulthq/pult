#!/usr/bin/env python3
"""Pult: Claude Code process wrapper for VS Code tabs — messages from Telegram go straight into the open tab
(stage 2, probe).

Installed by the owner via the `claudeCode.claudeProcessWrapper` setting in VS Code. The extension runs
`pult_tab.py <its claude> <arguments>` — both for tabs and for service commands. Standard library only.

The main rule is the same as for the hook: the wrapper never gets in the way. Off switch set, not a tab chat,
unverified Claude Code version, folder not in the list, any error before start — exec the real claude at once:
the process is replaced and the wrapper is gone.

In the selected folders the wrapper stays in between as a proxy: extension lines → Claude Code and the output
back, byte for byte; between extension lines it slips in a user message from the daemon. Claude Code echoes it
to its output (--replay-user-messages), and the tab shows it as a regular message with the turn it starts
(extension code 2.1.301: the tab inserts a replay with an unknown uuid into the chat; "working" comes from
system/init, the end from result). If the link to the daemon breaks, the tab works as without the wrapper.
"""
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import uuid

CONF = os.environ.get("PULT_TAB_CONF") or os.path.expanduser("~/.config/pult/tab.json")
OFF = os.path.expanduser("~/.config/pult/tab-off")        # off switch: if the file exists, there is no wrapper
SOCK = os.environ.get("PULT_SOCK") or os.path.expanduser("~/.local/share/pult/pult.sock")
LOG = os.path.expanduser("~/Library/Logs/pult-tab.log")
TAP_MAX = 4 * 1024 * 1024                                  # longer lines are not parsed, only passed through


def log(*a):
    try:
        with open(LOG, "a") as f:
            f.write("%s %d %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid(), " ".join(map(str, a))))
    except OSError:
        pass


def version_of(path):
    """…/anthropic.claude-code-2.1.301-darwin-arm64/resources/native-binary/claude → '2.1.301'."""
    for part in str(path).split(os.sep):
        if part.startswith("anthropic.claude-code-"):
            return part[len("anthropic.claude-code-"):].split("-")[0]
    return None


def arg(argv, name):
    try:
        return argv[argv.index(name) + 1]
    except (ValueError, IndexError):
        return None


def why_direct(argv, conf, cwd):
    """Why the wrapper is not needed (→ exec the real claude right away), or None if we proxy this tab."""
    if os.path.exists(OFF):
        return "switched off"
    if arg(argv, "--input-format") != "stream-json" or arg(argv, "--output-format") != "stream-json":
        return "not a chat session"
    if version_of(argv[0]) not in (conf.get("versions") or []):
        return "version %s is not verified" % version_of(argv[0])
    real = os.path.realpath(cwd)
    for folder in conf.get("folders") or []:
        f = os.path.realpath(os.path.expanduser(folder))
        if real == f or real.startswith(f.rstrip("/") + "/"):
            return None
    return "folder not in the list"


def write_all(fd, data):
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


class Tab:
    def __init__(self, argv):
        self.argv = argv
        self.cwd = os.getcwd()
        self.sid = arg(argv, "--resume") or arg(argv, "--session-id")
        self.lock = threading.Lock()           # lines go into Claude Code's stdin whole, never interleaved
        self.sock = None
        self.slock = threading.Lock()
        self.child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0)
        self.cin, self.cout = self.child.stdin.fileno(), self.child.stdout.fileno()

    def to_claude(self, line):
        with self.lock:
            write_all(self.cin, line)

    def up(self):
        """Extension → Claude Code, line by line (each line is one JSON message)."""
        try:
            for line in sys.stdin.buffer:
                self.to_claude(line)
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                self.child.stdin.close()
            except OSError:
                pass

    def down(self):
        """Claude Code → extension, byte for byte; along the way, pick up the session ID from system/init."""
        buf = b""
        while True:
            try:
                chunk = os.read(self.cout, 65536)
            except OSError:
                break
            if not chunk:
                break
            try:
                write_all(1, chunk)
            except OSError:
                break
            try:
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if b'"init"' in line and b'"system"' in line:
                        self.on_init(line)
                if len(buf) > TAP_MAX:
                    buf = b""
            except Exception as e:                 # parsing is a side job: its errors never affect the tab
                log("output parsing:", type(e).__name__)
                buf = b""

    def on_init(self, line):
        sid = json.loads(line).get("session_id")
        if sid and sid != self.sid:
            self.sid = sid
            self.tell({"op": "sid", "sid": sid})

    def tell(self, msg):
        with self.slock:
            if self.sock:
                try:
                    self.sock.sendall(json.dumps(msg, ensure_ascii=False).encode() + b"\n")
                except OSError:
                    pass

    def send_user(self, text, uid=None):
        # like a message typed in the tab (origin human — that is how the tab sends its own, tab code 2.1.301)
        msg = {"type": "user", "uuid": uid or str(uuid.uuid4()), "session_id": "", "parent_tool_use_id": None,
               "origin": {"kind": "human"}, "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
        self.to_claude(json.dumps(msg, ensure_ascii=False).encode() + b"\n")

    def link(self):
        """Link to the daemon: introduce ourselves, receive messages. No daemon — retry; the tab does not wait."""
        while self.child.poll() is None:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                s.connect(SOCK)
                with self.slock:
                    self.sock = s
                self.tell({"op": "hello", "pid": os.getpid(), "cwd": self.cwd, "sid": self.sid,
                           "version": version_of(self.argv[0])})
                for line in s.makefile("rb"):
                    m = json.loads(line)
                    if m.get("op") == "send" and m.get("text"):
                        self.send_user(m["text"], m.get("uuid"))
                        log("message from Pult into the tab", (self.sid or "?")[:8])
                        self.tell({"op": "sent", "uuid": m.get("uuid")})
            except Exception as e:
                if not isinstance(e, (FileNotFoundError, ConnectionRefusedError)):
                    log("daemon link:", type(e).__name__)
            finally:
                with self.slock:
                    self.sock = None
                s.close()
            time.sleep(3)

    def run(self):
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, lambda n, f: self.child.send_signal(n))
        threading.Thread(target=self.up, daemon=True).start()
        threading.Thread(target=self.link, daemon=True).start()
        self.down()
        if self.child.poll() is None:
            # output has nowhere to go (the tab was closed) but Claude Code is alive — don't leave it hanging
            try:
                self.child.wait(5)
            except subprocess.TimeoutExpired:
                self.child.terminate()
                try:
                    self.child.wait(5)
                except subprocess.TimeoutExpired:
                    self.child.kill()
        code = self.child.wait()
        return 128 - code if code < 0 else code


def main(argv):
    try:
        conf = json.load(open(CONF))
        why = why_direct(argv, conf, os.getcwd())
    except Exception as e:
        why = "no wrapper config (%s)" % type(e).__name__
    if why:
        os.execv(argv[0], argv)
    log("proxying a tab:", os.getcwd(), version_of(argv[0]))
    try:
        tab = Tab(argv)
    except Exception as e:
        log("failed to start, going direct:", repr(e))
        os.execv(argv[0], argv)
    sys.exit(tab.run())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("pult_tab.py: the path to claude is required")
    main(sys.argv[1:])
