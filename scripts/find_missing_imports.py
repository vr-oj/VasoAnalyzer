"""
find_missing_imports.py
=======================
AST-based analysis that finds names used in manager files that are neither
imported nor locally defined in the same file.  For each missing name it
then looks up what import statement supplies it in main_window.py.

Usage:
    python scripts/find_missing_imports.py
"""

import ast
import os
import sys
import textwrap
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path("/Users/valdovegarodr/Documents/GitHub/VasoAnalyzer")
MANAGERS_DIR = REPO_ROOT / "src/vasoanalyzer/ui/managers"
MAIN_WINDOW = REPO_ROOT / "src/vasoanalyzer/ui/main_window.py"

MANAGER_FILES = [
    "sample_manager.py",
    "plot_manager.py",
    "event_manager.py",
    "theme_manager.py",
    "navigation_manager.py",
    "export_manager.py",
    "project_manager.py",
    "snapshot_manager.py",
]

# ---------------------------------------------------------------------------
# Python built-in names we should ignore
# ---------------------------------------------------------------------------
BUILTINS = set(dir(__builtins__) if isinstance(__builtins__, dict) else dir(__builtins__))
BUILTINS.update({
    # common typing names
    "Any", "Dict", "List", "Optional", "Set", "Tuple", "Union", "Callable",
    "ClassVar", "Final", "Literal", "TypeVar", "Generic", "Protocol",
    "overload", "TYPE_CHECKING", "cast", "no_type_check",
    # common stdlib
    "os", "sys", "re", "io", "abc", "math", "time", "json", "copy",
    "pathlib", "dataclasses", "functools", "itertools", "collections",
    "contextlib", "threading", "traceback", "logging", "warnings",
    "datetime", "enum", "typing", "types",
    # common module-level names that are always available
    "self", "cls", "args", "kwargs",
    # python keywords / builtins that ast may surface
    "True", "False", "None",
    "__name__", "__file__", "__doc__", "__all__",
    "__init__", "__str__", "__repr__", "__class__",
})


# ---------------------------------------------------------------------------
# Step 1: collect everything *defined* in a file
# ---------------------------------------------------------------------------
def collect_definitions(tree: ast.Module) -> set:
    """
    Return the set of names that the file itself introduces:
    - import / import-from targets
    - top-level and class-level assignments (including __all__, type aliases)
    - function / class definitions
    - comprehension variables, for-loop targets, with-clause targets
    """
    defined = set()

    class Visitor(ast.NodeVisitor):
        def _add_targets(self, targets):
            for t in targets:
                self._add_target(t)

        def _add_target(self, node):
            if isinstance(node, ast.Name):
                defined.add(node.id)
            elif isinstance(node, (ast.Tuple, ast.List)):
                for elt in node.elts:
                    self._add_target(elt)
            elif isinstance(node, ast.Starred):
                self._add_target(node.value)

        def visit_Import(self, node):
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name.split(".")[0]
                defined.add(name)
            self.generic_visit(node)

        def visit_ImportFrom(self, node):
            for alias in node.names:
                name = alias.asname if alias.asname else alias.name
                if name != "*":
                    defined.add(name)
            self.generic_visit(node)

        def visit_FunctionDef(self, node):
            defined.add(node.name)
            # arguments
            for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
                defined.add(arg.arg)
            if node.args.vararg:
                defined.add(node.args.vararg.arg)
            if node.args.kwarg:
                defined.add(node.args.kwarg.arg)
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node):
            defined.add(node.name)
            self.generic_visit(node)

        def visit_Assign(self, node):
            self._add_targets(node.targets)
            self.generic_visit(node)

        def visit_AugAssign(self, node):
            self._add_target(node.target)
            self.generic_visit(node)

        def visit_AnnAssign(self, node):
            self._add_target(node.target)
            self.generic_visit(node)

        def visit_For(self, node):
            self._add_target(node.target)
            self.generic_visit(node)

        visit_AsyncFor = visit_For

        def visit_With(self, node):
            for item in node.items:
                if item.optional_vars:
                    self._add_target(item.optional_vars)
            self.generic_visit(node)

        visit_AsyncWith = visit_With

        def visit_ExceptHandler(self, node):
            if node.name:
                defined.add(node.name)
            self.generic_visit(node)

        def visit_Global(self, node):
            for name in node.names:
                defined.add(name)

        def visit_Nonlocal(self, node):
            for name in node.names:
                defined.add(name)

        def visit_comprehension(self, node):
            self._add_target(node.target)

        def visit_ListComp(self, node):
            for gen in node.generators:
                self.visit_comprehension(gen)
            self.generic_visit(node)

        visit_SetComp = visit_ListComp
        visit_DictComp = visit_ListComp
        visit_GeneratorExp = visit_ListComp

        def visit_NamedExpr(self, node):
            self._add_target(node.target)
            self.generic_visit(node)

    Visitor().visit(tree)
    return defined


