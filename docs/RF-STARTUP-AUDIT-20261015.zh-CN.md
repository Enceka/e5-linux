# RF 分配断言：宿主启动逻辑复查

## 结论边界

朋友 E5 的日志证明 CP 在 Alive 后约 23 秒报告
`drm_rfresourcehandle.c:3925 / Drm allocate spr rf path fail! / res_type=16`。
它没有包含故障前完整的 AT 收发序列，因此不能把该次断言确定归因于下述任一问题，
也不能排除宿主命令或配置作为触发条件。先前报告中“这是 CP 固件自身的问题”的表述过强。

最初只读审查时设备 SSH 超时；随后恢复连接，已按用户要求修复并部署到 E5。
没有改 NV、成功路径的 AT 初始化顺序、回放位置或保存的工作模式。随后按用户指令恢复打包，修复已纳入 r5 三机型安装包。

## 已确认的逻辑缺口

### 工作模式查询失败后仍写入猜测值

`modemmanager-01-unisoc-plugin.patch` 的 `cards_on_testmode_ready()`
把两个工作模式初始化为 `134`，查询完成时未接收错误。
若 `SPTESTMODE?` 超时、报错或回包不能解析，就继续用 `134,134` 创建激活计划。
它不保持已经配置的 `152`、仅 LTE 或其他真实模式。

离线测试从现有 `sim-power.py` 的模型编译实际回调，注入查询失败，确认仍创建
`+SPACTCARD=0;+SPTESTMODEM=134,134` 和随后 `+SPACTCARD=0;+SFUN=4`。
测试辅助文件在本地 `work/rf-audit-20261015/reproduce-power-fallback.py`；未访问设备。

### 激活序列忽略关键命令错误

`CardsOnContext` 使用零初始化，创建各条命令时只设置 command/timeout，
没有设置 response_processor。ModemManager 1.24.0 的
`at_sequence_parse_response()` 在该回调为空时直接 CONTINUE，
即使当前命令已经返回错误。

因此，SIM 供电或 `SPTESTMODEM` 设置失败后，仍可能执行后续 `SPSWDATA`、`SFUN=4`，
而 `cards_on_sequence_ready()` 未必得到任何错误。
“跳过不存在的另一张卡的错误”的历史策略，在加入 SIM 缺席过滤后仍留在关键序列中。

上游实现：
https://github.com/linux-mobile-broadband/ModemManager/blob/1.24.0/src/mm-base-modem-at.c#L185-L211

### 查询与初始化失败没有完整向上传递

- `init_cfun_ready()` 不接收 `CFUN?` 错误，失败会被当作不需要冷激活。
- `power_up_cfun_ready()` 同样丢弃查询错误，失败会转而发送 `CFUN=1`。
- `init_sim_on_ready()` 即使 `cards_on_finish()` 失败，也只记警告并返回初始化成功。

这些路径会模糊“已成功初始化”和“无法确认或只完成一半”的区别。
§47.3 曾实测一侧协议栈已经注册时再激活另一侧会触发其他 CP 断言，
因此不能在部分成功后盲目重跑整套双卡激活。
这是风险链路，尚无证据证明该次 RF 资源断言就是这样触发。

## 已核对与尚未证明的事项

- 正常成功路径仍保留原先核对的 RIL 顺序；本次没有发现把模式命令移到协议栈启动之后的改动。
- 开机回放位于 ModemManager 进程启动前，后续 verify 不回放、不重启射频。
- 本次报告是单卡场景，不能仅用“双卡竞争”解释；也不能把 res_type=16 直接解释为具体天线、频段或 NV 校验错误。
- 历史 §47.2 相同 RF 断言与特定样机的频段/双卡组合有关，并曾在 Android 出现。
  这不构成给全部 E5 强制 152、限制 NR 频段或复制另一台 NV 的依据。
- 新增的 `e5-modemd` 仅缩短故障后的 dump 等待，不修复触发条件。

