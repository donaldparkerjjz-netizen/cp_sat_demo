# 设备编号数据对齐 — 字段说明文档（整经/织造/水洗）

> 本文件说明 `weaving_demo/equipment.py` 产出的 4 个 JSON 文件里各字段的来源、
> 中文业务含义、类型与示例。数据由 `equipment.py` 从益丰生产管理表单 Excel 逐表清洗映射而来。

## 1. `equipment_master.json` —— 统一设备主档

顶层：`{generated_by, equipment_type_legend, equipment: [记录...]}`。
`equipment_type_legend`：`LOOM=织造/织机`、`WASH=水洗/水洗机`、`WAR=整经/整经机`。

每条记录字段：

| 字段 | 业务含义 | 来源 | 类型 | 示例 |
|---|---|---|---|---|
| `equipment_id` | 系统主键（流程前缀+编号） | 规则生成 | str | `LOOM-301` / `WASH-01` |
| `process_type` | 所属流程 | 规则 | str | `织造` / `水洗` / `整经` |
| `display_code` | 页面展示的现场编号 | 规则生成 | str | `#301织机` / `1号水洗机` |
| `equipment_name` | 设备名称 | 规则生成 | str | `织机 301` / `水洗机 1` |
| `source_code` | 源表原始编号（去杂质后） | 源表 | str | `#301` / `1号水洗机` |
| `source_sheet` | 所在源表 | 源表 | str | `②织机状态` |
| `source_cell` | 源表单元格（如 B9） | 源表 | str | `B9` |
| `source_value` | 源表单元格原始值 | 源表 | any | `#301` |
| `equipment_type` | 设备类别 | 规则 | str | `织机` / `水洗机` / `整经机` |
| `status` | 设备当前状态 | 源表（清洗） | str | `未安排` / `排产计划中` / `待确认/不可用` |
| `capacity_value` | 产能 | 源表（回填） | float/null | `400` |
| `capacity_unit` | 产能单位 | 源表 | str/null | `米/天` |
| `compatible_products` | 可对应产品 | 源表 | list[str] | `["N446","RN446"]` |
| `aliases` | 该设备别名（可归一形态） | 规则 | list[str] | `["#301"]` |
| `id_source` | 主键/编号来源 | 规则 | str | `来源表(②织机状态)` |
| `data_quality` | 数据质量标记 | 规则 | str | `ok` |

> 说明：整经机因源表无编号，**主档为空**，不出现在本文件；整经机编号缺口在报告中标注。

## 2. `equipment_alias_mapping.json` —— 别名映射表

每条记录字段：

| 字段 | 业务含义 | 类型 | 示例 |
|---|---|---|---|
| `process_type` | 所属流程 | str | `织造` |
| `equipment_type` | 设备类别 | str | `织机` |
| `source_sheet` | 该编号出现于哪张表 | str | `②织机状态` |
| `source_code` | 源表原始编号 | str | `#301` |
| `normalized_code` | 规范编号（去 #/中文/数字） | str | `301` |
| `equipment_id` | 映射到的系统主键 | str | `LOOM-301` |
| `match_method` | 匹配方式 | str | `direct` / `text_numeric_unify` / `chinese_name_unify` / `rule_generated` / `manual_confirm` |
| `confidence` | 匹配置信度 | float | `1.0` |
| `conflict_note` | 冲突说明（无则空） | str | 可空 |

> `manual_confirm`：任务引用但主档缺失、暂不能确定同一设备的条目，置信度记为 `0.0`。

## 3. `task_equipment_mapping.json` —— 任务→设备 关联

每条记录字段：

| 字段 | 业务含义 | 类型 | 示例 |
|---|---|---|---|
| `task_id` | 任务标识 | str | `WARP-5` / `WEAVE-7` / `WASH-7` |
| `process_type` | 流程 | str | `整经` |
| `equipment_type` | 设备类别 | str | `整经机` |
| `source_sheet` | 引用来源表 | str | `整经计划` |
| `source_cell` | 来源单元格 | str | `B5` |
| `source_value` | 来源单元格原始值 | any | `#301` |
| `source_code` | 引用编号（清洗后） | str | `#301` |
| `target_loom_id` | 目标织机主键（关联线索） | str | `LOOM-301` |
| `target_loom_code` | 目标织机现场编号 | str | `#301` |
| `product_id` | 产品款号 | str | `N73413N` |
| `beam_code` | 经轴品番 | str | `WN446` |
| `batch_code` | 批号（水洗） | str | `PH888888` |
| `set_length` | 整经设定数量/产能设定 | float | `400` |
| `plan_length` / `input_length` | 计划长度 / 投入长度（水洗） | float | `1000` / `990` |
| `plan_start` / `plan_end` | 计划起止（日期或时间） | str | `2026-04-03` / `09:05:00` |
| `plan_quantity` | 计划累计量 | float | `3600` |
| `status` | 任务状态 | str | `已匹配` / `待确认/无整经机号` |
| `content` | 行内容（轴个数/上轴等） | str | `轴个数` |
| `equipment_id` | 关联到的设备主键 | str | 可空 |
| `assignment_status` | 关联状态 | str | `已匹配` / `待确认` |
| `reason` | 待确认原因（已匹配则空） | str | 可空 |
| `confidence` | 关联置信度 | float | `1.0` / `0.0` |

> 当设备无法确定时：`equipment_id=""`、`assignment_status="待确认"`，`reason` 给出来源与原因。
> 整经任务全部为 `待确认`（源表无整经机编号），并记录其目标织机 `LOOM-###` 作为人工确认线索。
> 各流程主要业务字段：整经=产品/经轴品番/设定长度/计划日期/状态；织造=产品/经轴/起止/数量/状态；
> 水洗=批号/计划长度/投入/起止/状态。

## 4. `equipment_alignment_report.json` —— 数据对齐报告

| 字段 | 业务含义 |
|---|---|
| `report_title` | 报告标题 |
| `data_source` | 源文件名 |
| `generated_by` | 生成模块 |
| `equipment_type_summary` | 各设备类别主档数 + 未在任务中使用数 |
| `per_process` | 各流程：原始编号/清洗后设备/别名合并/缺失/重复/状态冲突/未匹配任务 |
| `totals` | 以上各项合计 |
| `reconciliation` | 对账校验：内部编号唯一/同工序规范化编号唯一/任务引用设备必须存在/不可用设备不得标记正常/设备工序与任务一致/状态冲突发现/产能单位不一致不合并/来源可追溯/原始清洗数量对账 |
| `status_conflicts` | 状态冲突明细（②织机状态 vs 织造计划） |
| `duplicate_refs` | 重复/别名冲突明细 |
| `manual_confirm_items` | 人工确认项明细 |
| `conclusion` | 对齐结论 |

`per_process` 字段口径：

| 字段 | 口径 |
|---|---|
| `raw_identifier_count` | 该流程在所有任务/引用中出现的不同源编号数 |
| `cleaned_equipment_count` | 归一后确认为真实设备的数量（主档数） |
| `merged_alias_count` | 别名合并数 = 已匹配的不同源值数 − 被引用设备数 |
| `missing_code_count` | 主档缺失数（整经机为 0，因主档为空是「无来源」而非「缺失引用」） |
| `duplicate_code_count` | 同一设备被多个不同形态源编号引用的次数 |
| `status_conflict_count` | 同一设备在两表中状态不一致的次数 |
| `unmatched_task_count` | 无法确定设备、标记待确认的任务数 |
