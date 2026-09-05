# 整经织造排工排产可视化 Demo · 阶段1 交付说明

> 项目：`D:\dsh\cp_sat_demo`（新增独立模块 `weaving_demo/`，复用已有 `libs/` 的
> ortools/openpyxl，不覆盖既有通用车间排程代码）。

## 一、本阶段范围（按你确认的方案1）

不实现 CP-SAT 排程、不做复杂排程页。只做：

1. 从 Excel《副本【作成中整经织造】益丰生产管理表单260604.xlsx》提取整经织造相关数据；
2. 字段清洗与映射（去掉 `#N/A`、`#REF!`、空值、`NULL`、日期串行列等）；
3. 建立领域数据模型：产品、订单/交期、织机、机台能力、经轴、整经任务、物料、工装、交期；
4. 把关键业务规则做成独立、可配置参数；
5. 产出结构化样例数据、数据校验、基础单元测试、字段说明文档。

## 二、目录与文件

```
weaving_demo/
├── __init__.py
├── config.py            # (新) 可配置业务规则参数(硬约束/软目标/时间/产能/交期/物料)
├── model.py             # (新) 领域数据模型(dataclass, 可按 JSON 序列化)
├── extract.py           # (新) Excel 提取 + 字段清洗映射 -> WeavingScenario
├── load.py              # (新) JSON <-> 领域模型 装载(往返)
├── validate.py          # (新) 数据级/静态校验(完整性/物料非负/产品-织机适配)
├── run_stage1.py        # (新) 阶段1 数据管道入口: 提取->JSON->校验->报告
├── sample_data/
│   └── scenario.json    # (新) 结构化样例数据(自动生成)
├── tests/
│   ├── conftest.py
│   ├── test_config.py   # 业务规则参数
│   ├── test_model.py    # 领域模型往返
│   ├── test_validate.py # 校验/产品-织机适配
│   └── test_extract.py  # 真实 Excel 提取集成(文件不存在自动跳过)
├── FIELD_DOC.md         # 字段说明文档
└── STAGE1_README.md     # 本文件
```

## 三、运行方式

> 环境：Python 3.12（`C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe`），
> 依赖 ortools/openpyxl 已在 `cp_sat_demo/libs/`。

### 1) 生成样例数据 + 校验（命令行）

```powershell
cd D:\dsh\cp_sat_demo
python -m weaving_demo.run_stage1
# 或指定 Excel / 输出路径
python -m weaving_demo.run_stage1 "C:\...\副本【作成中整经织造】益丰生产管理表单260604.xlsx" -o weaving_demo/sample_data/scenario.json
```

输出：样例 `weaving_demo/sample_data/scenario.json`，并在控制台打印数据级校验报告。

### 2) 运行单元测试

```powershell
cd D:\dsh\cp_sat_demo
python -m pytest weaving_demo/tests -q
# 预期: 21 passed
```

### 3) 单独提取

```powershell
python -m weaving_demo.extract <excel路径> -o weaving_demo/sample_data/scenario.json
```

## 四、验证结果（本机实测）

- 提取成功：产品 **19**、织机 **108**（可用 **106**）、工艺条件 **17**、经轴 **19**、
  整经任务 **60**、织造任务 **180**、落布预测 **60**、物料 **41**、交期 **4**。
- `run_stage1` 校验报告：**状态=通过 OK**，错误/警告均为空。
- 单元测试：**21 passed**（含真实 Excel 提取集成、JSON 往返、业务规则、产品-织机适配、
  物料非负、重复编码检测）。
- 样例 JSON 已生成（约 1.4 MB，含各任务按日矩阵）。

> 说明：控制台中文在 GBK 终端下可能显示乱码，属终端显示问题；生成/读取的文件均为 UTF-8，
> 浏览器/编辑器打开正常。

### 阶段1补丁（数据质量警告）
`validate.py` 已引入三级严重度 `ERROR/WARNING/INFO`，`ok = (ERROR 数=0)`，
因此**不再显示“完全无警告”**。本机实机输出：`状态=可运行 OK (ERROR=0, WARNING=10, INFO=1)`。
10 项 WARNING 为：交期来自月度预测、织造效率统一400、经轴仅品番级、缺少明确适配关系、
工装需求不完整、外部工作簿引用无法解析、时间口径不一致、上轴/穿综穿筘为临时参数、
任务交期数量优先级来自推导、未确认到货不计入可用库存；INFO 为“仓库工装库存未建档”。
详见 `validate.py` 与 `STAGE2_README.md`。

