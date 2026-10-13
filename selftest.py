#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iLEAPP 中文工作台 —— 自动化回归测试。

改完词典 / 引擎 / 界面，跑这一条命令就知道有没有踩坏东西：

    python selftest.py           # 单元 + 集成（不启动 iLEAPP，秒级）
    python selftest.py --e2e     # 额外跑真实 iLEAPP 端到端（需要本机有 iLEAPP）
    python selftest.py --all     # 等价于 --e2e

分八节：
  1 词典完整性          静态检查词表本身有没有脏数据
  2 翻译引擎单元        复数派生 / 列名识别 / 空白规整 / 组合护栏 / 翻译链优先级
  3 HTML 安全不变量     标签序列、script/style、数据单元格逐字保真
  4 错误路径            输入不存在、输出等于源、空目录
  5 工作台编排          配置读写、类型猜测、process() 的参数校验
  6 覆盖率阈值          防词典退化（改错了数字会掉下来）
  7 黄金集              人工核对过的关键术语与历史坑回归
  8 端到端              真实 iLEAPP 跑一遍 + 汉化 + 不变量复验

退出码 0 = 全部通过。
"""

import argparse
import collections
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ileapp_zh  # noqa: E402
import verify_localize as vl  # noqa: E402


# --------------------------------------------------------------------- 框架
class Harness:
    def __init__(self):
        self.passed = 0
        self.failed = []
        self.skipped = []
        self.warnings = []
        self.section_name = ""

    def section(self, name):
        self.section_name = name
        print(f"\n{'─' * 68}\n## {name}\n{'─' * 68}")

    def ok(self, name, cond, detail=""):
        if cond:
            self.passed += 1
            print(f"  √ {name}")
        else:
            self.failed.append((self.section_name, name, detail))
            print(f"  × {name}" + (f"\n      {detail}" if detail else ""))
        return bool(cond)

    def eq(self, name, got, want):
        return self.ok(name, got == want, f"期望 {want!r}，实际 {got!r}")

    def skip(self, name, why):
        self.skipped.append((self.section_name, name, why))
        print(f"  - {name}（跳过：{why}）")

    def warn(self, name, detail):
        self.warnings.append((self.section_name, name, detail))
        print(f"  ! {name}：{detail}")

    def report(self):
        print(f"\n{'=' * 68}")
        print(f"通过 {self.passed} · 失败 {len(self.failed)} · "
              f"跳过 {len(self.skipped)} · 提示 {len(self.warnings)}")
        if self.failed:
            print("\n失败明细：")
            for sec, name, detail in self.failed:
                print(f"  [{sec}] {name}")
                if detail:
                    print(f"        {detail}")
        print("=" * 68)
        print("√ 全部通过" if not self.failed else "× 存在失败项")
        return 0 if not self.failed else 1


H = Harness()


def locate_ileapp(wb=None):
    """找本机的 ileapp.exe。

    查找顺序：环境变量 ILEAPP_EXE → 工作台自己的查找逻辑（配置文件 / 同级目录）
    → 脚本同级或上一级目录里的 iLEAPP*/。
    刻意不写死任何绝对路径——仓库里不留个人目录。
    """
    env = os.environ.get("ILEAPP_EXE")
    if env and pathlib.Path(env).is_file():
        return pathlib.Path(env)
    if wb is not None:
        try:
            found = wb.find_ileapp()
            if found:
                return pathlib.Path(found)
        except Exception:  # noqa: BLE001
            pass
    for base in (HERE, HERE.parent):
        for pat in ("ileapp.exe", "iLEAPP*/ileapp.exe", "iLEAPP*/*/ileapp.exe"):
            try:
                hits = sorted(p for p in base.glob(pat) if p.is_file())
            except OSError:
                continue
            if hits:
                return hits[0]
    return None


# ------------------------------------------------------------------ 1 词典
def section_dictionary(dic, raw):
    H.section("1 词典完整性")

    for sec in ("ui", "categories", "headers", "modules", "glossary"):
        H.ok(f"词表存在且非空: {sec}",
             isinstance(raw.get(sec), dict) and len(raw[sec]) > 0,
             f"实际 {type(raw.get(sec)).__name__} "
             f"{len(raw.get(sec, {})) if isinstance(raw.get(sec), dict) else '?'}")

    bad_key, bad_val = [], []
    for sec in ("ui", "categories", "headers", "modules", "glossary"):
        for k, v in raw.get(sec, {}).items():
            if not isinstance(k, str) or not k.strip():
                bad_key.append((sec, k))
            if not isinstance(v, str) or not v.strip():
                bad_val.append((sec, k, v))
    H.ok("所有键都是非空字符串", not bad_key, f"{bad_key[:5]}")
    H.ok("所有值都是非空字符串", not bad_val, f"{bad_val[:5]}")

    # 值里不该出现英文残留键名（说明是半成品条目）
    same = [(s, k) for s in ("ui", "categories", "headers", "modules", "glossary")
            for k, v in raw.get(s, {}).items() if k == v]
    if same:
        H.warn("键值相同的空转词条", f"{len(same)} 条，例如 {same[:5]}")
    else:
        H.passed += 1
        print("  √ 没有键值相同的空转词条")

    # _meta 的开关必须指向真实存在的表
    meta = raw.get("_meta", {})
    for s in meta.get("compose_sections", []):
        H.ok(f"compose_sections 指向真实表: {s}", s in raw)
    for w in meta.get("compose_exclude", []):
        H.ok(f"compose_exclude 的词确实存在: {w}",
             any(w in raw.get(s, {}) for s in
                 ("ui", "categories", "headers", "modules", "glossary")))

    # 句式必须能编译
    try:
        for p, _ in raw.get("patterns", []):
            re.compile(p)
        H.passed += 1
        print(f"  √ 全部句式可编译（{len(raw.get('patterns', []))} 条）")
    except re.error as exc:
        H.ok("全部句式可编译", False, str(exc))

    # 垃圾复数词条。这里用显式黑名单而不是"反推"——反推不可靠：
    # Locales 是 Locale 的合法复数，只是 local 恰好也在词表里，会被误报。
    present = {en for en, _ in dic.terms}
    banned = ["Messageses", "Notess", "Millisecondses", "Statisticses",
              "Loyalty Pointses", "Suggested Inviteses", "Make New Friendses",
              "Searched Termses", "Microsecondses", "Emergency SOSes",
              "Statuses", "Passes"]   # 最后两个是合法的，单独在下面验存在性
    hit = [b for b in banned[:-2] if b in present]
    H.ok("没有重复派生的垃圾复数词条", not hit, f"{hit}")
    for good in ("Statuses", "Passes", "Categories", "Messages", "Locations"):
        H.ok(f"合法复数仍在词表: {good}", good in present)

    # "保持原样"的词条（Apple Watch / Wi-Fi / Photos.sqlite…）不能被短词规则拆开。
    # 这类词条值为自身，靠的是组合翻译单趟扫描——逐条 sub 会把
    # Apple Watch 里的 Watch 再译一遍，变成 "Apple 手表"。
    keep = [(s, k) for s in ("categories", "modules")
            for k, v in raw.get(s, {}).items() if k == v]
    bad_keep = []
    for s, k in keep:
        if k in raw.get("glossary", {}):
            continue            # glossary 里有别的译法，以 glossary 为准
        out = dic.compose(k)
        if out and out != k:
            bad_keep.append((k, out))
    H.ok(f"保持原样的词条不被短词拆开（共 {len(keep)} 条）",
         not bad_keep, f"{bad_keep[:8]}")

    H.ok(f"词典词条数合理（含派生复数，实际 {dic.term_count}）",
         1150 <= dic.term_count <= 1350)
    return


# -------------------------------------------------------------- 2 引擎单元
def section_engine(dic):
    H.section("2 翻译引擎单元")

    known = {k.lower() for k in dic.glossary}
    cases = [
        ("Status", ["Statuses"]),
        ("Pass", ["Passes"]),
        ("Category", ["Categories"]),
        ("Box", ["Boxes"]),
        ("Messages", []),        # 去掉 s 是 Message，已在词表 -> 不再派生
        ("Notes", []),
        ("", []),
        ("Foo1", []),            # 非字母结尾
    ]
    for term, want in cases:
        H.eq(f"plural_forms({term!r})", ileapp_zh.plural_forms(term, known), want)

    H.ok("plural_forms 对空值不崩",
         ileapp_zh.plural_forms("", known) == [] and
         ileapp_zh.plural_forms("   ", known) == [])

    # 原始列名识别
    raw_cols = ["zAsset-Date Created-0", "kMDItemFoo", "_kMDItemFoo",
                "SWYConverszGenAlbum-Creation Date-1", "added_at",
                "z_PK", "MKMediaItem"]
    plain = ["Battery Level", "Use Case", "Apple Music", "Timestamp",
             "Saved Reports"]
    for t in raw_cols:
        H.ok(f"识别为原始列名: {t}", ileapp_zh.looks_like_raw_column(t))
    for t in plain:
        H.ok(f"不误判为原始列名: {t}", not ileapp_zh.looks_like_raw_column(t))

    # 空白规整
    H.eq("normalize_cjk 中文之间去空格",
         ileapp_zh.normalize_cjk("电池 数据"), "电池数据")
    H.eq("normalize_cjk 中英之间补空格",
         ileapp_zh.normalize_cjk("iOS信息"), "iOS 信息")
    H.eq("normalize_cjk 中文标点前后不留空格",
         ileapp_zh.normalize_cjk("（ 测试 ）"), "（测试）")
    H.eq("normalize_cjk 英文括号不留空格",
         ileapp_zh.normalize_cjk("电池 ( BDC )"), "电池 (BDC)")

    # 标识符护栏：文件名 / 路径 / bundle id 必须逐字保真
    guards = [
        "MapTiles.sqlitedb records",
        "Parses com.apple.mobilesafari.Plist entries",
        "Files under Documents/activeUser*",
        "BDC_Daily logs",
        "Records from boot_history table",
    ]
    for s in guards:
        out = dic.compose(s)
        ident = ileapp_zh.OPAQUE_TOKEN_RE.search(s)
        if out is None:
            H.passed += 1
            print(f"  √ 护栏：整串未译（安全）  {s}")
        else:
            H.ok(f"护栏：标识符逐字保真  {s}",
                 ident and ident.group(0) in out,
                 f"译文 {out!r} 里找不到 {ident.group(0)!r}" if ident else "无标识符")

    # 长度护栏
    H.ok("超过 80 字符不组合", dic.compose("Message " * 20) is None)
    H.ok("超过 10 词不组合", dic.compose(" ".join(["Message"] * 11)) is None)

    # 长词命中后不能被短词拆开。这是"单趟替换"要保证的核心性质：
    # 逐条 sub 会在已替换的文本上重复扫描，"Apple Watch"（声明保持原样）
    # 里的 Watch 会被 Watch->手表 再译一遍，变成 "Apple 手表"。
    keep_cases = [
        ("Apple Watch", None),
        ("Wi-Fi", None),
        ("Photos.sqlite", None),
        ("Apple Watch Mail Accounts", "Apple Watch 邮件账号"),
        ("Apple Watch Photo Collections", "Apple Watch 照片合集"),
        ("Apple Watch Weather Cities", "Apple Watch 天气城市"),
    ]
    for src, want in keep_cases:
        H.eq(f"长词不被短词拆开: {src}", dic.compose(src), want)
    H.eq("保持原样的词 structural 走精确匹配",
         dic.structural("Apple Watch", "smart", False), ("Apple Watch", "exact"))

    # 翻译链优先级
    chain = [
        ("Battery Level", "电池电量", "exact"),
        ("Backlight Level", "背光亮度", "exact"),
        ("Use Case", "使用场景", "exact"),
        ("Current Phone", "当前号码", "exact"),
        ("Timestamp", "时间戳", "exact"),
        ("Total number of entries: 2", "条目总数：2", "pattern"),
        ("Total number of files: 7", "文件总数：7", "pattern"),
        ("Airbnb - Messages", "Airbnb - 消息", "composed"),
        ("Airdrop ID", "隔空投送 ID", "composed"),
    ]
    for src, want, kind in chain:
        got, got_kind = dic.structural(src, "smart", False)
        H.eq(f"structural({src!r})", (got, got_kind), (want, kind))

    # 报告标题的前后缀
    t = "iLEAPP - Battery Data Collection (BDC) - Once report"
    H.eq("报告标题前后缀",
         dic.structural(t, "smart", False),
         ("iLEAPP - 电池数据采集（BDC）- 一次性记录 报告", "affix"))

    # raw_column 跳过
    H.eq("原始列名默认跳过",
         dic.structural("zAsset-Date Created-0", "smart", False),
         (None, "raw_column"))
    H.ok("--raw-columns 时不再跳过",
         dic.structural("zAsset-Date Created-0", "smart", True)[1] != "raw_column")

    # exact 模式：只做精确匹配，绝不组合
    H.eq("exact 模式不组合", dic.structural("Airbnb - Messages", "exact", False),
         (None, None))
    H.eq("exact 模式仍精确匹配", dic.structural("Timestamp", "exact", False),
         ("时间戳", "exact"))

    # lookup 大小写不敏感
    H.eq("exact_lookup 忽略大小写", dic.exact_lookup("timestamp"), "时间戳")
    H.eq("ui_lookup 忽略大小写", dic.ui_lookup("details"), "案件详情")
    H.eq("ui_lookup 查不到返回 None", dic.ui_lookup("2026-09-23 10:00:00"), None)

    # 数据类词不该被当作可翻的界面标签
    for w in ("Yes", "No", "On", "Off", "True", "False"):
        H.ok(f"值类词 {w} 不在界面标签表里", w not in dic.ui)


# ------------------------------------------------------ 3 HTML 安全不变量
SAMPLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>iLEAPP - Battery Data Collection (BDC) - Once report</title>
<style>.x { color: #123456; } /* Case */</style>
<script>var msg = "Case &amp; Details"; if (1 < 2) { document.write("<b>hi</b>"); }</script>
</head>
<body>
<h6>Saved Reports</h6>
<h3 class="display-5">Battery Data Collection (BDC) - Once</h3>
<h6>Static battery identity written once per battery pack</h6>
<h6>Total number of entries: 2</h6>
<table>
<tr><th>Timestamp</th><th>zAsset-Date Created-0</th><th>Backlight Level</th></tr>
<tr><td>2026-09-23 10:00:00</td><td>测试数据</td><td>+86 138 0000 0000</td></tr>
<tr><td>Details</td><td>abc123</td><td>xyz@example.com</td></tr>
</table>
</body>
</html>"""

