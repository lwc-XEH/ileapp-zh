"""Extract iLEAPP artifact metadata (names, categories, headers) from source.

Uses ast so we read the real string literals rather than guessing with regex.
"""

import ast
import json
import pathlib
import sys
from collections import Counter

SRC = pathlib.Path(__file__).parent / "src" / "iLEAPP-main" / "scripts" / "artifacts"


def str_const(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def collect_strings(node):
    """All string literals inside an expression (handles tuples, implicit concat)."""
    out = []
    for sub in ast.walk(node):
        s = str_const(sub)
        if s is not None:
            out.append(s)
    return out


def parse_file(path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError as exc:
        return [], [], f"SyntaxError: {exc}"

    modules = []
    headers = []

    for node in tree.body:
        # __artifacts_v2__ = { "key": { "name": ..., "category": ... } }
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__artifacts_v2__" for t in node.targets
        ):
            if isinstance(node.value, ast.Dict):
                for k, v in zip(node.value.keys, node.value.values):
                    key = str_const(k)
                    if key is None or not isinstance(v, ast.Dict):
                        continue
                    meta = {}
                    for mk, mv in zip(v.keys, v.values):
                        mkey = str_const(mk)
                        if mkey in ("name", "description", "category"):
                            meta[mkey] = str_const(mv) or ""
                    modules.append({"key": key, "file": path.name, **meta})

        # data_headers = (...)   /   headers = (...)  -- declared inside function bodies
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in ("data_headers", "headers"):
                    headers.extend(collect_strings(node.value))

    # walk the whole tree: data_headers assignments live inside function bodies,
    # and some modules pass headers=(...) straight into create_artifact()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in ("data_headers", "headers"):
                    headers.extend(collect_strings(node.value))
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "headers":
                    headers.extend(collect_strings(kw.value))

    return modules, headers, None


def main():
    files = sorted(SRC.glob("*.py"))
    all_modules, all_headers, errors = [], [], []
    for f in files:
        mods, hdrs, err = parse_file(f)
        all_modules.extend(mods)
        all_headers.extend(hdrs)
        if err:
            errors.append((f.name, err))

    # de-dupe headers, keep frequency
    freq = Counter(h for h in all_headers if h and h.strip())
    uniq_headers = sorted(freq)

    categories = Counter(m.get("category", "") for m in all_modules if m.get("category"))
    names = sorted({m.get("name", "") for m in all_modules if m.get("name")})

    result = {
        "stats": {
            "files": len(files),
            "modules": len(all_modules),
            "unique_module_names": len(names),
            "unique_headers": len(uniq_headers),
            "header_occurrences": sum(freq.values()),
            "unique_categories": len(categories),
            "parse_errors": len(errors),
        },
        "categories": dict(categories.most_common()),
        "modules": all_modules,
        "headers": dict(freq.most_common()),
        "errors": errors,
    }

    out = pathlib.Path(__file__).parent / "extracted.json"
    # newline="\n"：固定 LF，避免 Windows 上写出 CRLF 造成行尾 diff
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                   encoding="utf-8", newline="\n")

    print(json.dumps(result["stats"], ensure_ascii=False, indent=2))
    print("\n--- categories (top 40) ---")
    for c, n in categories.most_common(40):
        print(f"{n:5d}  {c}")
    print("\n--- headers (top 40 by frequency) ---")
    for h, n in freq.most_common(40):
        print(f"{n:5d}  {h}")
    print(f"\nwritten: {out}")
    if errors:
        print(f"\n!! {len(errors)} files failed to parse")


if __name__ == "__main__":
    sys.exit(main())