## 五、数据缺口（需你确认/后续补充）

1. **逐单订单与交期缺失**：Excel 没有“订单明细/逐单交期”，只有“客户月度预测”（摘要）。
   阶段1暂按 `客户月度预测 → 每月末交期` 推导（见 `config.due_date_params`）。
2. **工艺汇总背番号（织造参数）未深度解析**：`钢筘型号/整经根数/挂纱/经密/纬密/织布张力`
   等在该较复杂的多子表页；`①基础资料` 只含部分。当前 `Product.钢筘型号` 等依赖此页，列为
   阶段1缺口（可用于产品-机台“钢筘匹配”）。
3. **整经预测辅助表未解析**：该页含“经轴品番、设定米数、整经根数、钢筘、使用纱线、单耗”
   的更细经轴数据；阶段1经轴主档由 `①基础资料` 的经轴款号生成，未取该页。
4. **经轴实体与“轴库存”维度**：经轴当前是“品番级”主档，尚未细化到“同一品番多只实体/在某
   织机上的状态”；“经轴库存推移”行未单独建模（`整经计划`中“经轴库存推移”行被过滤掉）。
5. **后整产能口径**：`后整计划`给出水洗/涂层/验布“默认24小时产能”（如 12000/12 小时、
   9000/12 小时、7000/12 小时），但未能与`①基础资料`的水洗/涂层/验布速度完全对齐；
   后整为阶段3+内容，阶段1仅作字段记录。
6. **落布/上轴口径**：落布预测的“上轴”与整经计划“上轴”关系、以及具体“经轴实体”绑定，
   需要你确认口径（当前按“数值”抽取）。

## 六、待确认规则

| # | 规则 | 现状（阶段1默认） | 需你确认 |
|---|---|---|---|
| 1 | 产品-织机适配 | 按“可对应产品清单 + 工装(钢筘/全幅边撑/废边盘/切边/纱架/大卷装/水过滤)” | 是否用“可对应产品”清单为准，还是用工装匹配？钢筘型号是否必须同号？ |
| 2 | 织机独占 | 一台织机同一时间一个任务（`loom_exclusive`） | 是否允许并轴/双幅等特殊情况？ |
| 3 | 经轴独占 | 一根经轴同一时间只能上一台织机（`beam_exclusive`） | 是否需要“经轴实体级”独占（同品番多只）？ |
| 4 | 上轴先于织造 | 经轴完成并上轴后织造才开始（`beam_mounted_before_weave`） | 换轴/装轴准备时间（`beam_mount_lead_days`）取值？ |
| 5 | 物料非负 | 库存逐日不得为负（`no_negative_material`） | 是否允许“欠料投产”或“安全库存”天数？ |
| 6 | 锁定任务 | 已开工/已上轴/人工锁定不可移动（`locked_task_immobile`） | 锁定的判据（哪些字段）？ |
| 7 | 优化优先级 | 降交期延误 → 减换款/换轴 → 减计划变动（`OBJECTIVE_PRIORITY`） | 换款与换轴的相对惩罚（`CHANGEOVER_PENALTY`）是否认可？ |
| 8 | 工装条件 | 产品缺任一必需工装不可排 | 工装清单（tooling_names）是否完整？ |

## 七、下一阶段（阶段2）接口设计（待你确认后实现）

阶段2：CP-SAT 排程核心。预计对外接口（`weaving_demo/solver.py`）：

```
solve(scenario: WeavingScenario, objective: str = "default", max_time_s: float = 30.0) -> {
    "status": "OPTIMAL|FEASIBLE|INFEASIBLE|UNKNOWN",
    "objective_value": float,
    "assignments": [ {织机, 产品, 经轴, start, end, 数量, 锁定?, 优先?} ],
    "kpi": { 总拖期, 换款次数, 换轴次数, 计划变动, 平均交期满足率, 利用率 },
    "issues": [ {类型: 逾期/物料不足/工装不匹配/无可行机台, 说明} ],
}
```

阶段2需覆盖的硬约束（来自 `config.HARD_RULES`）：产品-机台适配、织机独占、经轴独占、
上轴先于织造、工装条件、物料非负、锁定任务；软目标按 `OBJECTIVE_PRIORITY` 加权。

---
阶段1 完成并测试通过。请确认后我进入阶段2。
