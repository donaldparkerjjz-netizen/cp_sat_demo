# 整经织造排工排产可视化 Demo · 阶段2 算法与交付说明

> 阶段1(数据/领域模型)之上，新增阶段2：**CP-SAT 排程核心**。含阶段1数据质量补丁。

---

## 一、阶段1 数据质量补丁

`validate.py` 引入三级严重度：`ERROR / WARNING / INFO`，报告结构变为
`{ok, errors, warnings, info, items, stats, severity}`。`ok = (ERROR 数为 0)`；
WARNING/INFO 不影响 `ok`，因此**不再显示“完全无警告”**。

`run_stage1` 实机输出：`状态 = 可运行 OK (ERROR=0, WARNING=10, INFO=1)`。

### 阶段1 新增的 10 项数据缺口警告
| # | code | 警告 |
|---|---|---|
| 1 | due_from_forecast | 交期由客户月度预测推导，不是真实订单交期 |
| 2 | uniform_weave_efficiency | 19个产品织造效率为临时统一产能 400 米/天 |
| 3 | beam_master_only | 经轴仅有品番级主档，无实体经轴编号与真实剩余长度 |
| 4 | missing_compat | 产品或织机缺少明确适配关系；空适配不得解释为所有织机均可生产 |
| 5 | incomplete_tooling | 钢筘、废边盘、切边等工装需求不完整 |
| 6 | external_ref_unresolved | 源表存在外部工作簿引用/公式，无法解析 |
| 7 | time_inconsistent | 织机状态、计划日期与库存数据更新时间不一致 |
| 8 | temp_setup_params | 上轴330/穿综穿筘480/落布10分钟属临时参数 |
| 9 | derived_task_attrs | 织造任务交期、数量或优先级来自推导值 |
| 10 | unconfirmed_arrival | 物料到货日期未确认，未确认到货不计入可用库存 |
| INFO | tooling_stock_not_built | 仓库工装库存未建档，阶段2仅校验机台已安装配置 |

（另保留 ERROR：重复主键、物料负库存、锁定信息不完整、引用不存在产品/织机。）

---

## 二、阶段2 业务规则实现

### 1. 产品-织机适配（`compat.py`）
- 优先采用**产品明确指定的可用织机清单**（`Product.allowed_loom_ids`），其次织机声明的
  `可对应产品`；命中即兼容。
- 无明确清单 → 按已记录能力匹配：钢筘规格已知时要求**完全匹配**；钢筘规格缺失产生数据警告；
  门幅超过全幅边撑判不兼容；显式工装要求(废边盘/切边/纱架/大卷装/水过滤/齿轮铝轮/综丝)需具备。
- **禁止**把“适配信息为空”解释成“所有织机都可以生产”：织机无任何能力信息 → 不可确认兼容。

### 2. 织机独占：一台织机同一时间一个织造任务（`AddNoOverlap`）。双幅/并轴暂不纳入。

### 3. 经轴独占（虚拟实体）
- 数据只有品番级经轴 → 生成虚拟实体 `WB-<品番>-001`，带：经轴品番、总长度、剩余长度、
  最早可用时间、当前状态、当前所在机台、`is_derived=true`。
- 同一实体经轴同一时间不能分配给两台织机（按品番 NoOverlap）。

### 4. 上轴与准备时间（分钟，临时参数）
`drop_prep=10`、普通上轴 `mount=330`、穿综穿筘 `threading=480`。
同产品同工艺同钢筘不需重穿综 → 只计落布+上轴；产品或工艺变化 → 增加 480 分钟。

### 5. 物料规则
- 全局物料硬约束：每纱线 已排数量×单耗 ≤ 可用库存(仅“库存”行，已确认口径) − 安全库存(0)。
- 未确认到货(到货kg/到货托)不计入可用库存；只能产生风险提示。
- 物料不足 → 允许保留**未排数量**，返回部分可行方案，而非整个模型 INFEASIBLE。

