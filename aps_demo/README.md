# 减振车间 APS 智能排产 Demo
参考《益丰生产管理表单》结构，用 CP-SAT 为**信力科技减振车间**建的智能排产原型。
## 文件
- aps_engine.py        数据定义 + CP-SAT 建模求解(硬/软约束)
- 减振车间排产数据.xlsx  参考益丰表单: 机台台账/产品-机台适配/工价表/换模矩阵/订单/排产结果(机台×班次)
- aps_schedule.json     排程结果
- aps_gantt.png         排产甘特图(图片)
- aps_gantt.html        交互式甘特图(机台×班次, 悬停查看订单, 换模三角标注)
## 模型
- 时间轴: 7天×2班(白/夜)=14 班次槽位
- 硬约束: 产品-机台适配 / 单日单班唯一 / 产能上限(片/12h) / 返工专线 / 换模预留(不同产品连班需空档)
- 软目标: 优先级(急单最高) / 工价均衡(各机台累计计件工资 max-min 最小化) / 换模最小化 / 利用率
## 运行
python aps_engine.py
python aps_visualize.py   (画 PNG)
python make_aps_gantt.py   (生成 HTML)