## 修复应保持的约束

工作模式查询失败应上报失败，不能猜测并写入；激活序列应检查已选中、
需要激活的槽位的关键命令；前置失败不得继续启动协议栈。
CFUN 查询失败和部分初始化失败应明确保留错误，不伪装成功或自动重跑部分序列。
成功路径的命令顺序、用户保存的双卡模式/锁频、回放位置保持不变。

## 已实施的修复

新增公共补丁 `rootfs/deb-patches/modemmanager-16-unisoc-power-guards.patch`，
E5、T551M、M8 的后续构建共用，不含机型判断或强制频段/模式：

- 模式查询错误、空值、缺字段、负数、超范围及无效数字均返回错误，不写猜测的 134/134。
- 对实际生成的每条激活命令设置 MM 原生 mandatory response processor，前置失败立即中止；
  已证明缺席的卡槽仍按原逻辑跳过，成功路径的命令顺序不变。
- 初始化和 power-up 的 CFUN 查询错误或非法回包明确返回错误，不当作已激活，也不猜测执行 CFUN=1。
- SIM 激活失败传递给初始化调用者；失败路径调用父类 initialization_stopped 释放已获得的端口上下文，
  清空 task data，避免错误路径泄漏。此时不运行派生类的成功/数据偏好钩子。
- 没有新增失败后的 SFUN/CFUN 重跑、轮询、NV 写入或配置回放。

`openwrt/tests/sim-power.py` 编译生产回调及 MM 自身的 mandatory response processor：
保留 8 种卡槽/首选组合测试，补入全部 8 个激活步骤逐个注入错误、
模式及 CFUN 无效/错误回包、部分初始化失败、端口清理和正常成功分支。
开机回放 9 项、AT 路由 3 项、网络启动 8 项回归通过。

正式 OpenWrt 构建完成，版本 `modemmanager-1.24.0-r930`，其构建验证还通过
通话身份与路由、IMS 回包、挂断节流、数据偏好、移动切站和短信隔离回归。
构建工具补入测试依赖 pkg-config，来源/产物指纹校验通过。

## E5 实机部署与结果

- 升级 ModemManager 及其 RPCD 两个本地 APK，禁用安装脚本，保留设备原启动胶水文件，随后正常重启一次。
- 重启前确认无通话。没有重刷内核或重启厂商服务作为额外恢复动作；正常重启按既有关闭流程执行。
- 实际已进入 `CFUN:0` 的冷激活路径，日志记录 SIM1=present、SIM2=present，SIM1 上网。
- 新二进制 SHA-256：`5eb4aab538f848ac1a65c8ae3cd143baf288ad1fe987c95961fd6765d9c03c1c`。
- 双卡模式仍为 `134,134,0,20,3,1`，没有改成 T551M 的 152。
- WAN 获得 IPv4，MM 为 connected / home，当前注册 LTE；外网 ICMP 3/3 应答，DNS 解析正常。
  这只证明本轮联网可用，不把三个包的结果视为延迟或长期稳定性验证。
- network、双卡配置、回放、锁定控制、AT 分发、vendor/NV helper 的 SHA-256 与部署前一致。
- 九个原始 NV 分区的启动来源指纹不变，块设备仍全部只读；没有备份或修改原始 NV 内容。
- 本轮启动未见 RF 断言或初始化错误。此前 RF 故障是偶发，当前是 LTE，仍需用户按原来的 5G/双卡场景及多次启动复测；
  不能据此宣布闭源 CP 的射频断言已经完全消除。

本地构建、部署前后与回滚信息位于忽略目录 `work/rf-fix-20261015/`；
设备仅保存代码/APK 回滚文件 `/root/e5-rf-power-guards.HnKJNd`。
后续已重打 E5、T551M、M8 的 r5 发行 ZIP，构建器强制使用经来源指纹校验的 r930 APK 刷新基础 rootfs，并核对最终二进制；没有沿用预构建基础中的旧 r929。
