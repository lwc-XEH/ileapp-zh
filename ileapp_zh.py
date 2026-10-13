#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iLEAPP 报告汉化工具 / iLEAPP report Chinese localiser.

把 iLEAPP 生成的 HTML 报告翻成中文。设计上只翻"结构性文本"：

    会翻  - 页面标题、模块名、模块描述（需词典）、表头 <th>、侧边栏分类与模块名、
            报告模板里的固定标签（如 Case / Extraction Location / Details）
    不翻  - 表格数据单元格 <td> 里的内容、<script>/<style> 内容、原始数据库列名

取证数据必须逐字保真，所以数据单元格一律原样保留。输出是**另存一份**，
原报告不动。

用法:
    python ileapp_zh.py <报告目录或html文件> [-o 输出目录] [--mode smart|exact]
"""

import argparse
import csv
import json
import pathlib
import re
import shutil
import sys
from collections import Counter
from html.parser import HTMLParser

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DICT_NAME = "dict_ileapp_zh.json"

# 这些标签里的文本是结构性的，可以翻
STRUCTURAL_TAGS = {"title", "th", "h1", "h2", "h3", "h4", "h5", "h6", "a", "label"}
# 这些标签里的文本是数据，只在精确命中固定标签词典时才替换
DATA_TAGS = {"td", "li", "p", "div", "span", "option", "button"}
# 完全不碰
OPAQUE_TAGS = {"script", "style"}

# 报告标题的前后缀模板，如 "X report" / "iLEAPP - X report"
AFFIX_SUFFIX = [(" report", " 报告")]
AFFIX_PREFIX = [("iLEAPP - ", "iLEAPP - ")]

# 原始数据库列名：zAsset-Date Created-0 / kMDItemFoo / _kMDItemFoo / SWYzGenAlbum-...
RAW_COLUMN_RE = re.compile(r"^[A-Za-z_]{1,24}[-_]")

# 文件名 / 路径 / bundle id / 带下划线的标识符。取证场景里必须逐字保真，
# 组合翻译一律不碰。
#   命中示例：MapTiles.sqlitedb  com.apple.mobilesafari.Plist
#             Documents/activeUser*  BDC_Daily  added_at  boot_history
#   刻意不命中：episodes.（句末句点，点后无字母）  18.1（点后是数字）
# 代价是 "Hotspot/Tethering" 这类斜杠短语也不再逐词翻译——宁可少译，不可改错。
OPAQUE_TOKEN_RE = re.compile(r"\S*(?:\.[A-Za-z][A-Za-z0-9]{0,7}\b|[/_])\S*")


def looks_like_raw_column(text: str) -> bool:
    """判断一个字符串是不是原始数据库列名，这类默认不翻。

    iLEAPP 里列名冲突时会别名成 <原列名>-<人可读名>-<序号>，例如
    zAsset-Date Created-0、SWYConverszGenAlbum-Creation Date-1。这类整体视为原始列名。
    """
    if re.match(r"^[A-Za-z0-9_]+-.*-\d+$", text):
        return True
    if " " not in text and "-" in text:
        return True
    if " " not in text and "_" in text:
        return True
    if re.match(r"^[zZ][A-Z_]", text):
        return True
    if re.match(r"^(kMDItem|_kMDItem|MK|DB)", text):
        return True
    if re.match(r"^[A-Za-z]+[A-Z][a-z]+[A-Z]", text) and " " not in text:
        return True
    return False


def plural_forms(term: str, known=None):
    """派生英文复数形式。中文不分单复数，译文沿用单数。

    只做规则派生、不递归。命中不了就是无害的空转，所以宁可多派生。

    known 是词表里已知的词集合，用来判断"以 s 结尾的词到底是不是复数"。

    判断依据是发音而不是拼写：只有 /s/ 或咝音结尾的单数才需要加 es，
    -ss（Pass→Passes）、-us（Status→Statuses）属于这类；而 -ds / -ts / -ms
    / -ics 结尾的词多半本身就是复数（Milliseconds、Loyalty Points、
    Statistics），再派生只会造出 Millisecondses 这种永不命中的垃圾词条。
    """
    if not term or not term[-1].isalpha():
        return []
    low = term.lower()
    if low.endswith(("x", "z", "ch", "sh")):
        return [term + "es"]
    if low.endswith("ss"):
        return [term + "es"]          # Pass -> Passes, Address -> Addresses
    if low.endswith("s"):
        # -us 结尾的是单数，需要 es；其余（-ds/-ts/-ms/-ics/-is…）当作已是复数
        if low.endswith("us") and not (known and term[:-1].lower() in known):
            return [term + "es"]      # Status -> Statuses, Bus -> Buses
        return []
    if low.endswith("y") and len(term) > 1 and term[-2].lower() not in "aeiou":
        return [term[:-1] + "ies"]
    if low.endswith(("f", "fe")):
        # 不派生 wives / knives 这类不规则形，风险大于收益
        return [term + "s"]
    return [term + "s"]


class Dictionary:
    def __init__(self, path: pathlib.Path):
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.ui = raw.get("ui", {})
        self.categories = raw.get("categories", {})
        self.headers = raw.get("headers", {})
        self.modules = raw.get("modules", {})
        self.descriptions = raw.get("descriptions", {})
        self.glossary = raw.get("glossary", {})
        self.patterns = [(re.compile(p), r) for p, r in raw.get("patterns", [])]

        meta = raw.get("_meta", {})
        sections = {"ui": self.ui, "categories": self.categories,
                    "headers": self.headers, "modules": self.modules,
                    "descriptions": self.descriptions}

        # 精确匹配表：只在**整串**命中时生效，顺序即优先级
        self.exact = {}
        for name in ("ui", "modules", "headers", "categories", "descriptions"):
            for k, v in sections[name].items():
                self.exact.setdefault(k, v)

        # ---------------------------------------------------------- 组合词表
        # 供 compose() 做子串替换。基础是 glossary，再叠加 _meta.compose_sections
        # 指定的额外词表（categories / modules 这类语义名词，收益明显）。
        #
        # 关键点：exact 只在整串命中时生效，所以**不能**拿它来排除组合词条——
        # 那样 Messages（住在 categories 里）就永远参与不了 "Airbnb - Messages"
        # 的组合。反过来，像 Focus->专注模式 这种"单看没问题、进组合就改坏短语"
        # （Auto Focus 会变 Auto 专注模式）的歧义词，由 _meta.compose_exclude 点名剔除。
        self.compose_extra = [s for s in meta.get("compose_sections", [])
                              if s in sections]
        excluded = {k.lower() for k in meta.get("compose_exclude", [])}

        entries = []
        taken = set()
        # 顺序很讲究：glossary 是刻意做成语境无关的通用词表，优先于分类标题。
        # 否则 categories["Messages"]="短信与消息" 会把 "Airbnb - Messages"
        # 译成 "Airbnb - 短信与消息"，而 glossary 的 Message->消息 才是对的。
        self.compose_conflicts = []
        known = {k.lower() for k in self.glossary}
        for en, zh in self.glossary.items():
            if en not in taken:
                entries.append((en, zh))
                taken.add(en)
        for en, zh in self.glossary.items():
            for plural in plural_forms(en, known):
                if plural not in taken:
                    entries.append((plural, zh))
                    taken.add(plural)
        for sec in self.compose_extra:
            for en, zh in sections[sec].items():
                if en.lower() in excluded:
                    continue
                if en in taken:
                    if dict(entries).get(en) != zh:
                        self.compose_conflicts.append((en, dict(entries)[en], zh))
                    continue
                entries.append((en, zh))
                taken.add(en)

        # 按长度倒序，保证多词短语先于单词命中
        entries.sort(key=lambda kv: len(kv[0]), reverse=True)
        self.terms = entries

        # 单趟替换：把全部词条合成一个交替正则，长词排在前面。
        #
        # 这里**不能**逐条 re.sub——那样每替换一次都会在结果上重新扫描，
        # 于是 "Apple Watch"（词表里声明为保持原样）会先被整体替换成它自己，
        # 紧接着又被后面的 Watch->手表 命中，变成 "Apple 手表"。
        # 合成一个正则做单趟扫描，替换过的片段不会被二次匹配。
        self._combined_re = re.compile(
            r"(?<![A-Za-z0-9])(" +
            "|".join(re.escape(en) for en, _ in entries) +
            r")(?![A-Za-z0-9])", re.IGNORECASE)
        self._zh_by_lower = {}
        for en, zh in entries:
            self._zh_by_lower.setdefault(en.lower(), zh)
        self.term_count = len(entries)

    # ---------------------------------------------------------------- lookups
    def exact_lookup(self, text: str):
        if text in self.exact:
            return self.exact[text]
        low = text.lower()
        for k, v in self.exact.items():
            if k.lower() == low:
                return v
        return None

    def ui_lookup(self, text: str):
        """只允许固定标签词典，用于数据单元格。"""
        if text in self.ui:
            return self.ui[text]
        for k, v in self.ui.items():
            if k.lower() == text.lower():
                return v
        return None

    def compose(self, text: str):
        """术语级组合翻译。只用于短字符串。"""
        # 长句一律不组合：句子只有零星几个词能命中，翻出来是半中半英的
        # 破碎文本，不如保持英文。这两个上限是按 iLEAPP 语料调的——
        # 最长的模块名（Connected Device Information - …）约 70 字符 / 9 词。
        if not text or len(text) > 80 or len(text.split()) > 10:
            return None
        if looks_like_raw_column(text):
            return None
        # 先把标识符摘出来存进 vault，整体替换完再原样放回。否则
        # "MapTiles.sqlitedb" 会被译成 "地图瓦片.sqlitedb"——文件名不能改。
        vault = {}

        def stash(m):
            token = "\x00%d\x00" % len(vault)
            vault[token] = m.group(0)
            return token

        out = OPAQUE_TOKEN_RE.sub(stash, text)
        zh_map = self._zh_by_lower
        new = self._combined_re.sub(
            lambda m: zh_map.get(m.group(1).lower(), m.group(1)), out)
        if new == out:
            return None
        out = new
        for token, original in vault.items():
            out = out.replace(token, original)
        out = normalize_cjk(out)
        return out if out != text else None

    # ------------------------------------------------------------ 结构性文本
    def structural(self, text: str, mode: str, translate_raw: bool):
        """结构性文本的完整翻译链：精确 -> 句式 -> 前后缀 -> 术语组合。"""
        hit = self.exact_lookup(text)
        if hit:
            return hit, "exact"

        for pat, repl in self.patterns:
            m = pat.match(text)
            if m:
                return m.expand(repl), "pattern"

        # 报告标题：'X report' / 'iLEAPP - X report'
        for suffix, suffix_zh in AFFIX_SUFFIX:
            if text.endswith(suffix):
                core = text[: -len(suffix)].rstrip()
                inner, kind = self.structural(core, mode, translate_raw)
                if inner and inner != core:
                    return inner + suffix_zh, "affix"
        for prefix, prefix_zh in AFFIX_PREFIX:
            if text.startswith(prefix):
                core = text[len(prefix):].lstrip()
                inner, kind = self.structural(core, mode, translate_raw)
                if inner and inner != core:
                    return prefix_zh + inner, "affix"

        if mode != "smart":
            return None, None
        if looks_like_raw_column(text) and not translate_raw:
            return None, "raw_column"
        composed = self.compose(text)
        if composed:
            return composed, "composed"
        return None, None


def normalize_cjk(s: str) -> str:
    """修掉中英混排里多余的空白。"""
    s = re.sub(r"\s+", " ", s).strip()
    # 中文字之间不留空格
    s = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", s)
    # 中文与英文/数字之间补一个空格，读起来舒服
    s = re.sub(r"(?<=[\u4e00-\u9fff])(?=[A-Za-z0-9])", " ", s)
    s = re.sub(r"(?<=[A-Za-z0-9])(?=[\u4e00-\u9fff])", " ", s)
    # 标点前后不留空格
    s = re.sub(r"\s+([，。、：；！？）】」])", r"\1", s)
    s = re.sub(r"([（【「])\s+", r"\1", s)
    s = re.sub(r"\s+([)）\]])", r"\1", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    return s.strip()


class ReportTranslator(HTMLParser):
    def __init__(self, dic: Dictionary, mode: str, translate_raw: bool):
        super().__init__(convert_charrefs=False)
        self.dic = dic
        self.mode = mode
        self.translate_raw = translate_raw
        self.out = []
        self.stack = []
        self.stats = Counter()
        self.changes = []          # (原文, 译文, 出现次数) 汇总在后面
        self._pending_change = None

    # ------------------------------------------------------------- tag hooks
    def handle_starttag(self, tag, attrs):
        self.out.append(self.get_starttag_text())
        self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.out.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        self.out.append(f"</{tag}>")
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i] == tag:
                del self.stack[i:]
                break

    def handle_comment(self, data):
        self.out.append(f"<!--{data}-->")

    def handle_decl(self, decl):
        self.out.append(f"<!{decl}>")

    def handle_pi(self, data):
        self.out.append(f"<?{data}>")

    def handle_entityref(self, name):
        self.out.append(f"&{name};")

    def handle_charref(self, name):
        self.out.append(f"&#{name};")

    def unknown_decl(self, data):
        self.out.append(f"<![{data}]>")

    # -------------------------------------------------------------- the work
    def handle_data(self, data):
        if any(t in OPAQUE_TAGS for t in self.stack):
            self.stats["skipped_opaque"] += 1
            self.out.append(data)
            return

        stripped = data.strip()
        if not stripped:
            self.out.append(data)
            return

        tag = self.stack[-1] if self.stack else ""
        translated = None
        kind = None

        if tag in STRUCTURAL_TAGS:
            translated, kind = self.dic.structural(
                stripped, self.mode, self.translate_raw)
            if kind == "raw_column":
                self.stats["skipped_raw_column"] += 1
                kind = None
        elif tag in DATA_TAGS:
            # 数据单元格：只认固定标签，绝不组合翻译
            translated = self.dic.ui_lookup(stripped)
            kind = "ui_label" if translated else None

        if translated and translated != stripped:
            lead = data[:len(data) - len(data.lstrip())]
            trail = data[len(data.rstrip()):]
            self.out.append(lead + translated + trail)
            self.stats[kind or "exact"] += 1
            self.changes.append((stripped, translated))
        else:
            self.stats["unchanged"] += 1
            self.out.append(data)

    def result(self):
        html = "".join(self.out)
        # 声明语言改成中文
        html = re.sub(r'(<html[^>]*\blang=")en(")', r"\1zh-CN\2", html, count=1)
        return html


def translate_html(text: str, dic: Dictionary, mode: str, translate_raw: bool):
    parser = ReportTranslator(dic, mode, translate_raw)
    parser.feed(text)
    parser.close()
    return parser.result(), parser.stats, parser.changes


def iter_html_files(src: pathlib.Path):
    if src.is_file():
        yield src
        return
    for p in sorted(src.rglob("*")):
        if p.is_file() and p.suffix.lower() in (".html", ".htm"):
            yield p


def load_dictionary(dict_path=None):
    """载入词典。dict_path 为空时用脚本同目录下的默认词典。"""
    here = pathlib.Path(__file__).resolve().parent
    p = pathlib.Path(dict_path) if dict_path else here / DICT_NAME
    if not p.exists():
        raise FileNotFoundError(f"找不到词典文件: {p}")
    return Dictionary(p)


def localize_report(source, out=None, mode="smart", raw_columns=False,
                    dict_path=None, report_csv=None, log=None):
    """把一个 iLEAPP 报告目录（或单个 .html）翻成中文，另存一份。

    供命令行和图形界面共用。返回 dict：out_dir / files / totals / changes / csv_path
    """
    emit = log or (lambda msg: None)
    dic = load_dictionary(dict_path)

    src = pathlib.Path(source).resolve()
    if not src.exists():
        raise FileNotFoundError(f"路径不存在: {src}")
    out_dir = pathlib.Path(out).resolve() if out else src.with_name(src.name + "_zh")
    if out_dir == src:
        raise ValueError("输出目录不能和源目录相同")

    # 先把整个报告复制一份（含 _elements 等资源），再只改 .html
    if out_dir.exists():
        shutil.rmtree(out_dir)
    if src.is_dir():
        shutil.copytree(src, out_dir)
        emit(f"已复制报告到: {out_dir}")
    else:
        out_dir.mkdir(parents=True, exist_ok=True)

    totals = Counter()
    all_changes = Counter()
    files_done = 0

    for html_file in iter_html_files(src):
        rel = html_file.relative_to(src) if src.is_dir() else html_file.name
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)

        # newline="" 读写，保证行尾逐字不变。
        # 默认的通用换行会把 CRLF 读成 LF，写回时又按平台翻译一遍——
        # 结果是整个文件每一行的行尾都被改写，做文件比对时满屏 diff。
        # 取证报告要求"除翻译的文本外逐字节一致"，这条必须守住。
        with html_file.open("r", encoding="utf-8", errors="replace",
                            newline="") as f:
            raw = f.read()
        new, stats, changes = translate_html(raw, dic, mode, raw_columns)
        with target.open("w", encoding="utf-8", newline="") as f:
            f.write(new)

        totals.update(stats)
        all_changes.update(changes)
        files_done += 1

    csv_path = None
    if report_csv:
        csv_path = pathlib.Path(report_csv)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["英文原文", "中文译文", "出现次数"])
            for en, zh in sorted(all_changes, key=lambda kv: -all_changes[kv]):
                w.writerow([en, zh, all_changes[(en, zh)]])

    return {
        # 路径统一返回 str，方便调用方直接塞进 JSON / 界面文本
        "out_dir": str(out_dir),
        "files": files_done,
        "totals": totals,
        "changes": all_changes,
        "csv_path": str(csv_path) if csv_path else None,
    }


def print_result(res):
    totals = res["totals"]
    print(f"\n处理 HTML 文件: {res['files']}")
    print(f"  精确匹配   : {totals['exact'] + totals['ui_label']}")
    print(f"  句式匹配   : {totals['pattern']}")
    print(f"  标题前后缀 : {totals['affix']}")
    print(f"  术语组合   : {totals['composed']}")
    print(f"  保留原文   : {totals['unchanged']}")
    print(f"  跳过原始列名: {totals['skipped_raw_column']}")
    print(f"  不同译法条数: {len(res['changes'])}")
    print(f"\n输出目录: {res['out_dir']}")
    if res["csv_path"]:
        print(f"对照表: {res['csv_path']}")


def main():
    ap = argparse.ArgumentParser(
        description="把 iLEAPP 的 HTML 报告翻成中文（另存一份，原报告不动）")
    ap.add_argument("source", help="iLEAPP 报告目录，或单个 .html 文件")
    ap.add_argument("-o", "--out", help="输出目录，默认 <源目录>_zh")
    ap.add_argument("--mode", choices=("smart", "exact"), default="smart",
                    help="smart=精确匹配+术语组合(默认)，exact=只做精确匹配")
    ap.add_argument("--raw-columns", action="store_true",
                    help="连原始数据库列名（如 zAsset-Date Created-0）也翻")
    ap.add_argument("--report", action="store_true", help="输出对照表 CSV")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    here = pathlib.Path(__file__).resolve().parent
    csv_out = (here / "翻译对照表.csv") if args.report else None
    try:
        res = localize_report(args.source, args.out, args.mode,
                              args.raw_columns, report_csv=csv_out)
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(str(exc))

    print_result(res)

    if not args.quiet and res["changes"]:
        print("\n--- 替换示例（前 25 条）---")
        for (en, zh), n in res["changes"].most_common(25):
            print(f"  {n:4d}x  {en}  ->  {zh}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
