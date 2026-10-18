# 网页保存流量套餐误报服务不可用

## 原因与修复

2026-10-15 在 E5 实机确认 `unisoc.traffic` 正常运行。相同的无效配置经
`mu300dash.traffic_set` 转发，不含 `ubus_rpc_session` 时返回 `invalid_config`，
含网页会话字段时却返回 `traffic_unavailable`；直接内部调用报 `Invalid argument`。

rpcd 会给网页请求添加会话字段，用于公开 RPC 对象的权限检查。E5 公共实现
把整个请求原样传给内部 ubus 服务，导致内部调用失败。套餐内容、中文名称与
1000 GB 额度都不是这次错误的原因。

- 保存仅转发 `payload` 和已经校验的 SIM 卡槽。
- 清空仅转发显式 `slot` 和布尔 `confirm`，保留单卡／全部卡的原有范围语义。
- 不向内部服务转发会话和其他无关字段，不扩大网页 ACL。
- 解析错误返回 `invalid_config`；真正调用失败仍返回 `traffic_unavailable`。
- E5、T551M、M8 共用修复。连接的 E5 已热部署，未重启网络或改动现有套餐、流量。

MU300 当前实现已经过滤网页会话，不能把 E5 的缺陷算作 MU300 的复现。
该仓库补充同一真实调用链测试，并将保存参数的卡槽来源统一为已经校验的请求范围，
解析失败直接返回配置错误。

## 验证

`openwrt/tests/traffic-rpc.uc` 使用独立 `/tmp` 目录、假网卡计数和独立 ubus 对象。
在原生 OpenWrt 容器中，E5 与 MU300 分别通过 42 项检查；E5 实机同样通过 42 项。
覆盖用户给出的中文套餐请求、带会话的双卡独立保存、引号与小数、校验错误传递、
取消／确认清空、保留另一张卡和套餐。不会调用生产流量对象的清空方法。

在有 ucode、ubus、jsonfilter 的隔离 OpenWrt 环境中运行（ubusd 须已启动）：

```sh
TRAFFIC_TEST_LIB=/path/to/openwrt/luci-app-t551m/root/usr/libexec/unisoc-modem \
TRAFFIC_TEST_RPC=/path/to/openwrt/luci-app-t551m/root/usr/libexec/rpcd/mu300dash \
TRAFFIC_TEST_STRING_SLOTS=1 ucode /path/to/openwrt/tests/traffic-rpc.uc
```

MU300 使用 `tests/traffic_browser_rpc.uc`，路径改为 `luci-app-mu300`，省略
`TRAFFIC_TEST_STRING_SLOTS`；双卡测试需配置 `unisoc_modem.main.sim_slots=2`。
