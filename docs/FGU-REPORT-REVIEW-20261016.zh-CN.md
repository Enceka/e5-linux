# E5 电量停留与保存失败报告复核

## 范围与结论

复核来源：用户提供的 `charger-manager-fgu-bug-report.md`，其中引用朋友的
`6.18.54-e5-release20261016-g020b970e351e-dirty` 日志。
报告包含日志摘录，不等同于原始完整启动、放电和保存失败日志。

结论：90% 长时间不下降的直接机制可以由代码解释；容量保存失败需要继续定位。
不能据此认定是新增 SOC 恢复代码造成，也不能采用报告提出的循环次数右移方案。
本次仅复核和只读检查，没有修改电量算法、写入电量寄存器或重启设备。

## 1. 为什么会停在 90%

报告给出上电电压对应电量 `pocv_cap=998`、校准前值 `903`，随后
`SOC restore: ui=903 normal=968`。现有开机校准的计算是：如果电压估计比
保存值高超过 30 个千分点，校准后的 normal 为 `pocv_cap - 30`。
因此本例 `998 - 30 = 968`，并不是任意产生的 96.8%。

charger-manager 在放电状态禁止 UI 电量上升。当 normal 高于 UI 时保持 UI，
直到 normal 降到 UI 以下才继续按照平滑规则下降。因此 `normal=968` 与
`ui=903` 的差值足以解释停留现象。这是平滑状态停留，不是库仑计停止运行。
仅凭摘录不能验证停留时间的精确值或 normal 的绝对准确性。

已对照本机原厂 Android 的 `sc27xx_fuel_gauge.ko`，来源和 SHA256 见
[原厂电源行为记录](STOCK-POWER-RECOVERY-20261016.zh-CN.md)。二进制证据：

- `sc27xx_fgu_hw_init` 的 `0x3900–0x3968` 分别读取保存的 UI 和 normal。
  保存 UI 写入结构偏移 `0x80`，normal 写入偏移 `0x78`。
- `0x3a14–0x3a34` 对 normal 调用开机校准并保存，未同时覆盖保存 UI。
- `sc27xx_fgu_boot_cap_calibration` 的 `0x7a18–0x7a40` 同样使用 30 个
  千分点阈值，向上校准时取 `pocv_cap - 30`。

所以“保留 UI、校准 normal”也存在于原厂，并非新增恢复代码独有。
这不证明当前所有输入、运行环境和原厂完全相同；仍要区分保存值是否陈旧、
关机时间是否正确、上电 OCV 是否适用于本次启动。不能简单强制 UI=normal，
否则可能重新引入重启跳电、插电高估电量的问题。

## 2. 保存失败证明了什么

报告的两条 `failed to save current battery capacity` 证明相应的
`power_supply_set_property(..., CAPACITY, ...)` 返回失败。
但消息不含错误码，不能据此证明“每次都失败”，也不能区分：

- power_supply 框架或驱动就绪检查拒绝了请求；
- UI 保存/回读失败；
- UI 已成功，但 normal 保存/回读失败。

当前内核路径为 `sprd_fgu_set_property` → `sprd_fgu_save_capacity`。
保存函数分别校验 UI 与 normal，发生失败时已有更具体的日志：

```text
SOC retention UI: requested=... read=... ret=...
SOC retention normal: requested=... read=... ret=...
Failed to persist verified SOC: ...
```

需要保存失败时间点前后的完整原始日志，才能确认实际失败层级。
没有这些日志时，把故障直接归为 UI 没写进去、RTC 始终保留 903，均属推测。
目前写入时序已采用原厂的 masked update，不能仅凭本报告又改回强制写入。

另一个待验证的边界：过去的 100 次连续保存测试主要覆盖同一 UI 值，不能当作
所有跨整数、跨小数位变化及所有机器都可靠的证据。

## 3. `cycle=15` 不是循环次数

`sprd_fgu_cap_calculate_work` 打印：

```c
dev_info(data->dev, "battery soc = %d, cycle = %d\n", data->bat_soc, work_cycle);
schedule_delayed_work(..., msecs_to_jiffies(work_cycle * 1000));
```

这里是 **15 秒工作周期**。不存在报告所说的 `1020 >> 6` 对应关系。

现有源码明确注明内部 `charge_cycle` 使用 **0.001 次**单位，并按累计容量
增加该值。所以内部 1020 对应 1.020 次等效累计循环。
目前属性直接返回内部值，是否应对标准 CYCLE_COUNT 接口做单位换算，需要作为
独立的 ABI 问题核对；不能右移六位，也不能用 15 秒日志来验证循环次数。

## 4. 其他推断的边界

- E5 实际使用 AW322xx 充电芯片。`Cannot find power supply aw322xx_charger`
  若仅发生在启动依赖尚未就绪时，与运行期间持续找不到芯片的意义不同，不能
  一律归为预期配置差异。
- 未配置可选的容量 remap 或 step-charge 表，不自动等于驱动故障。
  3A 输入策略不代表接管或替代 JEITA。
- 根据报告电流和设计容量算出的下降幅度，与所列 normal 变化大致一致，
  支持运行期库仑积分仍在工作，不能据此证明电量绝对值准确。

## 5. 本机只读检查与下一步

2026-10-16 连接的自有 E5，同一 release 内核：电量由先前 78% 升至 82%，
最近一次读取 `battery.capacity=82`、`sc27xx-fgu.capacity=824`，USB SDP 充电。
当前保留的内核日志没有上述保存失败信息。只读取了 uevent 和 dmesg；没有读取
带有开关日志副作用的 debug/dump_info，也没有改写 SOC 或充电设置。
该结果不能替代朋友设备上的放电、重启故障验证。

后续应先确定保存失败的具体 errno、请求值和回读值，再检查 boot OCV、关机 RTC
以及原厂相同条件下的初始化输入。故障未闭环，不能宣称电量问题已经完全修好。