# ---------------------------------------------------------------------------
# Step 2: collect all Name *usages* in method bodies
# ---------------------------------------------------------------------------
def collect_usages(tree: ast.Module) -> dict:
    """
    Return {name: first_lineno} for every ast.Name load encountered in
    method bodies (FunctionDef / AsyncFunctionDef that are children of
    ClassDef nodes) and also in type annotations and default values.

    We also capture names used in isinstance(), issubclass(), type() calls,
    decorator names, and bare-name expressions at class body level.
    """
    usages: dict[str, int] = {}

    def record(name: str, lineno: int):
        if name not in usages:
            usages[name] = lineno

    class BodyVisitor(ast.NodeVisitor):
        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load):
                record(node.id, node.lineno)
            self.generic_visit(node)

        def visit_Attribute(self, node):
            # only recurse into the value, not the attr string
            self.visit(node.value)

        def visit_Constant(self, node):
            pass  # string constants (forward refs) not parsed here

    class ClassVisitor(ast.NodeVisitor):
        def visit_ClassDef(self, node):
            # bases / keywords of the class itself
            for base in node.bases:
                BodyVisitor().visit(base)
            for kw in node.keywords:
                BodyVisitor().visit(kw.value)
            # class body: decorators, methods, class-level assignments
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # decorators
                    for dec in item.decorator_list:
                        BodyVisitor().visit(dec)
                    # annotations
                    for arg in (item.args.args + item.args.posonlyargs +
                                item.args.kwonlyargs):
                        if arg.annotation:
                            BodyVisitor().visit(arg.annotation)
                    if item.returns:
                        BodyVisitor().visit(item.returns)
                    # default values
                    for default in item.args.defaults + item.args.kw_defaults:
                        if default:
                            BodyVisitor().visit(default)
                    # full body
                    for stmt in item.body:
                        BodyVisitor().visit(stmt)
                elif isinstance(item, ast.Assign):
                    for t in item.targets:
                        BodyVisitor().visit(t)
                    BodyVisitor().visit(item.value)
                elif isinstance(item, ast.AnnAssign):
                    BodyVisitor().visit(item.annotation)
                    if item.value:
                        BodyVisitor().visit(item.value)
            self.generic_visit(node)

    ClassVisitor().visit(tree)
    return usages


