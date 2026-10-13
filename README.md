# iLEAPP 中文工作台

把 [iLEAPP](https://github.com/abrignoni/iLEAPP) 的英文报告变成中文的一份，顺便把「跑解析」和「出中文报告」合成一步。

iLEAPP 是 iOS 取证的常用开源解析器，但它**没有中文版**——界面和报告模板全是英文硬编码。
这个工具不改 iLEAPP 本体，而是包在外面做编排和汉化：

```
选检材 → 自动跑 iLEAPP → 自动汉化报告 → 自动打开
```

**原报告一个字节都不动，中文版另存一份。**
**中文报告里的表格数据单元格默认逐字保真；只有固定模板标签允许替换，这条由 `verify_localize.py` 逐项断言。关键术语则由 `golden_set.json` 提供人工核对过的准确率下限。**

---

## 效果

| 位置 | 原文 | 中文 |
| --- | --- | --- |
| 页面标题 | `iLEAPP - Battery Data Collection (BDC) - Once report` | `iLEAPP - 电池数据采集（BDC）- 一次性记录 报告` |
| 表头 | `Design Capacity (mAh)` | `设计容量（mAh）` |
| 表头 | `YWW (Mfr Date Code)` | `YWW（生产日期代码）` |
| 侧边栏 | `Saved Reports` / `Unified Logs` | `已保存报告` / `统一日志` |
| 统计行 | `Total number of entries: 2` | `条目总数：2` |
| 模块名 | `Airbnb - Messages` | `Airbnb - 消息` |

---

## 特性

- **一步到位** —— 图形界面里选检材，解析完自动出中文报告，不用手动跑两次。
- **界面沿用原版观感** —— 窗口配色（深棕底 / 琥珀黄字）与图标取自 iLEAPP 原版，
  标题为 `iLEAPP 汉化版 2026.4.4`；控件文案全部中文。
- **数据逐字保真** —— 表格数据单元格 `<td>` **绝不参与组合翻译**，只认固定标签词典。
  取证场景下数据改了就没法当证据，这条是硬约束，且有自动化断言守着。
- **标识符护栏** —— 文件名 / 路径 / bundle id / 带下划线的标识符整段摘出、译完原样放回。
  `MapTiles.sqlitedb` 不会被译成 `地图瓦片.sqlitedb`。
- **覆盖率来自真实元数据** —— 词典不是手编的，是用 `ast` 从 iLEAPP 源码的
  `__artifacts_v2__` 和 `data_headers` 里抽出来的，再用实测覆盖率驱动补齐。
- **零第三方依赖** —— 只用 Python 标准库（tkinter 也是标准库）。
- **自带回归测试** —— `selftest.py` 一条命令跑完 280+ 项断言，含黄金集硬断言；有真实 iLEAPP 时还能补端到端。

---

## 快速开始

### 1. 准备 iLEAPP

从 [abrignoni/iLEAPP Releases](https://github.com/abrignoni/iLEAPP/releases) 下载 Windows 便携版
（`iLEAPP-<版本>-windows-x64-portable.zip`），解压到本工具**上一级目录**：

```
任意目录/
├── iLEAPP-2026.4.4/          ← iLEAPP 便携版解压在这里
│   └── ileapp.exe
└── iLEAPP 中文工作台/         ← 本工具
    └── 启动工作台.bat
```

放别处也行，第一次点「浏览」指定一次即可，路径会记住。

### 2. 确认有 Python 3.10+

需要带 tkinter 的 Python（[python.org](https://www.python.org/downloads/) 安装包和微软商店版都带）。

### 3. 双击 `启动工作台.bat`

然后：

1. **iLEAPP 程序** —— 通常已自动填好
2. **检材类型** —— 选文件/文件夹时自动猜，猜错手动改
3. **检材路径** —— 「选文件」或「选文件夹」
4. **输出目录** —— 中文报告放哪
5. 点 **「▶ 开始处理」**

跑完自动打开中文报告，全程有实时日志和进度条，随时可「停止」。

> 加密的 iTunes 备份需要在「备份密码」栏填密码。

---

## 命令行用法

不开界面也行，两步各自可单独跑：

```bash
# 1) 跑 iLEAPP（用 iLEAPP 自带的命令行）
ileapp.exe -t fs -i D:\检材 -o D:\out

# 2) 汉化报告
python ileapp_zh.py "D:\out\iLEAPP_Output_2026-10-13_Tuesday_105502"
```

`ileapp_zh.py` 参数：

| 参数 | 说明 |
| --- | --- |
| `source` | 报告目录，或单个 `.html` 文件 |
| `-o, --out` | 输出目录，默认 `<源目录>_zh` |
| `--mode smart` | **默认**。精确匹配 + 固定句式 + 标题前后缀 + 术语组合；覆盖率最高，但不会对 `<td>` 做术语组合，也不会把文件名 / 路径 / bundle id 这类标识符拆开翻 |
| `--mode exact` | 精确匹配 + 固定句式 + 标题前后缀，禁用术语组合；适合要完全压住长尾组合翻译时用 |
| `--raw-columns` | 让精确匹配 / 固定句式 / 标题改写作用于原始列名，但不参与术语组合 |
| `--report` | 额外输出 `翻译对照表.csv` |
| `--quiet` | 不打印替换示例 |

默认推荐 `smart`，因为它在不突破数据边界的前提下覆盖率最高：结构性文本会走完整翻译链，但**数据单元格 `<td>` 不做术语组合**，文件名 / 路径 / bundle id / 带下划线标识符会在组合翻译里整段保护。默认值不等于激进模式，它的边界是硬编码在引擎里的。

---

## 会翻什么，不会翻什么

这是整个工具最重要的设计。**取证数据必须逐字保真**，所以翻译范围是严格划定的。

### 会翻

`<title>`、模块名 `<h3>`、表头 `<th>`、侧边栏分类与模块名 `<h6>`、
报告模板固定标签（`Case` / `Details` / `Extraction Location`…）、带变量的固定句式。

### 不会翻（原样保留）

| 位置 | 原因 |
| --- | --- |
| **表格数据单元格 `<td>` 的内容** | 取证数据，改了就没法当证据。**只认固定标签词典，绝不组合翻译** |
| `<script>` / `<style>` 里的内容 | 会破坏报告功能 |
| 原始数据库列名（`zAsset-*`、`kMDItem*`、`SWYzGenAlbum-*`…） | 技术标识符，翻了反而看不懂、没法跟库表对照。加 `--raw-columns` 可强制翻 |
| 文件名 / 路径 / bundle id / 带下划线的标识符 | 见下 |
| 品牌名（`TikTok`、`Spotify`、`WhatsApp`…） | 本来就不该翻，**这是有意为之不是漏译** |

### 标识符护栏

组合翻译最容易出的事故是把文件名顺手翻了。所以引擎在翻译前会先把**标识符**整段摘出来
存好，翻译完再原样放回。命中规则：

```
命中：  MapTiles.sqlitedb    com.apple.mobilesafari.Plist
       Documents/activeUser* BDC_Daily  added_at  boot_history
不命中：episodes.（句末句点，点后无字母）   18.1（点后是数字）
```

代价是 `Hotspot/Tethering` 这类斜杠短语也不再逐词翻译 —— **宁可少译，不可改错。**

---

## 设计要点

### 为什么不用机器翻译

报告里有大量重复出现的**固定术语**（17000+ 个表头里绝大多数是同一批词），
而且**必须可复现、可审计**——同一份检材今天译成什么，明天还得是什么。
所以用的是「词典 + 受控组合」而不是模型：每个译文都能追溯到词表里的哪一条，
`measure_coverage.py` 能算出精确覆盖率，`verify_localize.py` 能证明数据没被动过。

### 单趟替换：长词不会被短词拆开

词表按长度倒序合成**一个**正则，一次扫描完成，替换过的片段不再被重新扫描。

这条很关键：逐条 `re.sub` 会在已替换的文本上再扫一遍，于是 `Apple Watch`
（词表里声明为「保持原样」）先被整体替换成它自己，紧接着又被后面的
`Watch → 手表` 命中，输出 `Apple 手表`。

顺带一个有用的副作用：`categories` / `modules` 里**值为自身的词条**
（`Apple Watch`、`Wi-Fi`、`Photos.sqlite`…）实际起到了**保护名单**的作用。
想让某个词在任何位置都保持英文，写成 `"词": "词"` 加进词表即可。

### 翻译优先级

```
精确匹配  →  句式匹配  →  标题前后缀  →  术语组合
```

组合词表由 `_meta.compose_sections` 决定把哪些表并进来；`_meta.compose_exclude`
用于剔除「单看没问题、进组合就改坏短语」的歧义词（如 `Focus → 专注模式`
会把 `Camera Auto Focus` 变成 `相机 Auto 专注模式`）。

---

## 质量指标

`measure_coverage.py` 拿**全部真实 iLEAPP 元数据**跑一遍翻译链：

```bash
python measure_coverage.py                      # 只出统计
python measure_coverage.py --dump               # 写出未翻译清单 _miss_*.txt
python measure_coverage.py --diff 旧词典.json    # 逐条比对译文变化，找回归
```

| 类别 | 样本量 | 未翻译 | 说明 |
| --- | --- | --- | --- |
| 模块名 | 1247 | **1.3%**（16 条） | 剩下 16 条全是品牌名 / Apple API 名 / IMEI·SIM 标识符 / `.plist` 文件名 / 原始列名别名 |
| 表头 | 17137 | **5.0%**（856 条） | 另有 12119 条是原始列名，按设计跳过 |
| 分类 | 234 | 41.0%（96 条） | 剩下全是品牌名，**不该翻** |
| 模块描述 | 1247 | 73.0% | 长句，`smart` 模式下是半中半英 |

> **上面这些数字是覆盖率，不是正确率。** 它回答的是“翻译链命中了多少”，不回答“命中的译文是否都准确”。
> 正确率下限由 [golden_set.json](golden_set.json) 提供：里面收了人工逐条核对过的关键术语、保护项和历史坑回归样本，`selftest.py` 会把它们当硬断言跑。
>
> 分类那 41% 看着高其实是对的：`TikTok` / `Spotify` / `Reddit` / `Google Drive`
> 这些留着英文才正常。判断覆盖率好不好，要看**剩余项是不是本来就该保留**。

---

## 开发与测试

```bash
python selftest.py           # 单元 + 集成，秒级（不启动 iLEAPP）
python selftest.py --e2e     # 额外跑真实 iLEAPP 端到端
```

八节内容：

| 节 | 检查什么 |
| --- | --- |
| 1 词典完整性 | 词表结构、空值、垃圾复数词条、「保持原样」词条是否真被保护 |
| 2 翻译引擎单元 | 复数派生 / 列名识别 / 空白规整 / 标识符护栏 / 翻译链优先级 |
| 3 HTML 安全不变量 | 标签序列、`<script>`/`<style>`、数据单元格逐字保真、二次翻译幂等 |
| 4 错误路径 | 源不存在、输出等于源、空目录、词典缺失 |
| 5 工作台编排 | 配置读写、检材类型猜测、`process()` 参数校验、启动脚本纯 ASCII、界面能否真正构建 |
| 6 覆盖率阈值 | 防词典退化（模块名 ≤5%、表头 ≤10%、分类 ≤50%） |
| 7 黄金集 | 人工核对过的关键术语、保护项与历史坑回归样本 |
| 8 端到端 | 真实 iLEAPP 跑一遍 → 汉化 → 不变量复验 |

环境变量：

| 变量 | 用途 |
| --- | --- |
| `ILEAPP_EXE` | 指定 `ileapp.exe` 路径，省去自动查找 |
| `ILEAPP_ZH_DEPLOY` | 指定另一份部署副本路径，测试会 md5 比对是否同步 |

### 独立校验工具

```bash
# 安全不变量：比对原报告与汉化报告，证明数据没被动过
python verify_localize.py <原报告目录> <汉化后目录>

# 列出报告里所有结构性文本，用来查词典覆盖情况
python audit_report.py <报告目录>
```

### 词典怎么扩充

词典是 `dict_ileapp_zh.json`，分 6 块：`ui` / `categories` / `headers` / `modules` /
`glossary` / `patterns`。可以直接编辑，但更推荐改 `build_dict.py` 再重新生成
（那个文件里写了每块内容的来源和注释）：

```bash
python build_dict.py     # 重新生成 dict_ileapp_zh.json
```

改词典的固定工作流：

```
改 build_dict.py → 重新生成 → measure_coverage.py --diff 看回归 → selftest.py
```

### iLEAPP 升级后怎么同步

`extract_metadata.py` 用 `ast` 解析 iLEAPP 源码，从 `scripts/artifacts/*.py` 的
`__artifacts_v2__` 抽模块名/分类/描述，从 `data_headers = (...)` 抽表头：

```bash
python extract_metadata.py    # 需要把 iLEAPP 源码放到 src/iLEAPP-main/
```

当前抽出：465 个模块文件、1247 个模块、17137 个唯一表头、234 个分类。
其中绝大多数表头是 Photos.sqlite 的原始列名（`zAsset-*`），不该翻——
这也正是工具默认跳过它们的原因。

---

## 项目结构

```
.
├── 启动工作台.bat          # 主入口，双击开图形界面
├── workbench.py            # 工作台界面 + 编排（跑 iLEAPP → 自动汉化）
├── ileapp_zh.py            # 汉化引擎，也可单独命令行调用
├── dict_ileapp_zh.json     # 词典（运行时读取）
├── build_dict.py           # 词典源码，改完重新生成 JSON
├── selftest.py             # 自动化测试，一条命令跑完全部检查
├── measure_coverage.py     # 覆盖率标尺，改词典后复测 / 查回归
├── verify_localize.py      # 安全不变量校验
├── extract_metadata.py     # 从 iLEAPP 源码抽取元数据（升级后同步用）
├── audit_report.py         # 列出报告里的结构性文本
├── translate_report.bat    # 拖放式汉化入口（把一个报告目录拖上去）
├── extracted.json          # 抽取结果（已提交，让测试开箱可跑）
├── testdata/               # 合成检材，供测试使用
└── 使用说明.md             # 详细手册
```

---

## 已知限制

- **模块描述长句在 `smart` 模式下是半中半英的**。要整句中文需逐条加词典，或用 `--mode exact` 保持英文。
- **术语组合是「机翻级」**，长尾表头可能出现生硬但可读的译文。要完全可控就用 `--mode exact`。
- 只翻 HTML。报告里的 **`_TSV Exports`、`_Timeline`、`_lava_artifacts.db` 不翻**——
  TSV 是给工具链消费的，保持原样更稳妥。
- 界面与报告汉化都**只针对 Windows** 做过验证（`.bat` 启动器、路径处理）。
- 需要 **Python 3.10+ 且带 tkinter**。

---

## 许可证与致谢

本项目以 **MIT License** 发布，详见 [LICENSE](LICENSE)。

它不打包、不修改、不再分发 iLEAPP 本体。上游项目：

- **[iLEAPP](https://github.com/abrignoni/iLEAPP)** — iOS Logs, Events, And Plists Parser，
  Copyright © 2020 Alexis Brignoni，MIT License。

`dict_ileapp_zh.json` 与 `extracted.json` 里包含从 iLEAPP 源码抽取的短事实性字符串
（模块名、分类名、表头名）及其中文译文，在此一并致谢。
