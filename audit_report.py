"""列出报告里所有"结构性文本"，用于审计词典覆盖率。"""

import pathlib
import sys
from collections import Counter
from html.parser import HTMLParser

STRUCTURAL = {"title", "th", "h1", "h2", "h3", "h4", "h5", "h6", "a", "label", "span", "h5"}
OPAQUE = {"script", "style"}


class Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.found = Counter()

    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if any(t in OPAQUE for t in self.stack):
            return
        s = data.strip()
        if not s:
            return
        tag = self.stack[-1] if self.stack else ""
        if tag in STRUCTURAL:
            self.found[(tag, s)] += 1


def main(root):
    c = Collector()
    for p in sorted(pathlib.Path(root).rglob("*.html")):
        try:
            c.feed(p.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            print("skip", p, e)
    c.close()

    print(f"结构性文本种类: {len(c.found)}\n")
    for (tag, s), n in sorted(c.found.items(), key=lambda kv: (kv[0][0], -kv[1])):
        print(f"{n:4d}x  <{tag:6s}>  {s}")


if __name__ == "__main__":
    main(sys.argv[1])
