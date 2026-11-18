# 旅游线路资料

这里提供旅行服务资料的本地演练来源与采集流程。目录有稳定标识，详情随发布期改变；合成资料位于 fixtures/source.json。app.capture 读取来源并编排观察，app.domain 解释业务身份并做批次级对账，app.records 保存来源版本收据、观察结论与批次生命周期。收据只表明资料已被读取；只有目录与详情在同一线路、同一出发批次、同一发布版本且可约状态一致时，观察才是 verified，否则一律保留为 incomplete 并注明原因。

## 一轮观察关联什么

一轮 observe_run 把四类信息关联到同一条观察上：

- 线路（source_id，稳定标识，不按显示名称覆盖）；
- 出发批次（batch_id，改期可能换新批次，也可能同批次只改条款）；
- 行程条件（集合地点、退改/行程条款，来自详情）；
- 可约状态（目录与详情各自的 bookable，必须一致）。

每处来源都留有版本收据（source_receipts）：URL、请求版本 requested_edition、实际服务修订 served_revision 与原始载荷。页面落到上一批次缓存（stale=1）或详情更新晚于目录（max_detail_edition）时，对账结论为 incomplete，原因分别记为 batch_mismatch 或 detail_revision_lag，bookable 留空，绝不写成已核实可约。

## 中断、续采与客服视图

- 观察按“目录 → 逐线路详情 → 对账 → 批次退役”分步推进，每步立即落库（runs/run_steps）。中途退出后用同一 run_id 再跑一次即可续采：已 verified 的线路跳过详情重读，incomplete 的线路重新采集对账。
- `python -m app.cli --progress RUN_ID`：查看某轮目前确认到哪一步、每条线路的观察结论与全部来源收据。
- `python -m app.cli --batches`：查看每个批次的当前状态；active=0 的旧批次带 retired_reason（如 superseded_by_new_batch），说明旧批次为何不再可用，旧收据仍可追溯。
- 运行期数据库默认落在 data/records.sqlite3。

## 本地命令

- python -m unittest discover -s tests -v：运行本地来源与浏览器测试。
- python -m compileall -q app tests：检查项目代码。
- python -m app.site：在 8765 端口启动演练来源。
- python -m app.cli：另一个终端读取演练来源并运行观察；可用 --edition 2、--stale、--max-detail-edition 1 演练故障场景。

浏览器页面位于 /catalog.html，使用前准备 requirements.txt 中的 Playwright 与 Chromium。