# 这些数据单元格必须逐字不变
KEEP_TD = ["2026-09-23 10:00:00", "测试数据", "+86 138 0000 0000",
           "abc123", "xyz@example.com"]


def section_html(dic):
    H.section("3 HTML 安全不变量")

    out, stats, changes = ileapp_zh.translate_html(SAMPLE_HTML, dic, "smart", False)

    a = vl.Probe(); a.feed(SAMPLE_HTML); a.close()
    b = vl.Probe(); b.feed(out); b.close()

    H.eq("标签数一致", len(a.tags), len(b.tags))
    H.eq("标签序列一致", [t for t, _ in a.tags], [t for t, _ in b.tags])
    H.eq("script/style 逐字节一致", a.opaque, b.opaque)
    H.ok("script 原文仍在输出里", 'document.write("<b>hi</b>")' in out)
    H.ok("script 里的 Case 未被翻译", 'var msg = "Case &amp; Details"' in out)
    H.ok("style 内容未被翻译", ".x { color: #123456; } /* Case */" in out)

    H.ok('lang 由 en 改为 zh-CN', 'lang="zh-CN"' in out and 'lang="en"' not in out)
    H.ok("DOCTYPE 保留", out.startswith("<!DOCTYPE html>"))
    H.ok("meta charset 保留", '<meta charset="UTF-8">' in out)

    # 数据单元格：必须逐字保真
    for val in KEEP_TD:
        H.ok(f"数据单元格逐字保真: {val}", val in out)
    H.ok("固定标签词典可翻数据单元格（Details -> 案件详情）",
         "<td>案件详情</td>" in out)
    H.ok("原始列名表头不翻", "<th>zAsset-Date Created-0</th>" in out)

    # 结构性文本该翻
    H.ok("表头翻: Timestamp", "<th>时间戳</th>" in out)
    H.ok("表头翻: Backlight Level", "<th>背光亮度</th>" in out)
    H.ok("标题翻", "电池数据采集（BDC）- 一次性记录 报告" in out)
    H.ok("统计句翻", "条目总数：2" in out)
    H.ok("侧边栏分类翻: Saved Reports", "已保存报告" in out)

    # 幂等：把中文结果再翻一遍，数据仍然不动
    out2, _, _ = ileapp_zh.translate_html(out, dic, "smart", False)
    for val in KEEP_TD:
        H.ok(f"二次翻译仍逐字保真: {val}", val in out2)
    c = vl.Probe(); c.feed(out2); c.close()
    H.eq("二次翻译标签序列仍一致", [t for t, _ in b.tags], [t for t, _ in c.tags])

    H.ok("有实际改动发生（不是空转）", stats["unchanged"] > 0 and len(changes) > 0)
    H.ok("统计里记录了原始列名跳过", stats["skipped_raw_column"] >= 1)


