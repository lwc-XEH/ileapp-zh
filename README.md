# iLEAPP Report Localizer (Chinese)

[![CI](https://github.com/lwc-XEH/ileapp-zh/actions/workflows/ci.yml/badge.svg)](https://github.com/lwc-XEH/ileapp-zh/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Platform](https://img.shields.io/badge/platform-Windows-blue)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

Turn an [iLEAPP](https://github.com/abrignoni/iLEAPP) forensic report into Chinese — and fold "run the parser" and "get the Chinese report" into a single step.

iLEAPP is a widely used open-source iOS forensic parser, but it has **no Chinese version**: the UI and every report template are hard-coded English. This tool does not modify iLEAPP. It wraps around it:

```
pick evidence → run iLEAPP → localize the report → open it
```

**The original report is not touched — not one byte. The Chinese version is saved alongside it.**
Table data cells in the localized report stay byte-for-byte identical by default; only fixed template labels are allowed to change, and `verify_localize.py` asserts that item by item. Key terminology is covered by a human-verified accuracy floor in `golden_set.json`.

> Chinese-language documentation lives in **[USAGE.zh-CN.md](USAGE.zh-CN.md)**.

---

## What it changes

| Location | Original | Chinese |
| --- | --- | --- |
| Page title | `iLEAPP - Battery Data Collection (BDC) - Once report` | `iLEAPP - 电池数据采集（BDC）- 一次性记录 报告` |
| Header | `Design Capacity (mAh)` | `设计容量（mAh）` |
| Header | `YWW (Mfr Date Code)` | `YWW（生产日期代码）` |
| Sidebar | `Saved Reports` / `Unified Logs` | `已保存报告` / `统一日志` |
| Summary line | `Total number of entries: 2` | `条目总数：2` |
| Module name | `Airbnb - Messages` | `Airbnb - 消息` |

## What it does *not* change

| Location | Why |
| --- | --- |
| **Table data cells `<td>`** | Forensic data. Only a fixed label dictionary applies; **compositional translation never touches them** |
| `<script>` / `<style>` contents | Would break the report |
| Raw DB column names (`zAsset-*`, `kMDItem*`, `SWYzGenAlbum-*`) | Technical identifiers — translating them makes them harder to map back to the database. `--raw-columns` opts in |
| File names / paths / bundle IDs / underscore identifiers | See the guard below |
| Brand names (`TikTok`, `Spotify`, `WhatsApp`…) | Intentionally left alone — **by design, not an omission** |

### Identifier guard

The most common way a compositional translator breaks a forensic report is by "helpfully" translating a file name. So before translating, the engine lifts **identifiers** out as opaque tokens and puts them back verbatim afterwards.

```
Matched:     MapTiles.sqlitedb    com.apple.mobilesafari.Plist
             Documents/activeUser*  BDC_Daily  added_at  boot_history
Not matched: episodes.   (sentence-final period, no letter after)   18.1   (digit after)
```

The trade-off: slash phrases like `Hotspot/Tethering` are not translated word by word either — **better to under-translate than to corrupt**.

---

## Features

- **One step** — pick evidence in the GUI; the Chinese report is produced automatically.
- **Matches the original UI** — window colors (dark brown background / amber text) and icon are taken from iLEAPP itself; the title reads `iLEAPP 汉化版 2026.4.4`.
- **Byte-for-byte data fidelity** — `<td>` cells never participate in compositional translation. A hard constraint for forensic work, enforced by automated assertions.
- **Identifier guard** — file names, paths, bundle IDs and underscore identifiers are extracted and restored verbatim.
- **Dictionary derived from real metadata** — not hand-written. Extracted with `ast` from iLEAPP's `__artifacts_v2__` and `data_headers`, then extended against measured coverage.
- **Zero third-party dependencies** — Python standard library only (tkinter included).
- **Regression tests included** — 280+ assertions in one command, including the golden set. End-to-end against real iLEAPP when one is installed.

---

## Quick start

### 1. Get iLEAPP

Download the Windows portable build from [abrignoni/iLEAPP Releases](https://github.com/abrignoni/iLEAPP/releases) (`iLEAPP-<version>-windows-x64-portable.zip`) and extract it **one level above** this tool:

```
any-folder/
├── iLEAPP-2026.4.4/          ← iLEAPP portable extracted here
│   └── ileapp.exe
└── ileapp-zh/                ← this tool
    └── start_workbench.bat
```

Anywhere else works too — point the GUI at `ileapp.exe` once and the path is remembered.

### 2. Confirm you have Python 3.10+

You need a Python build **with tkinter** (the installer from [python.org](https://www.python.org/downloads/) includes it).

### 3. Double-click `start_workbench.bat`

Then:

1. **iLEAPP executable** — usually filled in automatically
2. **Evidence type** — guessed from the file/folder you pick; correct it manually if wrong
3. **Evidence path** — "Select file" or "Select folder"
4. **Output directory** — where the Chinese report goes
5. Click **▶ 开始处理** ("Start")

The Chinese report opens automatically when it finishes. There is a live log and progress bar, and you can stop at any time.

> Encrypted iTunes backups need the password entered in the password field.

---

## Command line

The GUI is optional. Both halves can run independently:

```bash
# 1) Run iLEAPP (using its own CLI)
ileapp.exe -t fs -i D:\evidence -o D:\out

# 2) Localize the report
python ileapp_zh.py "D:\out\iLEAPP_Output_2026-10-13_Tuesday_105502"
```

`ileapp_zh.py` arguments:

| Argument | Description |
| --- | --- |
| `source` | Report directory, or a single `.html` file |
| `-o, --out` | Output directory, defaults to `<source>_zh` |
| `--mode smart` | **Default.** Exact matches + variable patterns + title affixes + term composition. Highest coverage, but never composes inside `<td>`, and never splits an identifier |
| `--mode exact` | Exact matches + variable patterns + title affixes, with term composition disabled |
| `--raw-columns` | Let exact matches / patterns / title affixes apply to raw column names too — they still do not take part in term composition |
| `--report` | Also write `翻译对照表.csv` (a translation mapping table) |
| `--quiet` | Do not print replacement examples |

`smart` is the default because it maximizes coverage without crossing the data boundary: structural text runs the full chain, while `<td>` cells skip composition and identifiers are protected as whole tokens. The default is not the aggressive setting — its limits are hard-coded in the engine.

---

## Design notes

### Why not machine translation

Reports repeat a large number of **fixed terms** (the vast majority of 17,000+ headers come from a small pool of words), and results **must be reproducible and auditable** — what a report translates to today must be what it translates to next year. So the engine is a "dictionary + controlled composition", not a model: every translation traces back to a dictionary entry, `measure_coverage.py` computes exact coverage, and `verify_localize.py` proves the data was not altered.

### Single-pass replacement: long terms are never split by short ones

All entries are sorted longest-first into **one** regular expression and applied in a single scan; spans that were already replaced are not rescanned.

This matters because repeated `re.sub` calls would rescan already-translated text: `Apple Watch` (declared "keep as-is") would first be replaced with itself, then immediately hit by `Watch → 手表`, producing `Apple 手表`.

A useful side effect: entries in `categories` / `modules` whose **value equals their key** (`Apple Watch`, `Wi-Fi`, `Photos.sqlite`…) act as a **protection list**. To keep any term in English everywhere, add it as `"term": "term"`.

### Translation precedence

```
exact match  →  pattern  →  title affix  →  term composition
```

Which tables feed composition is controlled by `_meta.compose_sections`; `_meta.compose_exclude` removes ambiguous words that are fine alone but corrupt phrases in composition (e.g. `Focus → 专注模式` would turn `Camera Auto Focus` into `相机 Auto 专注模式`).

---

## Quality metrics

`measure_coverage.py` runs the full translation chain over **all real iLEAPP metadata**:

```bash
python measure_coverage.py                      # statistics only
python measure_coverage.py --dump               # also write untranslated lists
python measure_coverage.py --diff old.json      # diff every translation against an older dictionary
```

| Category | Sample | Untranslated | Notes |
| --- | --- | --- | --- |
| Module names | 1247 | **1.3%** (16) | All brand names / Apple API names / IMEI·SIM identifiers / `.plist` file names |
| Headers | 17137 | **5.0%** (856) | A further 12119 are raw column names, skipped by design |
| Categories | 234 | 41.0% (96) | All brand names — **should not be translated** |
| Module descriptions | 1247 | 73.0% | Long prose; half-translated in `smart` mode |

> **These figures are coverage, not accuracy.** They measure how much of the real metadata the chain hits — not whether each hit is correct.
> The accuracy floor comes from `golden_set.json`: human-verified terms, protected identifiers, and historical regression cases, asserted in `selftest.py`.
>
> The 41% for categories is expected: `TikTok` / `Spotify` / `Reddit` / `Google Drive` are correct in English. Coverage should be judged by whether the **remaining items are ones that should be preserved**.

---

## Development

```bash
python selftest.py           # unit + integration, seconds (does not start iLEAPP)
python selftest.py --e2e     # also runs real iLEAPP end-to-end
```

Nine sections:

| # | What it checks |
| --- | --- |
| 0 | Python floor — every script must parse on Python 3.10 (the declared minimum) |
| 1 | Dictionary integrity — structure, empty values, junk plurals, "keep as-is" protection |
| 2 | Engine units — plural derivation, column detection, whitespace, identifier guard, chain precedence |
| 3 | HTML safety invariants — tag sequence, `<script>`/`<style>`, byte-for-byte `<td>`, idempotence |
| 4 | Error paths — missing source, output equals source, empty directory, missing dictionary |
| 5 | Workbench — config round-trip, evidence type guessing, `process()` validation, launcher, GUI construction |
| 6 | Coverage thresholds — guards against dictionary regression (modules ≤5%, headers ≤10%, categories ≤50%) |
| 7 | Golden set — human-verified terms, protected identifiers, historical regression cases |
| 8 | End-to-end — real iLEAPP run → localize → re-verify invariants |

Section 0 exists because a development machine may run a newer Python than the declared
minimum. Syntax that parses on 3.12+ but not on 3.10 (backslashes or reused quotes inside
f-string expressions, both unlocked by PEP 701) would otherwise pass locally and fail only
in CI. `release_check.py` performs the same floor check during compilation.

### Release check

```bash
python release_check.py 1 --allow-skip-e2e
```

Compiles every script, runs the full test suite, verifies determinism (the same report localized twice must produce byte-identical output), and scans every file that would be committed for personal paths or usernames.

### Independent verification tools

```bash
# Safety invariants: compare the original report against the localized one
python verify_localize.py <original-report-dir> <localized-dir>

# List all structural text in a report (to audit dictionary coverage)
python audit_report.py <report-dir>
```

### Extending the dictionary

The dictionary is `dict_ileapp_zh.json`, with six sections: `ui` / `categories` / `headers` / `modules` / `glossary` / `patterns`. It can be edited directly, but editing `build_dict.py` and regenerating is preferred (that file documents each section's source):

```bash
python build_dict.py     # regenerate dict_ileapp_zh.json
```

Workflow for dictionary changes:

```
edit build_dict.py → regenerate → measure_coverage.py --diff (check for regressions) → selftest.py
```

### Syncing after an iLEAPP upgrade

`extract_metadata.py` parses iLEAPP's source with `ast`, pulling module names / categories / descriptions from `__artifacts_v2__` and headers from `data_headers`:

```bash
python extract_metadata.py    # requires iLEAPP source at src/iLEAPP-main/
```

Currently extracted: 465 module files, 1247 modules, 17137 unique headers, 234 categories. The vast majority of headers are Photos.sqlite raw column names (`zAsset-*`), which should not be translated — which is exactly why the tool skips them by default.

---

## Project structure

```
.
├── start_workbench.bat     # main entry point, double-click to open the GUI
├── workbench.py            # GUI + orchestration (run iLEAPP → localize)
├── ileapp_zh.py            # localization engine, also usable as a CLI
├── dict_ileapp_zh.json     # dictionary (read at runtime)
├── build_dict.py           # dictionary source; regenerate the JSON after editing
├── selftest.py             # automated tests, one command for everything
├── measure_coverage.py     # coverage yardstick; re-measure after dictionary changes
├── verify_localize.py      # safety invariant checker
├── extract_metadata.py     # extract metadata from iLEAPP source (for upgrades)
├── audit_report.py         # list structural text in a report
├── translate_report.bat    # drag-and-drop localization entry point
├── golden_set.json         # human-verified translations, protected IDs, regressions
├── extracted.json          # extraction output (committed so tests run out of the box)
├── testdata/               # synthetic evidence used by the tests
├── USAGE.zh-CN.md          # detailed manual (Chinese)
└── .github/workflows/ci.yml
```

---

## Known limitations

- **Module descriptions are half-translated in `smart` mode.** Full Chinese requires adding entries per description, or using `--mode exact` to keep them in English.
- **Term composition is machine-translation grade.** Long-tail headers may read awkwardly though understandably. Use `--mode exact` for full control.
- **HTML only.** `_TSV Exports`, `_Timeline` and `_lava_artifacts.db` inside the report are not translated — TSV is consumed by tooling and is safer left as-is.
- **Windows only** for both the GUI and localization (`.bat` launchers, path handling).
- Requires **Python 3.10+ with tkinter**.

---

## License and acknowledgements

Released under the **MIT License** — see [LICENSE](LICENSE).

This project does not bundle, modify, or redistribute iLEAPP itself. Upstream:

- **[iLEAPP](https://github.com/abrignoni/iLEAPP)** — iOS Logs, Events, And Plists Parser,
  Copyright © 2020 Alexis Brignoni, MIT License.

`dict_ileapp_zh.json` and `extracted.json` contain short factual strings extracted from iLEAPP's
source (module names, category names, header names) together with their Chinese translations.
Credit and thanks to the iLEAPP project.
