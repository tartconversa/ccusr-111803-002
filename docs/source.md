# 旅行服务来源约定

目录和详情分别位于 /catalog 与 /detail，对应浏览器页面以 .html 结尾。详情使用目录中的稳定标识，不用显示名称做业务键。edition 为 1 或 2，表示两个发布期；出发批次、版本和行程条款是本地演练资料中的业务语义。来源只监听环回地址，没有真实人员、订单或账号。

## 业务键与页面字段

- 线路业务键为 `id`（source_id）；出发批次业务键为 `batch_id`，显示名称（`name`/`batch_label`）只用于展示，不能作为覆盖键。
- 目录行携带 `edition`、`batch_id`、`bookable`；详情行携带 `requested_edition`、实际服务的 `served_revision`（同时回填到 `revision`）、`batch_id`、`meeting_point`、`terms`、`bookable`。
- 浏览器页面对应暴露 `data-edition`、`data-revision`、`data-batch`、`data-bookable` 属性，供真实浏览器核对。

## 两个故障演练开关

详情接口（JSON 与 .html 同义）支持：

- `stale=1`：模拟页面跳转落到上一批次的缓存。第二发布期的详情返回第一发布期内容，`served_revision` 如实标注为 1；目录页在该开关下生成的详情链接也会带上 `stale=1`。
- `max_detail_edition=1`：模拟详情更新晚于目录。请求 edition=2 时详情仍给出第一发布期，`requested_edition=2` 而 `served_revision=1`。

采集端只能依据返回的标识对账，无法证明同批次一致时必须保留不完整观察，不得写成已核实可约。
