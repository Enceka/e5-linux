# 蜂窝发射功率控制可行性评估

日期：2026-10-17。仅评估，不实现、不部署功率控制，不发送功率设置命令。

后续针对“提高功率”的原厂 CP 固件查证、NR 最大 PA 参数边界、E5 / M8 原厂 EngineerMode 的完整命令格式与新增只读查询，见 [提高功率定向查证](MODEM-TX-POWER-INCREASE-EVIDENCE-20261017.zh-CN.md)。

## 结论

已找到可复用的原厂**功率回退**接口，值得继续研究。当前证据不足以推出“任意设定发射功率 / 精确 dBm 调节 / 增强功率”的功能，也不足以直接发布可调档位：参数单位、有效范围、不同频段的映射和实际效果尚未确认。

控制通道本身不需要新的内核驱动；现有 AT owner 可以承担传输。主要缺口是固件参数语义和结果验证，不是补一个网页滑块。

继续查证后，确认 E5、M8 原厂工程应用可以生成指定 dBm 的 `SPMAXRFPWR` NR 工程测试命令，应用校验范围为 `-43..27`，并有明确清除命令。不过它需要指定频点、带宽、调制和天线，包含连续波模式；原厂另一个 LTE PA 测试流程还明确要求飞行模式。这些测试入口不能作为已经验证的联网增强功能。应用允许输入 27，也不能证明实际输出或正常联网的最大功率是 27 dBm。

## 原厂二进制证据

从本地保存的原厂 vendor 提取 `libimpl-ril.so`，不是依据同平台网上命令猜测。

| 机型 | 架构 | `downgradeRadioPower` 地址 | 确认内容 |
| --- | --- | --- | --- |
| U30 Air | AArch64 | `0x6a1a0` | 完整命令组装、发送、完成回调和 HAL 请求链 |
| 荣悦 E5 | AArch64 | `0x6a5c0` | 相同的命令组装与应答判断 |
| VIPME M8 | AArch64 | `0x69ae0` | 相同的命令组装与应答判断 |
| T551M | ARM / Thumb | 符号 `0x51e2d`，指令起点 `0x51e2c` | 相同的双整数加载、条件追加与命令发送结构 |

U30 Air 原厂 `librilcore.so` 另有导出符号：

```text
ExtRadioNetwork::setRadioPowerFallback(int, bool, int)
```

反汇编确认：第一个 int 是请求序号；bool 和末尾 int 被作为两个请求参数发往 `RADIO_POWER_FALLBACK`（请求号 4032），再分发到 `downgradeRadioPower`。U30 Air 的分发表地址 `0x1b042`，对应分支 `0x6a684`。

RIL 的命令组装等价于：

```text
cmd = "AT+SPPOWERFB=" + 第一个数据参数
若第一个数据参数为 1，且第二个数据参数 >= 0：
    cmd += "," + 第二个数据参数
向该请求的 SIM socket 发送，按 AT 传输结果与 final response success 判定完成。
```

这里的 `>= 0` 只是 RIL 的组装条件，**不是固件允许任意非负数的证据**。函数没有读取发射功率的返回值。HAL 方法名、bool 参数和函数名共同支持“启用 / 取消功率回退”的解释；各模式的电气效果尚未做写入测试。

来源版本：

- U30 Air vendor：`ZTE/U30Air/U30Air:13/TP1A.220624.014/20241127.203422:user/release-keys`。
- E5 vendor：`UNISOC/ums9158_1h10_cmcc/ums9158_1h10:13/TP1A.220624.014/2024112822:user/release-keys`。
- T551M vendor：`onetouch/TYT_00CM_FIH/TYT:13/TP1A.220624.014/551MCM08:user/release-keys`。
- M8：本地原厂 ROM 提取目录 `vipme_m8/erofs/vendor_a/lib64/libimpl-ril.so`；此条不据此推定所有 M8 固件版本一致。
- F50 / V50 未在本轮分别核对原厂 RIL 与运行固件，不能因为与 U30 Air 共用仓库就直接启用。

SHA-256：

