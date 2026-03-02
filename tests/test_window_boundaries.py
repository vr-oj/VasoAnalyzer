from __future__ import annotations

import ast
from pathlib import Path


def _collect_imports(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


def test_home_page_has_no_forbidden_imports() -> None:
    home_page_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "vasoanalyzer"
        / "ui"
        / "panels"
        / "home_page.py"
    )
    tree = ast.parse(home_page_path.read_text(encoding="utf-8"))
    imports = _collect_imports(tree)
    forbidden = {
        "vasoanalyzer.ui.main_window",
        "vasoanalyzer.core.project",
    }
    offenders = sorted(imports & forbidden)
    assert not offenders, f"home_page.py imports forbidden modules: {offenders}"