### 6. 锁定规则
锁定条件：已开工 / 已上轴 / 人工锁定 / 进入冻结期（冻结期 = 排程开始后 3 天，配置化）。
锁定任务记录 `locked_machine_id/locked_start/locked_end/locked_quantity/lock_reason`；
信息不完整 → 数据 ERROR。锁定任务强制占用锁定的机台与时间窗口。

### 7. 工装范围
支持：废边盘(类型)、废边盘安装孔位、切边装置、钢筘、全幅边撑、齿轮或铝轮、综丝、纱架、
大卷装、水过滤。区分“机台已安装 / 仓库可调配 / 产品要求”；仓库工装库存未建档 → 产生
“工装库存未建档”提醒，阶段2仅校验机台已安装配置。

---

## 三、8 层字典序优化目标（`solver.py`）

> 阶段2.5 由 7 层校准为 **8 层**，并新增“启用机台成本”(不得高于交期目标)。

`STAGE2_PARAMS["objective_layers"]` 顺序即优先级，逐层最小化；每层求解后**固定该层最优值
(±容差)**再求下一层，并**分别输出每层目标值**：

1. unscheduled_quantity（未排数量）
2. weighted_tardiness（加权交期延误，带优先级）
3. max_tardiness（最大交期延误）
4. task_split_count（任务拆分份数）
5. machine_spread_count（启用机台数量 + 任务分散）
6. changeover_count（换款/换轴/穿综穿筘）
7. plan_change_count（相对原计划的变动）
8. utilization（在结果不变时提高机台利用率）

未采用“一个随意加权的总目标”。`model_minimize` 每次切换为当前层目标；前一层以
`prev <= best + tol` 固定。时间预算按层均分（`per_layer_time = max_time / num_layers`）。
为防止“换款目标导致任务分散到大量机台以规避换款”的副作用，`machine_spread_count` 在交期层之后生效。

---

## 四、CP-SAT 建模（真实 Google OR-Tools）

- **变量**：每 (任务, 拆分份数, 兼容织机) 一个 `loom_sel` 布尔、`qty`(已排数量)、
  `start/end/dur`(分钟)、可选区间 `NewOptionalIntervalVar`；每(任务,份)聚合
  `scheduled/unscheduled` 数量、`lateness`；每层目标 IntVar。
- **时长**：`dur = qty * minutes_per_meter + setup(织机)`（整数分钟）。
- **独占**：每织机 `AddNoOverlap`（含维修/锁定固定区间 `NewFixedSizeIntervalVar`）；
  每经轴品番 `AddNoOverlap`。
- **经轴到位**：`start >= beam.earliest_available_minute`。
- **物料**：全局线性约束 `∑ qty×单耗 ≤ 可用库存`。
- **任务**：不允许拆分(no-split)只能选一台织机；允许拆分设置最小批量/最大份数，
  各份合计 = 已排，需求 = 已排 + 未排；未排数量允许>0。

---

## 五、solve 接口（`solver.py`）

```
solve(scenario, objective="lexicographic", max_time_s=30.0, config=None) -> {
  status, solver_status, solve_time_s, schedule_start, schedule_end,
  model_stats: {num_variables, num_constraints, num_boolean, solver, num_workers,
                time_limit_s, per_layer_time_s, num_layers},
  assignments: [ {task_id, part_index, loom_id, product_id, beam_id, start, end,
                  start_minute, end_minute, scheduled_quantity, locked, lock_reason,
                  changeover_type, lateness_minutes} ],
  unscheduled: [ {task_id, required_quantity, scheduled_quantity, unscheduled_quantity,
                  reason_codes} ],
  objective_levels: [ {level, name, best_value, status, solve_time_s} ],
  kpi: {required_quantity, scheduled_quantity, unscheduled_quantity, on_time_quantity,
        late_quantity, total_lateness_minutes, max_lateness_minutes, changeover_count,
        beam_change_count, threading_count, plan_change_count, utilization},
  issues: [ {severity, code, task_id, loom_id, message} ],
  validation: {ok, checks:[{check, pass, message}]}
}
```
所有时间输出均为 **ISO 8601**，同时保留**内部分钟偏移** `start_minute/end_minute`。

