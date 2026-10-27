"""Was pultd.py split by moving code only? (review 2026-10-27, 6.2) Compares the daemon at a commit with the daemon
now, by parse tree, with its mixins on both sides — the bases of class Pult imported from modules of src/ (pult_api's
Api, pult_parts' Parts…), found by the tool itself: every method the daemon had is still there, in Pult or in a mixin,
the same but for the daemon's names a mixin reads late as self.D.X; a moved method reads no name that means another
thing in its new module (__name__, __file__, super…); what left pultd's module level is in a mixin's module as it was;
pultd gained only imports from those modules, Pult only its bases and D.

  python3 tools/split_check.py HEAD            the working tree against the last commit
  python3 tools/split_check.py ae4035c         …against the daemon before the split began

Exit 1 with what differs. Standard library only; it reads the files, it runs nothing of Pult.
"""
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# names that mean another thing in another module: a moved method must not read them bare
OWN_MODULE = {"__name__", "__file__", "__spec__", "__package__", "__loader__", "__builtins__", "globals", "vars", "super"}
D = "D = sys.modules[__name__]"


class Undaemon(ast.NodeTransformer):
    """self.D.X → X: a mixin's method as it was in the daemon."""
    def __init__(self):
        self.n = 0

    def visit_Attribute(self, node):
        self.generic_visit(node)
        v = node.value
        if isinstance(v, ast.Attribute) and v.attr == "D" and isinstance(v.value, ast.Name) and v.value.id == "self":
            self.n += 1
            return ast.copy_location(ast.Name(id=node.attr, ctx=node.ctx), node)
        return node


def the_class(tree, name):
    return next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name), None)


def methods(cls):
    """{name: def}; a property's getter and setter share a name — the second is "name#2"."""
    out = {}
    for n in cls.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            key, i = n.name, 1
            while key in out:
                i += 1
                key = "%s#%d" % (n.name, i)
            out[key] = n
    return out


def bound(n):
    """The names a module-level statement binds, for the report."""
    if isinstance(n, ast.Assign):
        return [x.id for t in n.targets for x in ast.walk(t) if isinstance(x, ast.Name)]
    return [getattr(n, "name", None) or ast.unparse(n)[:60]]


class Side:
    """The daemon at a commit (rev) or in the working tree (rev None): pultd's tree, Pult, its mixins and their modules."""
    def __init__(self, rev=None):
        self.rev = rev
        self.tree = ast.parse(self.read("pultd"))
        self.pult = the_class(self.tree, "Pult")
        origin = {(a.asname or a.name): n.module for n in self.tree.body if isinstance(n, ast.ImportFrom) and n.module
                  for a in n.names}
        self.mixins, self.modules = {}, {}            # class name → (module, ClassDef); module → its tree
        for b in self.pult.bases:
            m = origin.get(getattr(b, "id", None))
            if m and m.startswith("pult"):
                tree = self.modules.setdefault(m, ast.parse(self.read(m)))
                c = the_class(tree, b.id)
                if c is not None:
                    self.mixins[b.id] = (m, c)

    def read(self, module):
        if self.rev is None:
            return (ROOT / "src" / (module + ".py")).read_text(encoding="utf-8")
        return subprocess.run(["git", "-C", str(ROOT), "show", "%s:src/%s.py" % (self.rev, module)], check=True,
                              capture_output=True, text=True).stdout

    def where(self):
        """{method: (module, def)} over Pult and its mixins; a name in two of them → listed in clash."""
        out, clash = {}, []
        for module, cls in [("pultd", self.pult)] + list(self.mixins.values()):
            for name, fn in methods(cls).items():
                if name in out:
                    clash.append("%s is in both %s and %s" % (name, out[name][0], module))
                out[name] = (module, fn)
        return out, clash


def norm(fn):
    u = Undaemon()
    return ast.dump(u.visit(ast.parse(ast.unparse(fn)).body[0])), u.n


def main(rev):
    old, new = Side(rev), Side()
    ow, _ = old.where()
    nw, bad = new.where()
    moved, late = {}, 0
    for name, (m0, fn) in ow.items():
        if name not in nw:
            bad.append("%s is gone" % name)
            continue
        m1, got = nw[name]
        a, _ = norm(fn)
        b, k = norm(got)
        if a != b:
            bad.append("%s differs (in %s)" % (name, m1))
        if m1 != m0:
            moved[m1] = moved.get(m1, 0) + 1
            late += k
            bad += ["%s reads %s, which is %s's own there" % (name, x.id, m1) for x in ast.walk(got)
                    if isinstance(x, ast.Name) and x.id in OWN_MODULE]
    bad += ["%s is new (in %s)" % (name, nw[name][0]) for name in nw if name not in ow]
    # the class's other statements: as they were, and D once there are mixins
    others = lambda c: [ast.unparse(n) for n in c.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    want = [D] * bool(new.mixins and D not in others(old.pult)) + others(old.pult)
    if others(new.pult) != want:
        bad.append("class Pult's statements: %s, were %s" % (others(new.pult), others(old.pult)))
    # module level: what left pultd is in a mixin's module as it was; pultd gained imports from those modules only
    keep = lambda t: [n for n in t.body if not (isinstance(n, ast.ClassDef) and n.name == "Pult")]
    have = {ast.dump(n) for n in keep(new.tree)}
    gone = [n for n in keep(old.tree) if ast.dump(n) not in have]
    there = {ast.dump(n) for t in new.modules.values() for n in t.body}
    bad += ["%s left pultd and isn't in %s as it was" % (bound(n), ", ".join(new.modules) or "a mixin's module")
            for n in gone if ast.dump(n) not in there]
    was = {ast.dump(n) for n in keep(old.tree)}
    bad += ["new in pultd: %s" % ast.unparse(n)[:100] for n in keep(new.tree)
            if ast.dump(n) not in was and not (isinstance(n, ast.ImportFrom) and n.module in new.modules)]
    print("%s → now: Pult(%s); methods moved: %s, %d stay in pultd; %d of the daemon's names read late (self.D); "
          "%d module-level statements left pultd" % (
              rev, ", ".join(b.id for b in new.pult.bases if isinstance(b, ast.Name)),
              ", ".join("%d to %s" % (k, m) for m, k in moved.items()) or "none",
              sum(1 for name in ow if nw.get(name, ("",))[0] == "pultd"), late, len(gone)))
    for b in bad:
        print("  ✗", b)
    print("moved only" if not bad else "not only moved")
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
