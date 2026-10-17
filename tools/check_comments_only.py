"""Verify that a file differs from its git HEAD version only in comments and docstrings.

  python3 tools/check_comments_only.py . <file> [<file> ...]     # compares with git HEAD
Python: the AST with docstrings removed must be identical. JS / CSS / shell / HTML: every line, with its comment
part removed, must be identical (same number of lines). Prints OK or the first difference; exit code 1 on any.
"""
import ast
import re
import subprocess
import sys
from pathlib import Path


def strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return tree


def py_same(old, new):
    a = ast.dump(strip_docstrings(ast.parse(old)), include_attributes=False)
    b = ast.dump(strip_docstrings(ast.parse(new)), include_attributes=False)
    return a == b, None if a == b else "AST differs (code changed, not only comments/docstrings)"


LINE_COMMENT = {".js": r"(^|\s)//(\s|$)", ".sh": r"(^|\s)#(\s|$|!)", ".css": None, ".html": None}


def code_part(line, ext):
    if ext in (".css", ".html"):
        return line
    pat = LINE_COMMENT[ext]
    m = re.search(pat, line)
    return (line[:m.start()] if m else line).rstrip()


def text_same(old, new, ext):
    if ext == ".css":
        old, new = re.sub(r"/\*.*?\*/", "", old, flags=re.S), re.sub(r"/\*.*?\*/", "", new, flags=re.S)
    if ext == ".html":
        old, new = re.sub(r"<!--.*?-->", "", old, flags=re.S), re.sub(r"<!--.*?-->", "", new, flags=re.S)
    a, b = old.splitlines(), new.splitlines()
    if len(a) != len(b):
        return False, "line count differs: %d → %d" % (len(a), len(b))
    for i, (x, y) in enumerate(zip(a, b), 1):
        if code_part(x, ext) != code_part(y, ext):
            return False, "line %d: code differs:\n  - %s\n  + %s" % (i, x.strip()[:150], y.strip()[:150])
    return True, None


def main():
    repo, files = sys.argv[1], sys.argv[2:]
    bad = 0
    for f in files:
        old = subprocess.run(["git", "-C", repo, "show", "HEAD:" + f], capture_output=True, text=True).stdout
        new = (Path(repo) / f).read_text()
        ext = Path(f).suffix
        ok, why = py_same(old, new) if ext == ".py" else text_same(old, new, ext)
        cyr = len(re.findall("[А-Яа-яЁё]+", new))
        print("%-4s %s%s  (Cyrillic words left: %d)" % ("OK" if ok else "FAIL", f, "" if ok else "\n     " + why, cyr))
        bad += not ok
    sys.exit(1 if bad else 0)


main()