```text
U30 libimpl-ril.so a0e8e71fa1f4afda302f7471abd419f9f861256ebe7a63a4421c00cdb0c8b3ec
E5  libimpl-ril.so c0e86a5a6d7402a3d126e411fdb956deb8a6454763d55505c3ba64f839d0c14b
M8  libimpl-ril.so 9cbd0703dc8d8babeacde5d2779f82ad61c6f8b85668663d6a41bc63ee4a5a12
T551M libimpl-ril.so 142e7467f86dd484b7e20e3bfc2780b5132821661e0980c38b4e478dacd67630
U30 librilcore.so cb68b650d52e1a2bc4f645c0db6ecf077c0044d36233d03bc1b80c9f0cf8c050
```

## U30 Air 实机只读查询

已复核设备身份 `u30air`；使用原 `/usr/libexec/unisoc-modem/at`，`MU300_SIM_SLOT=0`，每条超时 3 秒。没有打开 tty 另抢通道。

运行固件返回：

```text
Platform Version: MOCORTM_V2_23A_W25.03.2_Debug
Project Version: QogirN6Pro_PS
BASE Version: 5G_MODEM_V2_23A_W25.03.2
HW Version: ums9620_modem
01-14-2025 10:14:02
```

| 查询 | 实际返回 | 能得出的结论 |
| --- | --- | --- |
| `AT+SPPOWERFB?` | `+CME ERROR: 65536014` | 本轮未取得当前状态；不能把传输工具退出码 0 当作设置成功 |
| `AT+SPPOWERFB=?` | `+SPPOWERFB:(),(),()`，随后 `OK` | 固件能处理测试形式，但没有给出枚举或范围；不证明设置形式的效果 |

两条功率相关只读查询各约 0.08–0.10 秒返回。没有发送 `SPPOWERFB` 设置、SFUN / CFUN 设置，没有改 NV、重启基带或改变网络配置。

## 现有软件支持与缺口

- 两仓库没有已实现的 `SPPOWERFB` 功率设置功能。现有 AT 入口可传递此类请求，公共网络操作锁和每 SIM 寻址可复用；不需要复制拨号流程。
- E5 的 Unisoc ModemManager 插件没有实现对应 SAR 功率后端。ModemManager 的通用 SAR API 存在，不等于当前 Unisoc 设备已经支持。
- 当前查询无法回读设置。如果未来实现，只能区分“命令已接受 / 最后请求的设置 / 实际状态未知”，不能将本地保存值冒充基带实测值。
- RIL 按 SIM socket 发命令，不足以证明双卡的功率限额互相独立。共享射频、LTE / NR 并发、不同频段和天线的作用范围仍未知。
- 当前参数是功率上限、衰减量还是档位索引，尚未确认；数字越大是否降得越多，也未确认。不能凭命令名给参数贴 dBm、dB、百分比标签。
- 是否立即生效、断网 / 切卡 / 重启后是否保留、是否覆盖厂商 SAR / 热管理策略，尚未确认。本轮不增加自动回放。
- 未确认可用的实际发射功率读取字段。RSRP / RSRQ / SINR 是接收侧指标，不能用来证明发射功率设置已生效；Speedtest 也不能替代功率测量。

## 后续实现判断

较合适的目标是**原厂功率回退模式**，在确认固件映射后提供有限、可解释的选项；先保留默认行为，避免暴露没有依据的任意数值。

进入实现前还需：确认参数映射、确认可恢复默认、进行受控写入与实际功率 / 链路效果验证，并分别确认 LTE / NR 和双卡范围。这些均未在本轮执行。

若只能得到 OK 而不能确认物理效果，则不应将其发布成精确功率控制功能。若目标是提高原厂允许的最大发射功率，本次没有找到可支持该目标的证据。

通用参考：

- [ModemManager SAR 接口定义](https://raw.githubusercontent.com/linux-mobile-broadband/ModemManager/main/introspection/org.freedesktop.ModemManager1.Modem.Sar.xml)：SAR level 的映射由设备厂商定义，可能按频段、天线变化；该通用说明不能替代本机映射表。
- [3GPP TS 38.213 / ETSI TS 138 213](https://www.etsi.org/deliver/etsi_ts/138200_138299/138213/17.02.00_60/ts_138213v170200p.pdf)：上行发射功率受网络功控和终端最大功率预算共同约束，不能将一个限制参数等同于持续固定输出功率。

离线原始材料位于本机 `e5-linux/work/tx-power-audit-20261017/`，包含 RIL 副本、反汇编、字符串交叉引用、请求分发表校验和只读查询 JSON；不随刷机包分发原厂二进制。