# ---------------------------------------------------------------------------
# Step 3: build import map from main_window.py
# ---------------------------------------------------------------------------
def build_main_window_import_map(path: Path) -> dict[str, str]:
    """
    Parse main_window.py and return {name: import_statement_text}.
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    lines = src.splitlines()

    name_to_stmt: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # reconstruct the line(s)
            stmt = lines[node.lineno - 1].strip()
            for alias in node.names:
                n = alias.asname if alias.asname else alias.name.split(".")[0]
                name_to_stmt[n] = stmt
        elif isinstance(node, ast.ImportFrom):
            # multi-line imports: grab the full import block
            start = node.lineno - 1
            end = node.end_lineno - 1 if hasattr(node, "end_lineno") else start
            stmt = " ".join(l.strip() for l in lines[start : end + 1])
            for alias in node.names:
                n = alias.asname if alias.asname else alias.name
                if n != "*":
                    name_to_stmt[n] = stmt

    return name_to_stmt


# ---------------------------------------------------------------------------
# Step 4: also scan src/ tree for where names might be defined
# ---------------------------------------------------------------------------
def build_src_export_map(repo_root: Path) -> dict[str, list[str]]:
    """
    Walk src/ to find which modules define (export) each name at module level.
    Returns {name: [module_path, ...]}
    """
    name_to_modules: dict[str, list[str]] = defaultdict(list)
    src_dir = repo_root / "src"
    for py_file in src_dir.rglob("*.py"):
        try:
            src = py_file.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(py_file))
        except SyntaxError:
            continue
        defs = collect_definitions(tree)
        rel = py_file.relative_to(repo_root)
        for name in defs:
            if name[0].isupper() or name.isupper():
                name_to_modules[name].append(str(rel))
    return name_to_modules


# ---------------------------------------------------------------------------
# Main analysis
# ---------------------------------------------------------------------------
def analyse_file(path: Path) -> dict:
    """
    Return {
        'missing': [(name, first_lineno), ...],   # missing names
        'defined': set,
        'usages': {name: lineno},
    }
    """
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as e:
        print(f"  SYNTAX ERROR in {path.name}: {e}", file=sys.stderr)
        return {"missing": [], "defined": set(), "usages": {}}

    defined = collect_definitions(tree)
    usages = collect_usages(tree)

    missing = []
    for name, lineno in sorted(usages.items(), key=lambda x: x[1]):
        if name in defined:
            continue
        if name in BUILTINS:
            continue
        if name.startswith("_"):
            continue  # private / dunder
        missing.append((name, lineno))

    return {"missing": missing, "defined": defined, "usages": usages}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    print("=" * 72)
    print("VasoAnalyzer — Missing Import Detector")
    print("=" * 72)

    # Build reference maps
    print("\n[1/3] Building import map from main_window.py …")
    mw_imports = build_main_window_import_map(MAIN_WINDOW)
    print(f"      Found {len(mw_imports)} imported names in main_window.py")

    print("\n[2/3] Scanning src/ for exported names …")
    src_exports = build_src_export_map(REPO_ROOT)
    print(f"      Indexed {len(src_exports)} unique exported names across src/")

    print("\n[3/3] Analysing manager files …\n")
    print("=" * 72)

    grand_total = 0

    for fname in MANAGER_FILES:
        fpath = MANAGERS_DIR / fname
        if not fpath.exists():
            print(f"\n{'─'*72}")
            print(f"  FILE NOT FOUND: {fpath}")
            continue

        result = analyse_file(fpath)
        missing = result["missing"]
        grand_total += len(missing)

        print(f"\n{'─'*72}")
        print(f"  FILE: {fname}  ({len(missing)} missing names)")
        print(f"{'─'*72}")

        if not missing:
            print("  ✓ No missing names detected.\n")
            continue

        for name, lineno in missing:
            # Where does main_window know this name from?
            mw_stmt = mw_imports.get(name)
            # Where else in the src tree is it defined?
            alt_modules = [m for m in src_exports.get(name, [])
                           if fname not in m]

            # Determine category
            if name[0].isupper() and not name.isupper():
                category = "CamelCase (class/type)"
            elif name.isupper():
                category = "ALL_CAPS (constant)"
            else:
                category = "function/other"

            print(f"\n  NAME     : {name}")
            print(f"  CATEGORY : {category}")
            print(f"  FIRST USE: {fname}:{lineno}")
            if mw_stmt:
                # Trim very long import lines for readability
                display = mw_stmt if len(mw_stmt) <= 100 else mw_stmt[:97] + "..."
                print(f"  MW IMPORT: {display}")
            else:
                print(f"  MW IMPORT: (not found in main_window.py imports)")

            if alt_modules:
                for mod in alt_modules[:3]:
                    print(f"  ALSO IN  : {mod}")

    print(f"\n{'='*72}")
    print(f"  GRAND TOTAL: {grand_total} potentially missing names found")
    print(f"{'='*72}\n")

    # -----------------------------------------------------------------------
    # Summary table
    # -----------------------------------------------------------------------
    print("\nSUMMARY TABLE (names missing from MULTIPLE files)")
    print("─" * 72)
    # collect all (name, file) pairs
    all_missing: dict[str, list[str]] = defaultdict(list)
    for fname in MANAGER_FILES:
        fpath = MANAGERS_DIR / fname
        if not fpath.exists():
            continue
        result = analyse_file(fpath)
        for name, _ in result["missing"]:
            all_missing[name].append(fname)

    multi = {n: files for n, files in all_missing.items() if len(files) > 1}
    if multi:
        for name, files in sorted(multi.items()):
            mw_stmt = mw_imports.get(name, "(unknown)")
            print(f"  {name:<40} missing in {len(files)} files")
            print(f"    import : {mw_stmt}")
            for f in files:
                print(f"    file   : {f}")
    else:
        print("  (no names missing in more than one file)")
    print()


if __name__ == "__main__":
    main()
