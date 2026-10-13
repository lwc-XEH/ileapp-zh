# iLEAPP 中文工作台

把「跑 iLEAPP」和「汉化报告」合成一件事：**选检材 → 自动跑 iLEAPP → 自动出中文报告 → 自动打开。**

iLEAPP 官方没有中文版，界面和报告全是英文硬编码。这个工作台不改 iLEAPP 本体，
而是包在外面做编排：调它解析，拿到报告后自动翻成中文。**原报告不动，另存一份。**

---

## 快速开始

双击 **`start_workbench.bat`**，然后：

1. **iLEAPP 程序** —— 已自动填好（会自动在上一级目录找 `iLEAPP-2026.4.4\ileapp.exe`），
   换过位置就点「浏览」重新指定
2. **检材类型** —— 选文件/文件夹时会自动猜，猜错手动改
3. **检材路径** —— 「选文件」或「选文件夹」
4. **输出目录** —— 报告放哪
5. 点 **「▶ 开始处理」**

跑完自动打开中文报告。全程有实时日志和进度条，随时可「停止」。

> 加密的 iTunes 备份需要在「备份密码」栏填密码。

### 为什么入口叫 workbench.py 不叫中文名

`.bat` 里的中文会被 cmd 按 GBK 读成乱码，所以入口脚本用 ASCII 文件名。
**界面和文件夹名都是中文的**，只有这一个文件名是英文。

---

## 命令行方式

不想开界面也行，两个步骤各自可单独跑：

```bash
# 1) 跑 iLEAPP（用 iLEAPP 自带命令行）
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

这是整个工具最重要的设计。**取证数据必须逐字保真**，所以翻译范围是严格划定的：

### 会翻

| 位置 | 例子 |
| --- | --- |
| 页面标题 `<title>` | `iLEAPP - Battery Data Collection (BDC) - Once report` → `iLEAPP - 电池数据采集（BDC）- 一次性记录 报告` |
| 模块名 `<h3>` | `Battery Data Collection (BDC) - Once` → `电池数据采集（BDC）- 一次性记录` |
| 表头 `<th>` | `Source File` → `来源文件`；`Design Capacity (mAh)` → `设计容量（mAh）` |
| 侧边栏分类 `<h6>` | `Battery` → `电池`；`Unified Logs` → `统一日志` |
| 模板固定标签 | `Case` → `案件`；`Details` → `案件详情`；`Extraction location` → `检材位置` |
| 带变量的固定句式 | `Total number of entries: 2` → `条目总数：2` |

### 不会翻（原样保留）

| 位置 | 原因 |
| --- | --- |
| **表格数据单元格 `<td>` 的内容** | 取证数据，改了就没法作为证据。**只认固定标签词典，绝不组合翻译** |
| `<script>` / `<style>` 里的内容 | 会破坏报告功能 |
| 原始数据库列名（`zAsset-*`、`kMDItem*`、`SWYzGenAlbum-*` 等） | 是技术标识符，翻了反而看不懂、也没法跟库表对照。加 `--raw-columns` 可强制翻 |
| **文件名 / 路径 / bundle id / 带下划线的标识符** | 见下节 |
| 品牌名（`TikTok`、`Spotify`、`WhatsApp`、`Google Drive`…） | 本来就不该翻，**这是有意为之不是漏译** |

### 标识符护栏（重要）

组合翻译最容易出的事故是把文件名顺手翻了。所以引擎在翻译前会先把**标识符**整段摘出来
存好，翻译完再原样放回。命中规则：

```
命中：MapTiles.sqlitedb   com.apple.mobilesafari.Plist
      Documents/activeUser*   BDC_Daily   added_at   boot_history
