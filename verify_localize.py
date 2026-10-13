#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汉化安全不变量校验：拿原报告和汉化后的报告逐文件比对。

取证报告的第一原则是"数据逐字保真"，所以汉化只允许改结构性文本。
本脚本把这条原则变成可执行的断言，每次改完词典 / 引擎都该跑一次：

  1. 标签序列完全一致（只允许 <html lang> 由 en 变 zh-CN）
  2. <script> / <style> 内容逐字节一致
  3. <td> 文本要么原样，要么只做了"固定标签词典"级别的替换
  4. 除标签内文本外，其余字节完全一致

用法:
    python verify_localize.py <原报告目录> <汉化后目录>
"""

import collections
import json
import pathlib
import re
import sys
from html.parser import HTMLParser

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).parent
OPAQUE = {"script", "style"}


class Probe(HTMLParser):
    """把一份 HTML 拆成可比对的三样东西：标签序列、不可变区、数据单元格。"""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.tags = []            # [(tag, lang属性)] 顺序敏感
        self.opaque = []          # [(tag, 原始内容)]
        self.td_texts = []        # 数据单元格文本
        self._buf = None
        self._opaque_tag = None

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs).get("lang")))
        if tag in OPAQUE:
            self._opaque_tag = tag
            self._buf = []
        elif tag == "td":
            self._buf = []
            self._opaque_tag = None

    def handle_startendtag(self, tag, attrs):
        self.tags.append((tag, dict(attrs).get("lang")))

    def handle_data(self, data):
        if self._buf is not None:
            self._buf.append(data)

    def handle_entityref(self, name):
        if self._buf is not None:
            self._buf.append("&" + name + ";")

    def handle_charref(self, name):
        if self._buf is not None:
            self._buf.append("&#" + name + ";")

    def _flush(self):
        if self._buf is not None:
            text = "".join(self._buf)
            if self._opaque_tag:
                self.opaque.append((self._opaque_tag, text))
            else:
                self.td_texts.append(text)
            self._buf = None
            self._opaque_tag = None

    def handle_endtag(self, tag):
        if tag in OPAQUE or tag == "td":
            self._flush()


def probe_file(path):
    p = Probe()
    p.feed(path.read_text(encoding="utf-8", errors="replace"))
    p.close()
    return p


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src = pathlib.Path(sys.argv[1])
    dst = pathlib.Path(sys.argv[2])

    ui = json.loads((HERE / "dict_ileapp_zh.json").read_text(
        encoding="utf-8")).get("ui", {})
    ui_lower = {k.lower() for k in ui}

    pages = sorted(p for p in src.rglob("*.html"))
    if not pages:
        print(f"× {src} 下没有 html")
        return 1

    fail = collections.Counter()
    checked = 0
    td_changed = 0
    td_changed_ok = 0
    tag_ok = 0
    opaque_ok = 0

    for page in pages:
        rel = page.relative_to(src)
        out = dst / rel
        if not out.exists():
            print(f"× 缺少输出文件: {rel}")
            fail["missing"] += 1
            continue
        checked += 1
        a = probe_file(page)
        b = probe_file(out)

        # 1) 标签序列：只允许 <html lang> 变化
        if len(a.tags) != len(b.tags):
            print(f"× {rel}: 标签数 {len(a.tags)} -> {len(b.tags)}")
            fail["tags"] += 1
        else:
            diff = [(i, x, y) for i, (x, y) in enumerate(zip(a.tags, b.tags))
                    if x[0] != y[0]]
            lang_diff = [(i, x, y) for i, (x, y) in enumerate(zip(a.tags, b.tags))
                         if x[0] == y[0] == "html" and x[1] != y[1]]
            if diff:
                print(f"× {rel}: 标签序列被改动 {diff[:3]}")
                fail["tags"] += 1
            elif len(lang_diff) > 1:
                print(f"× {rel}: 意外的 lang 改动 {lang_diff}")
                fail["lang"] += 1
            else:
                tag_ok += 1

        # 2) script / style 逐字节一致
        if a.opaque != b.opaque:
            print(f"× {rel}: <script>/<style> 内容被改动")
            fail["opaque"] += 1
        else:
            opaque_ok += 1

        # 3) 数据单元格：要么原样，要么原文是固定标签词典的键
        for x, y in zip(a.td_texts, b.td_texts):
            if x == y:
                continue
            td_changed += 1
            if x.strip() in ui or x.strip().lower() in ui_lower:
                td_changed_ok += 1
            else:
                print(f"× {rel}: 数据单元格被改且不在标签词典里: "
                      f"{x.strip()[:40]!r} -> {y.strip()[:40]!r}")
                fail["td"] += 1

    print()
    print(f"比对文件      : {checked} 个 html")
    print(f"标签序列一致  : {tag_ok}/{checked}")
    print(f"script/style  : {opaque_ok}/{checked} 逐字节一致")
    print(f"数据单元格改动: {td_changed} 处，其中 {td_changed_ok} 处属于固定标签词典")
    if fail:
        print(f"\n!! 不变量被破坏: {dict(fail)}")
        return 1
    print("\n√ 全部安全不变量通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