---

## 六、运行方式

```powershell
cd D:\dsh\cp_sat_demo
# 阶段1：生成样例数据 + 数据级校验(含 10 项警告)
python -m weaving_demo.run_stage1
# 阶段2：CP-SAT 排程演示(结果写入 sample_data/solve_result.json)
python -m weaving_demo.run_stage2 --max-time 15
# 全部单元测试(41 项)
python -m pytest weaving_demo/tests -q
```

---

## 七、实机验证结果

### 阶段2 演示（真实益丰场景，19 任务 / 108 织机）
- 求解状态：**OPTIMAL**，求解耗时 10.46s；模型规模 **num_variables=10105,
  num_constraints=8298**，`num_workers=1`（保证可复现），`layers=7`，`per_layer_time=2.143s`。
- 每层目标值（字典序）：`unscheduled_quantity=100800, weighted_tardiness=295320000,
  max_tardiness=132120, product_change_count=0, beam_threading_count=7,
  plan_change_count=0, utilization=253280`。
- KPI：需求 164120 米，已排 63320，未排 100800，准时 25400，逾期 37920，
  总延误 294840 分钟，最大延误 132120 分钟，换款 0，换轴 7，利用率 0.0108。
- 结果校验：**全部通过**（无机台时间重叠 / 无经轴时间重叠 / 已排+未排=需求 对账）。
- 已排任务均落在具备全幅边撑/钢筘的兼容织机(#101/#102)；多数产品因源数据未配置
  全幅边撑/工装而无可兼容织机，被保留为“未排数量”（部分可行方案）。

> 说明：阶段2 演示如实反映数据缺口——源表仅部分织机配置了钢筘/全幅边撑/工装，故多数
> 产品兼容织机少，产生大量“未排数量”。这正是“允许未排数量的部分可行方案”设计。

---

## 八、当前使用的临时业务参数

`STAGE2_PARAMS`（`config.py`）：`setup_minutes{drop_prep:10, mount:330, threading:480}`、
`safety_stock:0`、`confirmed_arrival_only:true`、`allow_unscheduled_on_material_shortage:true`、
`freeze_days:3`、`lock_conditions[...]`、`split_default{min_batch:500, max_parts:3, enabled_default:false}`、
`virtual_beam_prefix:"WB"`、`objective_layers[...]`、`lexicographic_tolerances{...:0}`、
`random_seed:20260518`、`num_workers:1`、`default_due_minutes`(build_tasks 60 天)、
`capacity_params{efficiency_factor:1.0, loom_daily_hours:24}`。

## 九、仍因数据不足未启用的约束

1. **逐日物料库存推移**：仅做全局物料预算约束，未做“逐日库存不得<0”的逐日联动。
2. **机台×产品组合效率差异**：生产时长用产品标准效率(mpm)，未用机台-产品组合效率折减。
3. **仓库可调配工装数量**：`warehouse_stock_available` 为空，仅校验机台已安装配置。
4. **后整/水洗/涂层/验布/入库排程**：属阶段3+，本阶段未纳入。
5. **休息日硬禁止排产**：未在阶段2模型中以“禁排区间”硬约束化（可后续配置维护区间实现）。
6. **真实实体经轴**：用虚拟经轴 `WB-XX-001` 替代，无真实剩余长度/在机状态。
7. **原计划一致性**：`plan_change_count` 依赖 `original_loom_id`，阶段1数据无原计划时恒为 0。

## 十、单元测试（41 项全部通过）

- 阶段1：`test_config / test_model / test_validate / test_extract`（21 项）。
- 阶段2：`test_solver.py`（20 项）——单任务单织机、无兼容织机、同机争用、同经轴争用、
  经轴未到位、维修禁排、锁定位置不变、锁定冲突→错误、物料不足→部分可行、紧急任务降延误、
  不允许拆分用一台、允许拆分满足最小批量/最大份数、换款成本、同产品免换款、穿筘加准备时间、
  超时返FEASIBLE、可复现、无机台重叠、无经轴重叠、数量对账。

---

## 十一、阶段2.5：结果诊断、指标核对与模型校准

新增 `diagnose.py`、`compat.py` 扩展、`run_diagnostics.py`，solve 结果新增
`diagnostics` 与 `business_status`。

### 11.1 diagnostics 块
```
diagnostics: {
  demand_coverage_rate, available_loom_count, candidate_loom_count, used_loom_count,
  unused_loom_count, horizon_total_minutes, available_machine_minutes,
  scheduled_machine_minutes, utilization_formula, utilization,
  task_count, scheduled_task_count, fully_unscheduled_task_count,
  partially_unscheduled_task_count, unscheduled_reason_summary:[{reason_code,task_count,quantity}],
  task_diagnostics:[{task_id, product_id, required_quantity, scheduled_quantity,
    unscheduled_quantity, due_date, due_minute, all_loom_count, compatible_loom_count,
    rejected_by_product_rule, rejected_by_tooling_rule, rejected_by_calendar,
    rejected_by_lock, rejected_by_beam, rejected_by_material, rejected_by_horizon,
    candidate_loom_ids, main_rejection_reason, final_reason_codes}],
  compatibility_mode
}
```
未排原因使用标准编码：`NO_COMPATIBLE_LOOM / TOOLING_MISMATCH / NO_AVAILABLE_BEAM /
MATERIAL_SHORTAGE / OUTSIDE_HORIZON / LOCK_CONFLICT / MIN_BATCH_NOT_MET /
CAPACITY_SHORTAGE / INVALID_DUE_DATE / MISSING_MASTER_DATA`。

### 11.2 算法状态 vs 业务结果状态
`solver_status`（OPTIMAL/FEASIBLE/INFEASIBLE/UNKNOWN）与 `business_status` 互不混淆：
- READY：全部需求已排且无硬约束风险。
- PARTIAL：存在未排数量，但已排部分可执行。
- HIGH_RISK：使用大量临时参数/推导交期，或未排比例高(当前 38.6% 即 HIGH_RISK)。
- NOT_EXECUTABLE：锁定冲突、数据错误或已排结果违反硬约束。

### 11.3 KPI 校正口径
- demand_coverage_rate = scheduled_quantity / required_quantity
- on_time_rate = on_time_quantity / scheduled_quantity
- on_time_demand_rate = on_time_quantity / required_quantity
- utilization = scheduled_machine_minutes / available_machine_minutes
  （available_machine_minutes 已扣维修/停机/禁排/班次外）
- total_delay_minutes = Σ max(0, end - due)（若拆分，按任务最大完成时间）
- max_delay_minutes + max_delay_task_id（可定位到具体任务）
- 未排对账：required_quantity == scheduled_quantity + unscheduled_quantity
- 机器散布：used_loom_count / task_fragment_count / single_task_loom_count /
  average_tasks_per_used_loom / total_idle_gap_minutes

### 11.4 适配模式（`compatibility_mode`）
`strict`（缺关键适配数据禁止安排）/ `balanced`（明确冲突禁止，缺失试排+风险，真实演示用）/
`simulation`（仅演示，基础能力匹配）。工装字段 0/空白/NULL/未知语义区分，未知不自动判兼容或不兼容；
钢筘规格缺失作为 WARNING，是否禁排由模式决定。

### 11.5 A/B/C/D 对照（诊断）
A(全约束)/B(关物料)/C(关经轴)/D(都关)。实机结果：A 已排 80720、B 已排 96920（+16200）、
C 已排 80720（无变化）、D 已排 95720 → **物料是瓶颈之一，经轴不是**。
未排主因：NO_COMPATIBLE_LOOM（部分产品无可兼容织机）+ MATERIAL_SHORTAGE。
该对照仅用于诊断，不作为正式方案发布。

### 11.6 测试
阶段2.5 新增 `test_diagnose.py`（15 项业务合理性）。当前全量 **56 项**全部通过。

