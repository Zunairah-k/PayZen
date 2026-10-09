"""Prints what every backend file contains: purpose line, classes, functions, API routes, test counts.
Run: python -m tests.system_map"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def routes(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in node.decorator_list:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                        and d.func.attr in ("get", "post", "put", "delete", "patch")
                        and d.args and isinstance(d.args[0], ast.Constant)):
                    yield d.func.attr.upper(), d.args[0].value, node.name


if __name__ == "__main__":
    for path in sorted((ROOT / "backend").rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        doc = (ast.get_docstring(tree) or "(no description)").splitlines()[0]
        names = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                 and not n.name.startswith("_")]
        print(f"\n{path.relative_to(ROOT)}\n   {doc}\n   defines: {', '.join(names[:12])}{' ...' if len(names) > 12 else ''}")
        for method, url, fn in routes(tree):
            print(f"   ROUTE {method} {url}  ->  {fn}")
    print("\nTests per file:")
    for path in sorted((ROOT / "tests").rglob("test_*.py")):
        print(f"   {path.relative_to(ROOT)}: {path.read_text(encoding='utf-8', errors='ignore').count('def test_')} tests")