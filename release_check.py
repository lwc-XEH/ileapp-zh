#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布前检查：连跑 N 轮完整检测，确认结果稳定、且不含个人信息。

    python release_check.py              # 默认 3 轮
    python release_check.py 5            # 5 轮
    python release_check.py --allow-skip-e2e   # 本机没有 iLEAPP 时明确接受跳过

每轮做四件事：

  1. **编译**  —— 全部 .py 过一遍语法检查（不落 __pycache__）
  2. **测试**  —— 调用 selftest.py --e2e 跑全量断言
  3. **确定性** —— 同一份报告汉化两次，产物 md5 必须逐字节一致
     真实报告只生成一次、多轮复用，所以轮内的 md5 恒定；但它的数值**每次跑
     release_check 都会变**——iLEAPP 会把生成时刻写进报告（`artifact started
     at … UTC`）。这里验的是引擎本身是否确定，不是 iLEAPP 的输出是否可复现。
  4. **隐私**  —— 扫描所有会被提交的文件，确认没有个人目录 / 用户名 / 本机路径

**没有 iLEAPP 时默认拒绝出具"可以发布"的结论**——端到端是这套检查里最关键的
一节，静默跳过会给出虚假的通过。确实要在没有 iLEAPP 的机器上跑，就显式加
--allow-skip-e2e。

任一轮出现失败，退出码非 0。

环境变量（可选）：
    ILEAPP_EXE             指定 ileapp.exe，跳过自动查找
    ILEAPP_ZH_DEPLOY       指定另一份部署副本，测试会 md5 比对是否同步
    ILEAPP_ZH_PRIVACY_TERMS 额外的敏感词，分号分隔（如自己的工具目录名）
