# APN 切换与 IPv4-only 拨号修复

## 已确认的问题

依据两份用户报告及仓库代码，问题发生在两个独立环节。

1. APN 的 Python 入口和 ucode 配置库只接受 18–22 位数字 ICCID。
   基带提供带字母的标识时，保存配置可以成功，但应用、按卡绑定和拨号解析
   会报 `apn_identity`。不是 APN 名称、SIM 无效或网络拒绝。
2. ModemManager 选择已存在的 `CID 2 / IP` 配置后，需要 `sipa_eth1`，
   但端口发现、规则只登记首个数据网口。它在激活前报
   `No network interface for PDP context 2 (sipa_eth1)`。
   手动将网卡设为 up 无法补齐 ModemManager 的端口列表。
3. 原有 CID>1 选择还遗漏 SIM2 的网口偏移；网页速率、流量池和屏幕统计
   固定读取 CID1，在其他 CID 上联网后也会显示错误的速率/用量。

## 原厂对照

使用本地保存的 E5 原厂 `/vendor/lib64/libimpl-ril.so`：

```
SHA256 c0e86a5a6d7402a3d126e411fdb956deb8a6454763d55505c3ba64f839d0c14b
getEthIndexBySocketId 0x4c950
getEthNameByCid       0x4c990
getCidByEthIndex      0x4c970
```

反汇编确认 SIM1 以 `CID-1`、SIM2 以 `CID+7` 计算网口索引，
对应已有 SIPA 驱动的两个八口分组。不能将所有 CID 强行路由到首口，
也不能把 SIM1 的 CID9 当作 SIM2 的首口。这里的分组范围是主机数据口
的边界，不是宣称基带只支持八个 PDP 上下文。

## 实现

- ICCID 接受 18–22 位 ASCII 字母数字，原样保存和比较；保留大小写及尾部字母。
  不剥掉字母，不将不同标识合并为同一张卡，仍拒绝分隔符、控制字符及非字符串。
  用户另行反馈存在 G–Z 的标识，因此兼容完整 ASCII 字母，不将其解释为标准 BCD。
- 共享端口发现先报告 SIPC AT 口，再撤销另一 SIM 的网口，报告当前卡实际存在的
  全部数据口。启动和热插拔使用同一实现；早期仅有 net 口时仍不启动 MM 探测。
- 插件规则覆盖 `sipa_eth0..15`；OpenWrt / Debian 事件入口按当前卡过滤。
  删除事件不受当前卡/AT 存在性限制，保证旧端口能正常清理。
- bearer 读取已有 `sipc_wwan.card`，精确选择当前卡和 CID 的网口，不使用
  “任取可用数据口”的策略；错误或越界上下文不会借用另一 SIM 的接口。
- 保持原来的 `CGPCO → SPSWDATA → CGACT → CGDATA` 顺序，不新增 AT、
  不强制双栈、不修改初始 EPS、不增加 CFUN/SFUN 或后台轮询。
- 网页实时速率、按卡流量池、屏幕速率和本次流量统计覆盖对应卡的数据口分组。
  原有按卡套餐、历史累计和配置键保持兼容；迁移时不重复计入其他 CID 的旧计数。
  地址和 DNS 页面保留 netifd 实际的 CID 网口。
- 通用 netifd 启动补丁修正重复应用时的无卡分支识别，确保共享构建/更新可重复执行。
- 源码补丁进入 Debian/OpenWrt 公共 MM 补丁序列，OpenWrt 修订升至 r937；
  APK 更新同步完整的热插拔和启动发现逻辑，三款机型走同一套代码。

MU300 使用直接配置 CID 的另一套拨号实现，没有本次 MM 缺失端口路径；
它只同步实际存在的 ICCID 校验/解析缺陷，不引入 E5 的 MM 端口机制。

## 验证边界

已执行真实 ucode/UCI 配置测试、Python 入口和 MU300 AT 文本解析测试、
编译原 bearer 选择函数的 C 测试、模拟 sysfs 的端口发现/过滤测试，
以及真实 ubus/ucode 流量服务的双卡 CID2、旧记录迁移和重启测试。
覆盖 SIM1/SIM2、CID1..8、无端口、错误端口类型、无 AT、跨卡清理和非法标识。

2026-10-17 构建完成 `modemmanager-1.24.0-r937.apk`，并通过通话、短信、
SIM 电源/事件、移动重连及新增数据口选择的编译回归。实际解包确认新 bearer、
规则、网口发现 helper、热插拔 handler 和跨卡事件过滤均已进入 APK；
`tools/openwrt-package-state.py check 25.12.5` 通过。
两仓库真实 UCI/APN 测试分别通过 91 / 86 项检查；E5 Python 入口 17 项、
端口发现/过滤 10 项、屏幕 APN 2 项及 MU300 shell/APN 7 项测试通过。
真实流量服务另验证 CID2 的双卡计数、屏幕速率、旧累计迁移及失败回滚。

这些是离线回归，不代表已经完成用户卡片的 IPv4-only 实机拨号。
实机还需核验：字母 ICCID 应用/自动匹配；IPv4-only CID2 获取 IP 和访问外网；
SIM2 CID2；切回双栈后的 DNS、网速及按卡用量。无需为验证修改 NV。
