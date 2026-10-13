# -*- coding: utf-8 -*-
"""复现 CI：不同 stderr 编码下，缺 tkinter 提示测试的断言结果。"""
import os, subprocess, sys, pathlib

HERE = pathlib.Path(".").resolve()
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

def run(io_encoding):
    env = dict(os.environ, ILEAPP_ZH_NO_DIALOG="1")
    if io_encoding:
        env["PYTHONIOENCODING"] = io_encoding
    r = subprocess.run([sys.executable, "-c", stub], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env)
    stderr = r.stderr
    check1 = r.returncode == 1
    check2 = "tkinter" in stderr and "需要带 tkinter 的 Python" in stderr
    check3 = sys.executable in stderr or "当前解释器" in stderr
    print(f"  PYTHONIOENCODING={io_encoding or '(默认/locale)'}: "
          f"rc={r.returncode} | 断言1(退出码1)={'过' if check1 else '挂'} "
          f"| 断言2(中文提示)={'过' if check2 else '挂'} "
          f"| 断言3(解释器路径)={'过' if check3 else '挂'}")
    print(f"    stderr 前 120 字符: {stderr[:120]!r}")

print("当前 locale:", sys.stdout.encoding)
run(None)          # 不设置 -> 用系统 locale（复现 CI 的根因）
run("cp1252")      # 明确模拟 CI 英文 locale
run("utf-8")       # 修复方案
