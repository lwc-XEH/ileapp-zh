#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对全部 iLEAPP 元数据跑一遍翻译链，量化词典覆盖率。

这是"完善汉化"时的标尺：改完词典 / 引擎就跑一次，看数字涨没涨、有没有回归。

    python measure_coverage.py            # 只出统计
    python measure_coverage.py --dump     # 额外写出未翻译清单 _miss_*.txt
    python measure_coverage.py --diff 旧词典.json   # 与旧词典逐条比对译文变化
"""

import argparse
import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from ileapp_zh import Dictionary  # noqa: E402

HERE = pathlib.Path(__file__).parent
KINDS = ("exact", "pattern", "affix", "composed", "raw_column", "none")


def load_samples():
    ex = json.loads((HERE / "extracted.json").read_text(encoding="utf-8"))
    return {
        "模块名": sorted({m["name"] for m in ex["modules"] if m.get("name")}),
        "表头": sorted(ex["headers"]),
        "分类": sorted(ex["categories"]),
        "模块描述": sorted({m["description"] for m in ex["modules"]
                        if m.get("description")}),
    }


def measure(d, samples, label):
    """返回 {类别: (统计Counter, 未翻译list)}。"""
    result = {}
    for name, items in samples.items():
        stat = collections.Counter()
        miss = []
        for t in items:
            _, kind = d.structural(t, "smart", False)
            kind = kind or "none"
            stat[kind] += 1
            if kind == "none":
                miss.append(t)
        result[name] = (stat, miss)
    return result


def report(result):
    for name, (stat, miss) in result.items():
        n = sum(stat.values())
        print(f"[{name}] 共 {n}")
        for k in KINDS:
            if stat[k]:
                print(f"   {k:<11} {stat[k]:>6}  {stat[k] * 100.0 / n:5.1f}%")
        print(f"   -> 未翻译 {len(miss)} 条 ({len(miss) * 100.0 / n:.1f}%)")
        print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true", help="写出未翻译清单")
    ap.add_argument("--diff", metavar="OLD_DICT",
                    help="与旧词典比对译文变化（找回归）")
    args = ap.parse_args()

    d = Dictionary(HERE / "dict_ileapp_zh.json")
    print(f"词典词条（含派生复数）: {d.term_count}")
    if d.compose_extra:
        print(f"组合词表额外叠加: {d.compose_extra}")
    if getattr(d, "compose_conflicts", None):
        print(f"词表优先级冲突 {len(d.compose_conflicts)} 条"
              f"（已采用 glossary 值）:")
        for en, kept, dropped in d.compose_conflicts[:15]:
            print(f"   {en!r}: 保留 {kept!r} / 丢弃 {dropped!r}")
    print("=" * 66)

    samples = load_samples()
    result = measure(d, samples, "current")
    report(result)

    if args.dump:
        names = {"模块名": "_miss_names.txt", "表头": "_miss_headers.txt",
                 "分类": "_miss_cats.txt", "模块描述": "_miss_descs.txt"}
        for k, fn in names.items():
            items = result[k][1]
            (HERE / fn).write_text("\n".join(items), encoding="utf-8",
                                   newline="\n")
            print(f"写出 {fn} ({len(items)})")

    if args.diff:
        old = Dictionary(pathlib.Path(args.diff))
        print("\n" + "=" * 66)
        print(f"与 {args.diff} 比对译文变化")
        changed = 0
        for name, items in samples.items():
            print(f"\n### {name}")
            shown = 0
            for t in items:
                a, ka = old.structural(t, "smart", False)
                b, kb = d.structural(t, "smart", False)
                if (a or t) != (b or t):
                    changed += 1
                    if shown < 30:
                        print(f"   {t[:46]:<46} {(a or '—')[:26]}  =>  {b or '—'}")
                        shown += 1
            if shown == 0:
                print("   （无变化）")
            elif shown == 30:
                print("   ...")
        print(f"\n共 {changed} 条译文发生变化")


if __name__ == "__main__":
    main()