"""

import ast
import hashlib
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

# 会被提交的文件（git 可用时以 git 为准，否则用这份白名单）
FALLBACK_FILES = [
    ".gitattributes", ".gitignore", "LICENSE", "README.md", "USAGE.zh-CN.md",
    "start_workbench.bat", "translate_report.bat",
    "workbench.py", "ileapp_zh.py", "build_dict.py", "extract_metadata.py",
    "measure_coverage.py", "verify_localize.py", "selftest.py",
    "audit_report.py", "release_check.py",
    "dict_ileapp_zh.json", "extracted.json", "golden_set.json",
    ".github/workflows/ci.yml",
]

# 隐私扫描：命中即失败。
#
# 模式刻意写成不会匹配到自身的形态——扫描器的源码里必然写着这些规则，
# 如果写成 /Users/ 这样的字面量，它第一件事就是举报自己。
# 字符类把斜杠和冒号拆开之后，源码文本里就不存在可被匹配的完整路径。
SENSITIVE_PATTERNS = [
    # Windows: X:\Users\<名字>  或  X:/Users/<名字>
    (re.compile(r"[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}[^\\/\s\"'<>|]+", re.I),
     "Windows 用户目录绝对路径"),
    # 类 Unix: /home/<名字>  或  /Users/<名字>
    (re.compile(r"/(?:home|Users)/[^/\s\"'<>|]+"),
     "类 Unix 家目录绝对路径"),
]

# 项目专属的敏感词（比如自己的工具目录名）。
# 不写死在源码里，用环境变量传入：分号分隔。
#   set ILEAPP_ZH_PRIVACY_TERMS=某个目录名;某个项目名
EXTRA_TERMS = [t.strip() for t in
               os.environ.get("ILEAPP_ZH_PRIVACY_TERMS", "").split(";")
               if t.strip()]

SUMMARY_RE = re.compile(
    r"通过 (\d+) · 失败 (\d+) · 跳过 (\d+) · 提示 (\d+)")
COVERAGE_RE = re.compile(r"([\u4e00-\u9fff]+)未翻译率 ([\d.]+)%")


# --------------------------------------------------------------------- 工具
def tracked_files():
    """返回会被提交的文件清单。

    优先问 git：已跟踪文件 + 未跟踪文件都要扫。
    否则退回白名单，至少把仓库里新增但尚未 add 的关键文件也覆盖到。
    """
    try:
        tracked = subprocess.run(["git", "ls-files"], cwd=str(HERE),
                                 capture_output=True, text=True, encoding="utf-8")
        untracked = subprocess.run(["git", "ls-files", "--others",
                                    "--exclude-standard"], cwd=str(HERE),
                                   capture_output=True, text=True, encoding="utf-8")
        paths = []
        if tracked.returncode == 0:
            paths.extend(p for p in tracked.stdout.splitlines() if p)
        if untracked.returncode == 0:
            paths.extend(p for p in untracked.stdout.splitlines() if p)
        if paths:
            seen = set()
            out = []
            for p in paths:
                key = p.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(pathlib.Path(HERE, p))
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    return [HERE / n for n in FALLBACK_FILES if (HERE / n).is_file()]


def check_compile(floor=(3, 10)):
    """编译全部 .py。用 compile() 而不是 py_compile，避免落 __pycache__。

    除了当前解释器，还会按**最低支持版本**再解析一遍：语法在 3.12+ 上合法、
    在 3.10 上报错的情况是真实存在的（f-string 表达式里用反斜杠、复用引号，
    都是 PEP 701 才放开）。CI 的矩阵里就有 3.10，这种代码会直接红。
    在本地先拦一道，省得推上去才发现。
    """
    bad = []
    files = sorted(HERE.glob("*.py"))
    floor_note = ".".join(str(n) for n in floor)
    for p in files:
        text = p.read_text(encoding="utf-8")
        try:
            compile(text, str(p), "exec")
        except (SyntaxError, UnicodeDecodeError) as exc:
            bad.append(f"{p.name}: {exc}")
            continue
        try:
            ast.parse(text, filename=str(p), feature_version=floor)
        except SyntaxError as exc:
            bad.append(f"{p.name}: 不兼容 Python {floor_note}"
                       f"（第 {exc.lineno} 行：{exc.msg}）")
    return len(files), bad


def _personal_user():
    """返回需要排查的本机用户名，CI / 通用账号名一律排除。

    为什么要排除：CI 上 USER 就是 "runner"（GitHub Actions）或
    "runneradmin"（Windows runner），而 workflow 里天然会写 runner.os
    这类官方语法。若不排除，"本机用户名 runner" 会把每个 CI 跑成红色。
    这个检查的目的是抓**个人**目录泄露，不是抓通用词。
    """
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    if user.lower() in {"runner", "runneradmin", "root", "user", "admin",
                        "administrator", "github", "actions", "ci",
                        "build", "jenkins", "docker", "vscode"}:
        return ""
    return user


def check_privacy():
    """扫描会提交的文件里有没有个人信息。"""
    hits = []
    user = _personal_user()
    for p in tracked_files():
        if not p.is_file():
            continue
        if p.suffix.lower() in (".db", ".lava", ".png", ".jpg", ".ico", ".zip", ".exe"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pat, why in SENSITIVE_PATTERNS:
                m = pat.search(line)
                if m:
                    hits.append(f"{p.name}:{i} [{why}] {m.group(0)}")
            for term in EXTRA_TERMS:
                if term in line:
                    hits.append(f"{p.name}:{i} [自定义敏感词 {term}] "
                                f"{line.strip()[:60]}")
            if user and len(user) >= 4 and user in line:
                hits.append(f"{p.name}:{i} [本机用户名 {user}] {line.strip()[:60]}")
    return hits


def check_determinism(report_dir):
    """同一份报告汉化两次，产物必须逐字节一致。返回 (ok, 说明)。"""
    with tempfile.TemporaryDirectory(prefix="det_") as td:
        td = pathlib.Path(td)
        sums = []
        for run in (1, 2):
            res = ileapp_zh.localize_report(report_dir, out=td / f"run{run}")
            out = pathlib.Path(res["out_dir"])
            h = hashlib.md5()
            for f in sorted(out.rglob("*.html")):
                h.update(f.relative_to(out).as_posix().encode())
                h.update(f.read_bytes())
            sums.append((h.hexdigest(), res["files"], len(res["changes"])))
    same = sums[0][0] == sums[1][0]
    detail = (f"{sums[0][1]} 个文件 / {sums[0][2]} 种译法 / "
              f"md5 {sums[0][0][:12]}" + ("" if same else
                                          f"  ≠ {sums[1][0][:12]}"))
    return same, detail


def make_synthetic_report(root):
    """造一份合成的"报告"，用来测确定性——不依赖 iLEAPP 是否装了。"""
    root.mkdir(parents=True, exist_ok=True)
    page = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>iLEAPP - Battery Data Collection (BDC) - Once report</title>
<style>.a{color:#123}</style>
<script>var x = "Case";</script></head>
<body>
<h6>Saved Reports</h6><h6>Total number of entries: 2</h6>
<h3 class="display-5">Battery Data Collection (BDC) - Once</h3>
<h6>Static battery identity written once per battery pack from BDC_Once logs</h6>
<table><tr><th>Timestamp</th><th>Backlight Level</th><th>zAsset-Date Created-0</th></tr>
<tr><td>2026-09-23 10:00:00</td><td>测试数据</td><td>Battery\\BDC\\BDC_Once.csv</td></tr>
<tr><td>Details</td><td>Apple Watch</td><td>MapTiles.sqlitedb</td></tr></table>
</body></html>
"""
    for name in ("_HTML/page_a.html", "_HTML/page_b.html", "index.html"):
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(page, encoding="utf-8", newline="")
    return root