# ---------------------------------------------------------------- 4 错误路径
def section_errors(dic, tmp):
    H.section("4 错误路径")

    def expect_exc(name, exc_type, fn):
        try:
            fn()
        except exc_type:
            H.passed += 1
            print(f"  √ {name}")
        except Exception as exc:  # noqa: BLE001
            H.ok(name, False, f"抛出了 {type(exc).__name__}: {exc}")
        else:
            H.ok(name, False, "没有抛异常")

    expect_exc("源路径不存在 -> FileNotFoundError", FileNotFoundError,
               lambda: ileapp_zh.localize_report(tmp / "不存在的东西"))

    empty = tmp / "空目录"
    empty.mkdir(exist_ok=True)
    res = ileapp_zh.localize_report(empty)
    H.eq("无 html 的目录不报错，处理 0 个文件", res["files"], 0)

    src = tmp / "源报告"
    src.mkdir(exist_ok=True)
    (src / "a.html").write_text("<html><body><h1>x</h1></body></html>",
                                encoding="utf-8")
    expect_exc("输出目录等于源目录 -> ValueError", ValueError,
               lambda: ileapp_zh.localize_report(src, out=src))

    expect_exc("词典路径不存在 -> FileNotFoundError", FileNotFoundError,
               lambda: ileapp_zh.load_dictionary(tmp / "没有这个词典.json"))

    # 单文件也能翻
    one = src / "a.html"
    res2 = ileapp_zh.localize_report(one)
    H.ok("单个 html 文件也能翻", pathlib.Path(res2["out_dir"], "a.html").exists())

    # 行尾保真：CRLF 进 CRLF 出，LF 进 LF 出。
    # 默认的通用换行会把 CRLF 读成 LF、写回时再按平台翻译一遍，
    # 结果是整个文件每一行的行尾都被改写——做文件比对时满屏 diff，
    # 与"除翻译文本外逐字节一致"的承诺不符。
    page = [b'<html lang="en">',
            b'<head><title>Timestamp</title></head>',
            b'<body><h1>Timestamp</h1><p>Total number of entries: 2</p></body>',
            b'</html>']
    for label, eol in (("CRLF", b"\r\n"), ("LF", b"\n")):
        d = tmp / f"行尾{label}"
        d.mkdir(exist_ok=True)
        original = eol.join(page)
        (d / "a.html").write_bytes(original)
        r = ileapp_zh.localize_report(d)
        out = (pathlib.Path(r["out_dir"]) / "a.html").read_bytes()
        H.eq(f"{label} 输入：换行数不变", out.count(eol), original.count(eol))
        if eol == b"\n":
            H.ok("LF 输入不引入 CRLF", b"\r\n" not in out)
        else:
            H.ok("CRLF 输入不残留裸 LF", out.count(b"\n") == out.count(b"\r\n"))
        H.ok(f"{label} 输入：内容确实被翻译了", "时间戳".encode() in out)


