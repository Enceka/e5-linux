# MU300 短信转发移植（2026-10-10）

参考 `mu300-linux-clean-tf-7.2` 提交 `25f8d0c` 的转发页面、渠道实现和模板渲染器，
适配本仓库的双卡收件箱、短信发送接口与电源状态。入口仍为
**蜂窝 → 短信转发**（`/cgi-bin/luci/admin/modem/forward`）。MIT 许可随插件安装。

## 功能

- Webhook：JSON、表单或文本模板，GET/POST、自定义请求头、超时及推送预设；
  `{from}`、`{text}`、`{time}`、`{sim}`、`{device}`、`{kind}` 按格式转义。
- 钉钉机器人：可选 HMAC-SHA256 加签，并检查接口业务返回码。
- SMTP：465 TLS / 587 STARTTLS、授权码留空保留、可选设备信息。
- 本机短信：最多三个目标，使用原短信来源 SIM 发送；不切上网卡。
  保留 MU300 的单条 70 UCS-2 单元限制，超过时明确记录失败，避免截断内容。
- 共用或双卡独立渠道、号码/关键词黑名单、三语模板、设备备注。
- 电源通知：使用共用配置；充电状态变化或跨越 5/20/40/60/80/100% 时通知，
  首次观察只建立基线。迁移时默认不开启此项。
- 最近 30 次投递结果留在内存，限制显示高度并内部滚动；不记录短信内容、号码或目标地址。
  页面关闭后仍执行，失败不自动重发。

## 接入与配置迁移

收信、长短信组装、SIM 存储清理仍由 `e5-sms-receive` 完成。完整新短信事件经
`e5-sms forward ID` 进入一个 `sms-forward event ID` 投递入口。不存在 MU300 的
第二套收件箱或 AT 轮询。独立 procd 服务每 5 秒只观察电池状态。

`forward-native` 仅读取原有原子更新的收件箱；历史、未完成、已删除及发件记录
不能投递。发送前持久记录消息 ID，防止重复事件或重启重发；较旧 ID 的长短信
稍后才组装完成也能处理，不使用会漏过它的单调 ID 游标。变更启用状态、渠道或
路由模式会更新时间基线，不补发之前的短信。投递先记录尝试，因此发送过程中
异常断电可能丢失本次投递，不承诺 exactly-once 到达远端。

首次启动迁移 `/etc/config/e5-notify` 的共用、SIM1、SIM2 配置，包括未启用的
目标、模板、请求头和超时。新配置保存在 `/etc/unisoc-modem/forward/`，仅 root
可读；原 UCI 不删除，原值另保存在目录内用于回退。后续启动不会再次覆盖新配置。
新页面从迁移后的配置读写，旧 UCI 转发字段不再是活动编辑入口；短信声音、震动、
亮屏等通知配置继续使用原 UCI。

沿用 MU300 的公网 HTTPS 及证书校验策略，不跟随重定向；SMTP 同样验证 TLS。
旧配置若使用 HTTP、内网地址或不兼容模板，应先调整目标再使用新版，不能假定
所有旧目标都兼容。本次 T551M 已有的 HTTPS 模板通过实际渲染校验并保留启用状态。

构建加入 `msmtp`、`openssl-util`；根文件系统与界面更新包同时包含新消息分派，
清理脚本保留新服务，升级保留配置目录。只更新 LuCI 包时也需要匹配的 `e5-sms`
平台分派，否则迁移拒绝激活；不会静默保留两套自动转发入口。

## 验证与部署

```sh
python3 device/openwrt_device_common/tests/test_forward_native.py
python device/openwrt_device_common/tests/test_forward_browser.py
# 在具有 jshn、ucode、openssl 的 OpenWrt 上，使用复制到临时目录的三个后端文件：
python3 device/openwrt_device_common/tests/test_forward_transport.py --tools /tmp/forward-test-tools
```

测试覆盖迁移幂等性、两个来源卡、去重、迟到分段、历史基线、黑名单、模板转义、
钉钉签名、SMTP 内容、短信来源卡、单条长度限制、电源状态变化、记录上限及敏感
字段脱敏。投递程序均由隔离的模拟端替代，不向真实号码、邮箱或 Webhook 发测试。
浏览器检查保存与配置切换、未保存内容不被刷新覆盖、未保存禁止测试、中英土三语、
390/1280 px 布局及记录滚动。

已部署到 T551M，核对三个迁移配置、原 Webhook 启用状态、启动服务、真实 LuCI
读配置及原模板渲染。没有通过真实收件方验证投递到达；需要后续实际新短信验证。
本次不重启整机，不修改上网卡、CPU 配置、驱动或 NV。

### E5 实机同步（2026-10-10）

E5 已应用 `e3d21c0` 的同版前后端及原生短信事件接入，安装 `msmtp`、
`openssl-util` 依赖并启用开机服务。迁移使用 E5 自己的配置：共用、SIM1、SIM2
均未配置目标且处于关闭状态，更新后保持原样；电源通知也保持关闭。

实机隔离测试覆盖 Webhook、钉钉加签、SMTP、来源卡短信、去重、分段及电源事件，
所有投递均使用模拟端。真实 LuCI 页面通过三个配置读取、390/1280 px 布局及
无 JavaScript 异常检查。服务运行及开机链接正常，原通知 UCI、CPU 配置未变，
九个原始 NV 分区只读校验通过，蜂窝网络、热点和屏幕运行正常。
未重启整机；未发送真实转发测试，实际到达需配置目标后用新短信验证。

### T551M 加签依赖补装（2026-10-12）

T551M 上钉钉加签渠道全部记录 `delivery_failed`，历史 `http_code` 恒为 0。根因：
2026-10-10 部署只拷贝后端与界面文件，未安装依赖包，设备上没有 `openssl`
命令。签名管道 `openssl dgst -sha256 -hmac … -binary | openssl base64 -A`
的 `2>/dev/null` 把“命令不存在”静默成空输出，`[ -n "$_sig" ]` 判空后直接
返回失败，curl 从未执行；`record_delivery` 对非 `[1-5]xx` 一律记 0，即页面
看到的占位值。与蜂窝网络、SIM 或 TLS 无关：curl 自带 TLS 后端，实测
webhook 直连 200；页面的“无服务”读数来自空置卡槽。

修复：设备执行 `apk update && apk add openssl-util msmtp`。`msmtp` 同在
10-10 部署中遗漏，SMTP 渠道会因缺少命令直接失败；已安装时为空操作。投递
在每次调用时重新解析命令路径，安装后即生效，无需重启；
`/etc/init.d/unisoc-sms-forward restart` 可选。加签不能省略，也无法用忽略
证书替代：机器人密钥模式必须携带有效 `timestamp`+`sign`，此处 openssl 用于
HMAC 计算，与 TLS 证书无关；TLS 校验保持开启。E5/M8 根文件系统自
e3d21c0f 起包含两包；TF 组装（`openwrt/build-profile-tf.py`）现于构建时安装
两包，校验 apk 数据库并在 `BUILD.json` 记录版本。
