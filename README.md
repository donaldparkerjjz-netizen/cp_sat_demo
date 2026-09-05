# CP-SAT 排工排产（生产排程）可视化 Demo

这是一个用 **Google OR-Tools CP-SAT 约束求解器**实现的生产排程（排工排产）
可视化演示：把「多工单、多工序、多机台」的排程问题建模为约束规划模型，求出
（近）最优排程，并用交互式 **甘特图** 展示。

---

## 功能特性

- **CP-SAT 建模**：区间变量 + 工序间先序约束 + 每台机器的独占约束（AddNoOverlap）。
- **多种优化目标**：
  - makespan    最小化总完工时间
  - completion  最小化所有工单完工时间之和
  - tardiness   最小化总拖期（相对交期）
  - weighted    最小化加权完工时间
- **两种工艺类型**：
  - job    Job-Shop：每个工单走一条随机的机器工艺路线
  - flow   Flow-Shop：所有工单按统一机器顺序加工
- **交互式甘特图**：
  - 按机器 / 按工单两种视图
  - 滚轮缩放、拖拽平移、悬停查看工序详情
  - 每台机器利用率显示、工单图例、KPI 汇总
- **两种运行方式**：
  - 在线演示（FastAPI 后端，可实时改参数重新求解）
  - 静态演示（自包含 HTML，双击即可查看）

---

## 目录结构

    cp_sat_demo/
    ├── scheduler.py        # CP-SAT 建模求解器（命令行工具）
    ├── app.py              # FastAPI 在线演示后端（/api/solve）
    ├── build_static.py     # 生成自包含静态页 demo.html
    ├── schedule.json       # 求解输出示例
    ├── demo.html           # 自包含静态演示页（可直接打开）
    ├── static/
    │   └── index.html      # 前端页面（甘特图，内联 CSS/JS）
    └── libs/               # 已解压的 ortools 依赖（无 pip 环境亦可运行）

---

## 环境依赖

- Python 3.12（本项目打包时使用的解释器位于
  C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe）
- ortools（Google OR-Tools）：已预先解压到 libs/ 目录，
  scheduler.py / app.py 会自动把 libs/ 加入 sys.path，因此无需 pip 安装。
- fastapi + uvicorn（在线演示需要，通常已随 Python 环境安装）

---

## 快速开始

### 方式一：在线演示（推荐，可交互调参）

    python app.py

然后浏览器打开：http://127.0.0.1:8000

在页面上调整「工单数 / 机器数 / 工艺类型 / 优化目标 / 随机种子 / 求解上限」，
点击「求解」，即可实时得到新的排程甘特图。

### 方式二：静态演示（自包含，无需后端）

    python build_static.py --jobs 7 --machines 6 --seed 7

生成 demo.html，双击用任意浏览器打开即可查看。

### 方式三：命令行求解

    python scheduler.py --jobs 6 --machines 5 --objective makespan --seed 42
    python scheduler.py --jobs 8 --machines 6 --objective tardiness --type flow --seed 3

输出的 JSON 写入 schedule.json，控制台还会打印一个文本甘特图预览。

---

## CP-SAT 建模说明

问题定义：共 N 个工单（Job），每单由若干工序（Operation）按固定工艺顺序组成；
每道工序需要在指定的机器上加工一段固定时长。

模型要素：

1. 变量：每道工序一个「区间变量」(start, duration, end)，end = start + duration。
2. 先序约束：同一工单内，后一道工序的 start >= 前一道工序的 end。
3. 机器独占：对每台机器收集其上所有工序的区间，加入 AddNoOverlap(...)，
   保证同一机器同一时刻只加工一道工序。
4. 目标：根据所选对象最小化（如最小化总完工 makespan）。

    # 关键片段（scheduler.py）
    interval = model.NewIntervalVar(start, duration, end, name)
    model.Add(starts[(job, idx)] >= ends[(job, idx - 1)])   # 先序
    model.AddNoOverlap(machine_intervals[m])                # 独占

CP-SAT 在设定的时间上限内返回最优解（OPTIMAL）或可行解（FEASIBLE）。

---

## HTTP API

| 方法 | 路径         | 说明                     |
|------|--------------|--------------------------|
| GET  | /            | 返回前端页面             |
| GET  | /api/solve   | 求解并返回排程 JSON      |

/api/solve 查询参数：jobs（工单数）、machines（机器数）、type（job/flow）、
objective（makespan/completion/tardiness/weighted）、seed（随机种子）、
max_time（求解上限秒数）。

    curl "http://127.0.0.1:8000/api/solve?jobs=6&machines=5&objective=makespan&seed=42"

---

## 说明 / 注意

- 控制台里中文可能出现乱码（GBK 控制台 vs UTF-8 源码），这是终端显示问题，
  生成的 JSON / HTML 均为 UTF-8 编码，浏览器打开正常。
- 求解耗时随实例规模增大而增长；max_time 用于限制求解时间，超时返回当前最优可行解。
- 本演示聚焦「调度建模 + 可视化」，未涉及上游 BOM / 物料约束等更复杂的排产场景。