# ------------------------------------------------------------------ 5 工作台
def section_workbench(tmp):
    H.section("5 工作台编排")
    try:
        import workbench as wb
    except (ImportError, SystemExit) as exc:
        H.skip("导入 workbench", f"tkinter 不可用（{exc}）")
        return None
    H.passed += 1
    print("  √ 导入 workbench")

    # 配置读写往返（指向临时文件，别碰用户真实配置）
    old_cfg = wb.CONFIG_PATH
    wb.CONFIG_PATH = tmp / "测试配置.json"
    try:
        payload = {"ileapp": r"E:\x\ileapp.exe", "input": r"E:\检材",
                   "outdir": r"E:\out", "do_localize": True,
                   "open_after": False, "mode": "exact"}
        wb.save_config(payload)
        got = wb.load_config()
        H.eq("配置写入后能读回", got, payload)
        H.ok("配置文件是 UTF-8（中文不乱码）",
             "检材" in wb.CONFIG_PATH.read_text(encoding="utf-8"))
        wb.CONFIG_PATH = tmp / "不存在的配置.json"
        H.eq("配置不存在时返回空 dict", wb.load_config(), {})
    finally:
        wb.CONFIG_PATH = old_cfg

    # 检材类型猜测（不需要真的建文件，只按路径名判断）
    class _Var:
        def __init__(self):
            self.value = None

        def set(self, v):
            self.value = v

    class _Fake:
        def __init__(self):
            self.v_type = _Var()

    guess_cases = [
        ("/x/report.zip", "zip 压缩包"),
        ("/x/backup.tar", "tar 压缩包（含 .tar.xz）"),
        ("/x/backup.tar.xz", "tar 压缩包（含 .tar.xz）"),
        ("/x/log.gz", "gz 压缩包"),
        ("/x/disk.E01", "磁盘镜像（E01 / img / dd / dmg 等）"),
        ("/x/disk.dd", "磁盘镜像（E01 / img / dd / dmg 等）"),
        ("/x/disk.img", "磁盘镜像（E01 / img / dd / dmg 等）"),
        ("/x/notes.txt", "单个文件"),
    ]
    for path, want in guess_cases:
        f = _Fake()
        wb.App._guess_type(f, path)
        H.eq(f"猜测类型 {path}", f.v_type.value, want)

    # iTunes 备份目录：有 Manifest.db 才算
    it = tmp / "itunes"
    it.mkdir(exist_ok=True)
    (it / "Manifest.db").write_bytes(b"")
    f = _Fake()
    wb.App._guess_type(f, str(it))
    H.eq("有 Manifest.db 的目录判为 iTunes 备份",
         f.v_type.value, "iTunes / Finder 备份")

    plain = tmp / "普通文件夹"
    plain.mkdir(exist_ok=True)
    f = _Fake()
    wb.App._guess_type(f, str(plain))
    H.eq("普通目录判为已提取文件系统",
         f.v_type.value, "文件夹（已提取的文件系统）")

    # newest_report
    H.eq("newest_report 对不存在的目录返回 None",
         wb.newest_report(tmp / "根本没有这个目录"), None)
    H.eq("newest_report 对没有报告的空目录返回 None",
         wb.newest_report(plain), None)

    # process() 参数校验
    def expect_exc(name, exc_type, fn):
        try:
            fn()
        except exc_type:
            H.passed += 1
            print(f"  √ {name}")
        except Exception as exc:  # noqa: BLE001
            H.ok(name, False, f"抛出了 {type(exc).__name__}: {exc}")
        else:
            H.ok(name, False, "没有抛异常")

    out = tmp / "out"
    expect_exc("process(exe=None) -> ValueError", ValueError,
               lambda: wb.process(None, "fs", str(plain), str(out)))
    expect_exc("process(exe 不存在) -> FileNotFoundError", FileNotFoundError,
               lambda: wb.process(str(tmp / "没有.exe"), "fs", str(plain), str(out)))
    exe = locate_ileapp(wb)
    if exe:
        expect_exc("process(检材不存在) -> FileNotFoundError", FileNotFoundError,
                   lambda: wb.process(str(exe), "fs",
                                      str(tmp / "没有这个检材"), str(out)))
    else:
        H.skip("process(检材不存在)", "本机没找到 ileapp.exe")

    H.ok("输入类型表覆盖 iLEAPP 全部 -t 取值",
         {v for _, v in wb.INPUT_TYPES} ==
         {"fs", "zip", "tar", "gz", "itunes", "raw", "file"})
    H.ok("汉化模式表正确",
         {v for _, v in wb.MODE_LABELS} == {"smart", "exact"})

    # 窗口标题沿用原版 "iLEAPP version X" 的格式，只把 version 换成汉化版。
    # 这里只锁"必须带汉化二字"，具体版本号随 iLEAPP 升级可以改。
    H.ok("窗口标题含『汉化』二字", "汉化" in wb.APP_TITLE, f"当前 {wb.APP_TITLE!r}")

    # 启动脚本：纯 ASCII + CRLF，两条都是 cmd.exe 的硬要求。
    #   非 ASCII —— cmd 按控制台代码页读 .bat，中文路径会变乱码
    #   LF-only  —— 多行括号块会被解析错（实测会把 setlocal 参数拆成命令）
    for name in ("start_workbench.bat", "translate_report.bat"):
        bat = HERE / name
        if not bat.is_file():
            H.skip(name, "文件不存在")
            continue
        data = bat.read_bytes()
        n_lf = data.count(b"\n")
        n_crlf = data.count(b"\r\n")
        H.ok(f"{name} 是纯 ASCII（cmd.exe 按 GBK 读）",
             all(b < 128 for b in data),
             f"含非 ASCII 字节: {[b for b in data if b >= 128][:8]}")
        H.ok(f"{name} 是 CRLF 行尾",
             n_lf > 0 and n_crlf == n_lf,
             f"CRLF={n_crlf} LF={n_lf}")
    H.ok("start_workbench.bat 指向 workbench.py",
         b"workbench.py" in (HERE / "start_workbench.bat").read_bytes())

    # 启动器必须挑到"能 import tkinter"的那个 Python。
    # 机器上常有好几个 Python（venv / 便携版 / 嵌入式），其中一些不带
    # tkinter；pythonw 没有控制台，导入失败时窗口根本不出现、也不报错，
    # 用户双击后只会觉得"没反应"。所以启动器会逐个探测。
    launcher = HERE / "start_workbench.bat"
    if launcher.is_file() and os.name == "nt":
        probe_src = launcher.read_text(encoding="ascii").replace(
            'start "" "%PY%" "%~dp0workbench.py"', "echo CHOSEN=%PY%")
        probe = tmp / "probe_launch.bat"
        probe.write_bytes(probe_src.replace("\n", "\r\n").encode("ascii"))
        r = subprocess.run(["cmd", "/c", str(probe)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        chosen = ""
        for line in r.stdout.splitlines():
            if line.startswith("CHOSEN="):
                chosen = line[len("CHOSEN="):].strip()
        if not chosen:
            H.skip("启动器挑到带 tkinter 的 Python", "PATH 上没有可用的 Python")
        else:
            rc = subprocess.run([chosen, "-c", "import tkinter"],
                                capture_output=True).returncode
            H.ok(f"启动器挑到带 tkinter 的 Python（选中 {chosen}）", rc == 0)
    else:
        H.skip("启动器挑到带 tkinter 的 Python", "非 Windows 或找不到启动器")

    # 缺 tkinter 时不能静默死掉：pythonw 没有控制台，必须给出看得见的提示。
    # 用 stub 拦掉 tkinter 的导入，这样在任何机器上都能测。
    stub = (
        "import sys, builtins\n"
        "real = builtins.__import__\n"
        "def fake(name, *a, **k):\n"
        "    if name == 'tkinter' or name.startswith('tkinter.'):\n"
        "        raise ImportError(\"No module named 'tkinter'\")\n"
        "    return real(name, *a, **k)\n"
        "builtins.__import__ = fake\n"
        f"p = {str(HERE / 'workbench.py')!r}\n"
        "exec(compile(open(p, encoding='utf-8').read(), p, 'exec'),\n"
        "     {'__name__': '__main__', '__file__': p})\n"
    )
    # PYTHONIOENCODING 必须显式给 utf-8：CI 的 Windows runner 是英文
    # locale（cp1252），子进程往管道里写中文提示时会整体退化为 \uXXXX
    # 转义，"需要带 tkinter 的 Python" 这个断言就只在中文机器上过得去。
    # 强制 utf-8 让这条测试与系统 locale 无关。
    r = subprocess.run([sys.executable, "-c", stub], capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env=dict(os.environ, ILEAPP_ZH_NO_DIALOG="1",
                                PYTHONIOENCODING="utf-8"))
    H.eq("缺 tkinter 时退出码为 1", r.returncode, 1)
    H.ok("缺 tkinter 时给出中文提示",
         "tkinter" in r.stderr and "需要带 tkinter 的 Python" in r.stderr,
         f"stderr: {r.stderr[:200]!r}")
    H.ok("提示里点明了当前解释器路径",
         sys.executable in r.stderr or "当前解释器" in r.stderr)

    # 界面能不能真正构建出来（建好立刻隐藏并销毁，不留窗口）
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        try:
            app = wb.App(root)
            root.update_idletasks()
            H.passed += 1
            print("  √ 界面能构建（App 初始化无异常）")
            H.ok("界面输入框已初始化为字符串",
                 isinstance(app.v_exe.get(), str) and
                 isinstance(app.v_in.get(), str) and
                 isinstance(app.v_out.get(), str))
            H.ok("界面默认选中第一种检材类型",
                 app.v_type.get() == wb.INPUT_TYPES[0][0])
            H.ok("界面默认选中一种汉化模式",
                 app.v_mode.get() in [m[0] for m in wb.MODE_LABELS])
        finally:
            root.destroy()
    except Exception as exc:  # noqa: BLE001
        H.skip("界面能构建", f"无图形环境或 tkinter 异常：{exc}")
    return wb


# -------------------------------------------------------------- 6 覆盖率阈值
def section_coverage(dic):
    H.section("6 覆盖率阈值（防词典退化）")

    meta_file = HERE / "extracted.json"
    if not meta_file.is_file():
        H.skip("覆盖率阈值", f"缺少 {meta_file.name}（先跑 extract_metadata.py）")
        return
    ex = json.loads(meta_file.read_text(encoding="utf-8"))
    samples = {
        "模块名": sorted({m["name"] for m in ex["modules"] if m.get("name")}),
        "表头": sorted(ex["headers"]),
        "分类": sorted(ex["categories"]),
    }
    # 阈值按当前实测留出余量；分类里有大量品牌名，本就不该翻
    limits = {"模块名": 5.0, "表头": 10.0, "分类": 50.0}

    for name, items in samples.items():
        stat = collections.Counter()
        for t in items:
            stat[dic.structural(t, "smart", False)[1] or "none"] += 1
        miss = stat["none"]
        rate = miss * 100.0 / len(items)
        # 注意：raw_column（原始数据库列名）是**故意跳过**的，不算未翻译。
        # 表头里有 70% 是这类列名，混进来会把数字看得毫无意义。
        H.ok(f"{name}未翻译率 {rate:.1f}% ≤ {limits[name]}%"
             f"（共 {len(items)} 条，缺 {miss}，另有 "
             f"{stat['raw_column']} 条原始列名按设计跳过）",
             rate <= limits[name])

    # 反向检查：确实译出来的条数不能太少
    composed = sum(1 for t in samples["模块名"]
                   if dic.structural(t, "smart", False)[1] in
                   ("exact", "composed", "affix", "pattern"))
    H.ok(f"模块名实际译出 {composed} 条", composed > 1100,
         f"只有 {composed} 条")


# -------------------------------------------------------------- 7 黄金集断言
def section_golden(dic):
    H.section("7 黄金集（人工核对硬断言）")

    golden = HERE / "golden_set.json"
    if not golden.is_file():
        H.skip("黄金集", f"缺少 {golden.name}")
        return
    data = json.loads(golden.read_text(encoding="utf-8"))

    for src, want in data.get("translate", {}).items():
        H.eq(f"黄金集: {src!r}", dic.structural(src, "smart", False)[0], want)

    for src in data.get("protect", []):
        for mode in ("smart", "exact"):
            got, _ = dic.structural(src, mode, False)
            effective = src if got is None else got
            H.eq(f"黄金集保护({mode}): {src!r}", effective, src)

    for src, want in data.get("regression", {}).items():
        got, _ = dic.structural(src, "smart", False)
        effective = src if got is None else got
        H.eq(f"黄金集回归: {src!r}", effective, want)


# ------------------------------------------------------------------ 8 端到端
def section_e2e(tmp, wb):
    H.section("8 端到端（真实 iLEAPP）")

    exe = locate_ileapp(wb)
    if exe is None:
        H.skip("端到端", "本机没找到 ileapp.exe")
        return
    print(f"  iLEAPP: {exe}")

    testdata = HERE / "testdata" / "fs"
    if not testdata.is_dir():
        H.skip("端到端", f"测试数据不存在: {testdata}")
        return

    work = tmp / "e2e"
    work.mkdir(parents=True, exist_ok=True)

    # --- 直接调 ileapp.exe
    proc = subprocess.run(
        [str(exe), "-t", "fs", "-i", str(testdata), "-o", str(work)],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", cwd=str(exe.parent))
    H.eq("iLEAPP 退出码", proc.returncode, 0)

    reports = sorted(p for p in work.glob("iLEAPP_Output_*") if p.is_dir())
    if not H.ok("生成了报告目录", bool(reports)):
        return
    src = reports[0]
    H.ok("报告含 _HTML 目录", (src / "_HTML").is_dir())
    H.ok("报告含 TSV 导出", (src / "_TSV Exports").is_dir())

    # --- 汉化
    res = ileapp_zh.localize_report(src, mode="smart")
    dst = pathlib.Path(res["out_dir"])
    H.ok("汉化输出目录存在", dst.is_dir())
    H.ok("处理了至少 1 个 html", res["files"] >= 1)

    # --- 不变量复验
    vproc = subprocess.run(
        [sys.executable, str(HERE / "verify_localize.py"), str(src), str(dst)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    H.eq("安全不变量校验退出码", vproc.returncode, 0)
    if vproc.returncode != 0:
        print(vproc.stdout[-1500:])
    else:
        for line in vproc.stdout.strip().splitlines()[-4:]:
            print("      " + line)

    # --- 中文报告真的可打开
    H.ok("中文报告 index.html 存在", (dst / "index.html").is_file())
    pages = list((dst / "_HTML").glob("*.html"))
    if pages:
        html = pages[0].read_text(encoding="utf-8", errors="replace")
        H.ok("lang 已改为 zh-CN", 'lang="zh-CN"' in html)
        H.ok("侧边栏已中文化", "已保存报告" in html)
    else:
        H.ok("_HTML 下有页面", False)

    # --- 部署副本是否与工作区一致（同步到别处是手工步骤，容易忘）。
    # 副本位置用环境变量指定，仓库里不写死任何绝对路径。
    deploy_env = os.environ.get("ILEAPP_ZH_DEPLOY")
    deploy = pathlib.Path(deploy_env) if deploy_env else None
    if deploy is None:
        H.skip("部署副本一致性", "未设置 ILEAPP_ZH_DEPLOY 环境变量")
    elif not deploy.is_dir():
        H.skip("部署副本一致性", f"{deploy} 不存在")
    elif deploy.resolve() == HERE.resolve():
        H.skip("部署副本一致性", "当前就是在部署副本里跑的，无从比对")
    else:
        import hashlib
        stale = []
        for name in ("workbench.py", "ileapp_zh.py", "dict_ileapp_zh.json",
                     "build_dict.py", "measure_coverage.py", "verify_localize.py",
                     "selftest.py", "release_check.py", "USAGE.zh-CN.md",
                     "start_workbench.bat", "extracted.json"):
            a = HERE / name
            b = deploy / name
            if not a.is_file():
                continue
            if not b.is_file():
                stale.append(f"{name}(缺失)")
            elif hashlib.md5(a.read_bytes()).hexdigest() != \
                    hashlib.md5(b.read_bytes()).hexdigest():
                stale.append(name)
        if stale:
            H.warn("E 盘部署副本与工作区不一致", f"{stale}（需同步）")
        else:
            H.passed += 1
            print("  √ E 盘部署副本与工作区一致")

    # --- 工作台整链（进程内）
    if wb:
        logs, prog = [], []
        try:
            wres = wb.process(str(exe), "fs", str(testdata),
                              str(tmp / "e2e_wb"), do_localize=True, mode="smart",
                              log=logs.append,
                              on_progress=lambda d, t, l: prog.append((d, t)))
            H.eq("workbench.process 退出码", wres["rc"], 0)
            H.ok("process 返回可 JSON 序列化",
                 isinstance(wres["report_dir"], str) and
                 isinstance(wres["zh_dir"], str))
            H.ok("process 产出了中文报告",
                 wres["zh_dir"] and pathlib.Path(wres["zh_dir"], "index.html").is_file())
            H.ok(f"进度回调正常（{len(prog)} 次）", len(prog) > 0)
            H.ok("进度分母一致",
                 len({t for _, t in prog}) == 1, f"{sorted({t for _, t in prog})}")
        except Exception as exc:  # noqa: BLE001
            H.ok("workbench.process 整链", False, f"{type(exc).__name__}: {exc}")
            for l in logs[-6:]:
                print("      " + l)
    else:
        H.skip("workbench.process 整链", "tkinter 不可用")


# --------------------------------------------------- 0 Python 版本兼容底线
def section_pyfloor(floor=(3, 10)):
    """全部脚本必须能在最低支持版本（3.10）上解析。

    每台开发机的 Python 版本都不一样，很容易写出"我这儿能跑"却只能在
    3.12+ 解析的语法——f-string 表达式里用反斜杠或复用引号（PEP 701）就是
    典型，3.10 直接 SyntaxError。CI 矩阵里跑 3.10，这种代码推上去必红，
    所以在本地自测里先拦一道。
    """
    H.section("0 Python 版本兼容底线")
    import ast
    note = ".".join(str(n) for n in floor)
    bad = []
    files = sorted(HERE.glob("*.py"))
    for p in files:
        try:
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p),
                      feature_version=floor)
        except SyntaxError as exc:
            bad.append(f"{p.name}:{exc.lineno} {exc.msg}")
    H.ok(f"{len(files)} 个脚本都能在 Python {note} 上解析", not bad,
         "；".join(bad[:5]))
    if sys.version_info < floor:
        H.skip("当前解释器版本", f"低于 {note}，上面的结论仅供参考")


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="iLEAPP 中文工作台自动化测试")
    ap.add_argument("--e2e", "--all", dest="e2e", action="store_true",
                    help="额外跑真实 iLEAPP 端到端")
    args = ap.parse_args()

    print("iLEAPP 中文工作台 · 自动化测试")
    print(f"工作目录: {HERE}")
    print(f"解释器  : {sys.executable}")

    section_pyfloor()
    raw = json.loads((HERE / "dict_ileapp_zh.json").read_text(encoding="utf-8"))
    dic = ileapp_zh.Dictionary(HERE / "dict_ileapp_zh.json")

    section_dictionary(dic, raw)
    section_engine(dic)
    section_html(dic)

    with tempfile.TemporaryDirectory(prefix="ileapp_selftest_") as td:
        tmp = pathlib.Path(td)
        section_errors(dic, tmp)
        wb = section_workbench(tmp)
        section_coverage(dic)
        section_golden(dic)
        if args.e2e:
            section_e2e(tmp, wb)
        else:
            H.section("8 端到端（真实 iLEAPP）")
            H.skip("端到端", "未加 --e2e")

    return H.report()


if __name__ == "__main__":
    sys.exit(main())