不命中：episodes.（句末句点，点后无字母）   18.1（点后是数字）
```

代价是 `Hotspot/Tethering` 这类斜杠短语也不再逐词翻译 —— **宁可少译，不可改错。**

---

## 词典怎么扩充

词典是 `dict_ileapp_zh.json`，分 6 块：

```json
{
  "ui":         { "固定标签": "中文" },
  "categories": { "Battery": "电池" },
  "headers":    { "Source File": "来源文件" },
  "modules":    { "模块显示名": "中文" },
  "glossary":   { "术语": "中文" },
  "patterns":   [ ["^Total number of entries: (\\d+)$", "条目总数：\\1"] ]
}
```

翻译优先级：**精确匹配 → 句式匹配 → 标题前后缀 → 术语组合**。

想加词条直接编辑 `dict_ileapp_zh.json` 即可（UTF-8）。更推荐改 `build_dict.py`
再重新生成，因为那个文件里写了每块内容的来源和注释：

```bash
python build_dict.py     # 重新生成 dict_ileapp_zh.json
```

### 术语组合是怎么取词的（`_meta` 两个开关）

`exact` 表只在**整串**命中时生效，所以像 `Messages` 这种住在 `categories` 里的词，
默认永远参与不了 `Airbnb - Messages` 的组合。为此 `_meta` 里有两个开关：

```json
"_meta": {
  "compose_sections": ["categories", "modules"],
  "compose_exclude": ["Focus"]
}
```

- `compose_sections` —— 哪些表额外并入组合词表。`categories` / `modules` 是语义名词，
  收益明显；`headers` 里有 `Case`、`Level` 这类**短歧义词，进了组合反而改坏短语**，所以不收。
- `compose_exclude` —— 单看没问题、进组合就出事的词。`Focus`→`专注模式` 会把
  `Biome - Camera Auto Focus ROI` 变成 `相机 Auto 专注模式 ROI`，对应模块名已在
  `MODULES_EXTRA` 里点名兜住。

**优先级**：`glossary` > `compose_sections`。因为 glossary 是刻意做成语境无关的通用词表，
而 `categories["Messages"]="短信与消息"` 是侧边栏标题译法，拿去做组合会得到
`Airbnb - 短信与消息`，不如 glossary 的 `Message→消息`。冲突时保留 glossary，
并在跑 `measure_coverage.py` 时把冲突列出来供人工核对。

### 复数

英文有单复数、中文没有，所以 `plural_forms()` 会自动派生 `Message → Messages`。
判断依据是**发音**而不是拼写：只有咝音结尾的单数才需要加 `es` ——
`-ss`（`Pass→Passes`）、`-us`（`Status→Statuses`）属于这类；
而 `-ds` / `-ts` / `-ms` / `-ics` 结尾的词多半本身就是复数
（`Milliseconds`、`Loyalty Points`、`Statistics`），再派生只会造出
`Millisecondses` 这种永不命中的垃圾词条。

### 长词不会被短词拆开（单趟替换）

组合翻译是**一次扫描**，不是逐条替换。词表按长度倒序合成一个正则，
长词优先命中，且**替换过的片段不会被重新扫描**。

这条很关键：逐条 `re.sub` 会在已经替换过的文本上再扫一遍，于是
`Apple Watch`（词表里声明为"保持原样"）会先整体替换成它自己，
紧接着又被后面的 `Watch → 手表` 命中，变成 **`Apple 手表`**。
单趟替换从根上消除了这类事故。

顺带一个有用的副作用：`categories` / `modules` 里**值为自身的词条**
（`Apple Watch`、`Wi-Fi`、`Photos.sqlite`、`App Store`…）实际起到了
**保护名单**的作用 —— 它们在组合时整段命中，后面的短词规则碰不到。
所以想让某个词在任何位置都保持英文，把它加进 `categories` 并写成
`"词": "词"` 即可。

### 想翻译某个模块的描述

模块描述是长句。**smart 模式下能命中的词会被翻译，但长句只有零星几个词命中，
翻出来是半中半英的破碎文本**。要整句翻译就把它加进 `descriptions` 块精确命中：

```json
"descriptions": {
  "Static battery identity written once per battery pack from BDC_Once logs":
      "每个电池组仅写入一次的电池静态身份信息，来自 BDC_Once 日志"
}
```

不想看到半中半英就整体用 `--mode exact`，描述会保持英文原文。

### 词典是怎么来的（不是手编的）

`extract_metadata.py` 用 `ast` 解析 iLEAPP 源码，从 `scripts/artifacts/*.py` 的
`__artifacts_v2__` 里抽出全部模块名、分类、描述，从 `data_headers = (...)` 元组里抽出全部表头：

```bash
python extract_metadata.py    # 需要 src/iLEAPP-main/ 源码目录
```

当前抽出：465 个模块文件、1247 个模块、17137 个唯一表头、234 个分类。
其中绝大多数表头是 Photos.sqlite 的原始列名（`zAsset-*`），不该翻 —— 这也正是
工具默认跳过它们的原因。iLEAPP 升级后重新跑一次再补新词即可。

---

## 质量指标

`measure_coverage.py` 拿**全部真实 iLEAPP 元数据**跑一遍翻译链，是改词典时的标尺：

```bash
python measure_coverage.py             # 只出统计
python measure_coverage.py --dump      # 额外写出未翻译清单 _miss_*.txt
python measure_coverage.py --diff 旧词典.json   # 逐条比对译文变化，找回归
```

当前结果（词典 1218 条含派生复数）：

| 类别 | 样本量 | 未翻译 | 说明 |
| --- | --- | --- | --- |
| 模块名 | 1247 | **1.3%**（16 条） | 剩下 16 条全是品牌名 / Apple API 名 / IMEI·SIM 标识符 / `.plist` 文件名 / 原始列名别名 |
| 表头 | 17137 | **5.0%**（856 条） | 另有 12119 条是原始列名，按设计跳过 |
| 分类 | 234 | 41.0%（96 条） | 剩下全是品牌名，**不该翻** |
| 模块描述 | 1247 | 73.0% | 长句，见上文 |

> **上面这些数字是覆盖率，不是正确率。** 它回答的是“翻译链命中了多少”，不回答“命中的译文是否都准确”。
> 正确率下限由 [golden_set.json](golden_set.json) 提供：里面收了人工逐条核对过的关键术语、保护项和历史坑回归样本，`selftest.py` 会把它们当硬断言跑。
>
> 分类那 41% 看着高，其实是对的：`TikTok` / `Spotify` / `Reddit` / `Google Drive`
> 这些留着英文才正常。判断覆盖率好不好要看**剩余项是不是本来就该保留**。

改词典的工作流：**改 `build_dict.py` → `build_dict.py` 重新生成 → `measure_coverage.py --diff` 看有没有回归 → 跑 `selftest.py`。**

---

## 自动化测试

`selftest.py` 把上面所有检查固化成断言，一条命令跑完：

```bash
python selftest.py           # 单元 + 集成，秒级（不启动 iLEAPP）
python selftest.py --e2e     # 额外跑真实 iLEAPP 端到端（需要本机有 iLEAPP）
```

七节内容：

| 节 | 检查什么 |
| --- | --- |
| 1 词典完整性 | 词表结构、空值、垃圾复数词条、"保持原样"词条是否真被保护 |
| 2 翻译引擎单元 | 复数派生 / 列名识别 / 空白规整 / 标识符护栏 / 翻译链优先级 |
| 3 HTML 安全不变量 | 标签序列、`<script>`/`<style>`、数据单元格逐字保真、二次翻译幂等 |
| 4 错误路径 | 源不存在、输出等于源、空目录、词典缺失、**行尾保真（CRLF/LF 原样保留）** |
| 5 工作台编排 | 配置读写、检材类型猜测、`process()` 参数校验、启动脚本纯 ASCII、**界面能否真正构建** |
| 6 覆盖率阈值 | 防词典退化（模块名 ≤5%、表头 ≤10%、分类 ≤50%） |
| 7 端到端 | 真实 iLEAPP 跑一遍 → 汉化 → 不变量复验 → 部署副本一致性 |

退出码 0 表示全部通过。**改完任何东西都该跑一次。**

### 发布前检查

要对外发布时用 `release_check.py`，它连跑 N 轮并额外查两件事：

```bash
python release_check.py        # 默认 3 轮
python release_check.py 5      # 5 轮
```

| 检查 | 说明 |
| --- | --- |
| 编译 | 全部 `.py` 过一遍语法检查（不落 `__pycache__`） |
| 测试 | 调用 `selftest.py --e2e` 跑全量断言 |
| **确定性** | 同一份报告汉化两次，产物 md5 必须逐字节一致 |
| **隐私** | 扫描所有待提交文件，确认没有个人目录 / 用户名 / 本机绝对路径 |

各轮数字必须完全一致，否则说明存在随机性。**没有 iLEAPP 时默认拒绝出具
「可以发布」的结论**——端到端是这套检查里最关键的一节，静默跳过会给出虚假的
通过。确实要在没有 iLEAPP 的机器上跑，就显式加 `--allow-skip-e2e`。

> **真实报告的 md5 每次跑都会变，这是正常的。** iLEAPP 会把生成时刻写进报告
> （`artifact started at … UTC`），所以两份不同批次生成的报告本来就不同。
> 确定性检查比的是「**同一份**报告汉化两次」，验的是引擎本身是否确定；
> 跨运行恒定的那个是**合成报告**的 md5（它由测试自己造，内容固定）。
> 判断标准：轮内 md5 一致 = 引擎确定；合成报告 md5 跨次一致 = 整体没有随机性。

相关环境变量：

| 变量 | 用途 |
| --- | --- |
| `ILEAPP_EXE` | 指定 `ileapp.exe`，跳过自动查找 |
| `ILEAPP_ZH_DEPLOY` | 指定另一份部署副本，测试会 md5 比对是否同步 |
| `ILEAPP_ZH_PRIVACY_TERMS` | 额外的敏感词，分号分隔（如自己的工具目录名） |

---

## 已验证

`verify_localize.py` 把「数据逐字保真」变成可执行断言，每次改引擎都该跑一次：

```bash
python verify_localize.py <原报告目录> <汉化后目录>
```

用 iLEAPP 2026.4.4 **真实跑出的报告**测试（合成检材，含 Battery BDC_Once + Safari 历史）：

| 检查项 | 结果 |
| --- | --- |
| 自动化测试 `selftest.py --e2e` | **168 项全过**，0 失败（连跑 3 轮结果完全一致） |
| 端到端编排（检材 → 解析 → 汉化） | 退出码 0，全流程约 7 秒，1174 次进度回调 |
| 标签序列（逐标签比对） | 6/6 个 html 完全一致 |
| `<script>` / `<style>` 内容 | 6/6 逐字节一致，未被触碰 |
| 数据单元格 `<td>` | 仅 1 处固定标签被替换；**零越界改动** |
| 标识符护栏 | 全语料扫描，**0 处文件名被改坏** |
| `<html lang>` | `en` → `zh-CN` |
| 编码 | 保持 UTF-8，中文正常渲染 |

---

## 已知限制

- **模块描述长句在 smart 模式下是半中半英的**，要整句中文需逐条加词典，或用 `--mode exact` 保持英文。
- **术语组合翻译是「机翻级」**，长尾表头可能出现生硬但可读的译文。
  要完全可控就用 `--mode exact`。
- 报告里的 **`_TSV Exports`、`_Timeline`、`_lava_artifacts.db` 不翻**，只翻 HTML。
  TSV 是给工具链消费的，保持原样更稳妥。
- 需要 **Python 3.10+ 且带 tkinter**（python.org 的安装包默认带；微软商店版也带）。
- 工作台默认在**上一级目录**找 `iLEAPP-2026.4.4\ileapp.exe`。如果你把 iLEAPP 挪走了，
  点「浏览」指定一次即可，路径会记进 `工作台配置.json`。

---

## 文件清单

| 文件 | 作用 |
| --- | --- |
| `start_workbench.bat` | **主入口**，双击即开图形界面 |
| `workbench.py` | 工作台界面 + 编排逻辑（跑 iLEAPP → 自动汉化） |
| `ileapp_zh.py` | 汉化引擎，也可单独命令行调用 |
| `dict_ileapp_zh.json` | 词典（可直接编辑） |
| `build_dict.py` | 词典源码，改完重新生成 JSON |
| `selftest.py` | **自动化测试**，一条命令跑完全部检查（`--e2e` 含真实报告） |
| `release_check.py` | **发布前检查**，连跑 N 轮 + 确定性 + 隐私扫描 |
| `measure_coverage.py` | **覆盖率标尺**，改词典后复测 / 查回归 |
| `verify_localize.py` | **安全不变量校验**，比对原报告与汉化报告 |
| `extract_metadata.py` | 从 iLEAPP 源码抽取模块名/表头（升级后同步用） |
| `audit_report.py` | 列出报告里所有结构性文本，用来查词典覆盖率 |
| `工作台配置.json` | 自动生成，记住上次用的路径和选项 |
| `示例-中文报告/` | 用真实 iLEAPP 报告跑出来的汉化效果样例 |

依赖：**只用 Python 标准库**（tkinter 是标准库的一部分），不需要装任何第三方包。