def locate_exe():
    """找 ileapp.exe：环境变量 → 工作台配置文件 → 同级/上一级目录。

    直接读配置文件而不是 import workbench，免得为了一个路径把 tkinter 拖进来。
    """
    env = os.environ.get("ILEAPP_EXE")
    if env and pathlib.Path(env).is_file():
        return pathlib.Path(env)
    try:
        cfg = json.loads((HERE / "工作台配置.json").read_text(encoding="utf-8"))
        saved = cfg.get("ileapp")
        if saved and pathlib.Path(saved).is_file():
            return pathlib.Path(saved)
    except (OSError, ValueError):
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


# --------------------------------------------------------------------- 主流程
def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("-")]
    allow_skip_e2e = "--allow-skip-e2e" in sys.argv
    try:
        rounds = max(1, int(argv[0])) if argv else 3
    except ValueError:
        print(f"轮数必须是整数，收到 {argv[0]!r}")
        return 2

    print("=" * 70)
    print(f"iLEAPP 中文工作台 · 发布前检查（{rounds} 轮）")
    print(f"项目目录: {HERE}")
    print(f"解释器  : {sys.executable}")
    exe = locate_exe()
    print(f"iLEAPP  : {exe or '未找到'}")
    print("=" * 70)

    if not exe:
        print("\n!! 没找到 ileapp.exe —— 端到端检测会被跳过。")
        print("   这是发布前检查里最关键的一节（真实报告 + 安全不变量复验），")
        print("   跳过它给出的通过是不完整的。")
        print("   请设置环境变量 ILEAPP_EXE，或用 --allow-skip-e2e 明确接受跳过。")
        if not allow_skip_e2e:
            print("\n× 拒绝在缺端到端的情况下出具结论")
            return 1

    files = tracked_files()
    print(f"\n待提交文件: {len(files)} 个，共 "
          f"{sum(p.stat().st_size for p in files if p.is_file()) / 1024:.0f} KB")

    # ---- 隐私扫描只做一次（与轮次无关）
    print("\n【隐私扫描】")
    hits = check_privacy()
    if hits:
        print(f"  × 发现 {len(hits)} 处敏感信息：")
        for h in hits[:20]:
            print("      " + h)
    else:
        print("  √ 未发现个人目录 / 用户名 / 本机绝对路径")

    results = []
    with tempfile.TemporaryDirectory(prefix="release_") as td:
        td = pathlib.Path(td)
        synth = make_synthetic_report(td / "synthetic")
        real = None
        if exe:
            work = td / "e2e"
            work.mkdir()
            subprocess.run([str(exe), "-t", "fs", "-i", str(HERE / "testdata" / "fs"),
                            "-o", str(work)], cwd=str(exe.parent),
                           capture_output=True)
            cands = sorted(p for p in work.glob("iLEAPP_Output_*") if p.is_dir())
            real = cands[0] if cands else None

        for r in range(1, rounds + 1):
            print(f"\n{'─' * 70}\n第 {r}/{rounds} 轮\n{'─' * 70}")

            n_files, bad = check_compile()
            print(f"  {'√' if not bad else '×'} 编译 {n_files} 个脚本"
                  f"（兼容 Python 3.10+）"
                  + ("" if not bad else f"，{len(bad)} 个失败"))
            for b in bad:
                print("      " + b)

            proc = subprocess.run(
                [sys.executable, str(HERE / "selftest.py"), "--e2e"],
                cwd=str(HERE), capture_output=True, text=True,
                encoding="utf-8", errors="replace")
            tail = proc.stdout.strip().splitlines()[-6:]
            m = SUMMARY_RE.search(proc.stdout)
            counts = tuple(int(g) for g in m.groups()) if m else None
            cov = dict(COVERAGE_RE.findall(proc.stdout))
            if counts:
                print(f"  {'√' if counts[1] == 0 else '×'} 测试 "
                      f"通过 {counts[0]} · 失败 {counts[1]} · "
                      f"跳过 {counts[2]} · 提示 {counts[3]}")
                if cov:
                    print("      覆盖率 " + " · ".join(
                        f"{k} {v}%" for k, v in cov.items()))
            else:
                print("  × 测试未产出汇总行，原始输出尾部：")
                for l in tail:
                    print("      " + l)

            det_ok, det_txt = check_determinism(synth)
            print(f"  {'√' if det_ok else '×'} 确定性（合成报告） {det_txt}")
            real_txt = None
            if real:
                real_ok, real_txt = check_determinism(real)
                print(f"  {'√' if real_ok else '×'} 确定性（真实报告） {real_txt}")
                if r == 1:
                    print("      注：真实报告的 md5 每次跑 release_check 都会变，"
                          "因为 iLEAPP 把生成时刻写进了报告。")
                    print("      这里比的是「同一份报告译两次」，验引擎是否确定；"
                          "跨运行恒定的那一个是上面的合成报告。")
            else:
                real_ok = True

            ok = (not bad and not hits and det_ok and real_ok
                  and proc.returncode == 0 and counts is not None
                  and counts[1] == 0)
            results.append({
                "round": r, "ok": ok, "counts": counts, "cov": cov,
                "det": det_txt, "real": real_txt, "compile_bad": len(bad),
            })

    # ---- 汇总
    print(f"\n{'=' * 70}\n汇总\n{'=' * 70}")
    print(f"{'轮次':<6}{'结果':<8}{'通过':>6}{'失败':>6}{'跳过':>6}"
          f"{'提示':>6}  确定性")
    for x in results:
        c = x["counts"] or (0, 0, 0, 0)
        print(f"{x['round']:<6}{'√ OK' if x['ok'] else '× FAIL':<8}"
              f"{c[0]:>6}{c[1]:>6}{c[2]:>6}{c[3]:>6}  "
              f"{'一致' if x['det'] else '不一致'}")

    stable = len({tuple(x["counts"]) for x in results if x["counts"]}) == 1
    e2e_ran = bool(real)
    print(f"\n端到端(真实 iLEAPP): {'已执行' if e2e_ran else '**未执行**'}")
    print(f"各轮数字: {'完全一致' if stable else '**不一致**（存在随机性）'}")
    print(f"隐私扫描: {'通过' if not hits else f'{len(hits)} 处命中'}")
    all_ok = (all(x["ok"] for x in results) and not hits and stable
              and (e2e_ran or allow_skip_e2e))

    print("\n" + ("√ 可以发布" if all_ok else "× 存在问题，先修再发布"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
