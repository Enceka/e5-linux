# 内核源码与固定版本

2026-10-18。通用构建与 E5 专用构建共用
[`sprd-linux-devs/linux`](https://github.com/sprd-linux-devs/linux) 的 `e5-6.18` 分支。
最低提交 `b93bbc3a36fd3c1acae0e44b93d909f7fe942182` 记录在
[`upstream/kernel-source.json`](../upstream/kernel-source.json)，基线为 `020b970e351e`。

原有 display、power、charger-capabilities、eMMC、SD power、thermal、SIPA、
Wi-Fi TX/SAE/stations 和 fuel-gauge 通用策略形成 11 个内核提交；EIC 修复已存在，
没有重复提交。策略来源为 `linux_device_common` 的 `90d418efe480`。
通用 Docker/本机构建入口移除重复应用，检查最低提交和源码状态；Docker 只读挂载源码。

E5 的准备脚本只保留 USB charger/OTG、CPUFreq、Wi-Fi 生命周期与队列、AW32257
及 WCN 日志的机型差异。它们仍由设备仓库管理，不创建另一条内核分支。需要同时构建
不同配置时可使用同一仓库的临时 worktree；不要从 T551M 适配过的工作区构建 E5。
M8/T551M 的现有版本检查与适配入口保留。

`CONFIG_LOCALVERSION_AUTO=n` 配合构建入口显式的空 `LOCALVERSION`，使内核只显示
基础版本和原有设备标识，例如 `6.18.54-e5`、`6.18.54-e5-mobile4`。关闭 AUTO
但不设置 `LOCALVERSION` 仍可能出现 `+`。这个设置只控制版本显示，E5 专用适配执行后
Git 仍会显示源码修改；通用构建不会应用这些差异。

固定版本不是源码或模块兼容性凭证。发布清单 `build.json` 记录实际内核和设备提交，
E5 专用输出另存 `source-commit`。改动驱动后一起重建内核和模块，并保留包内哈希校验。
验证包括真实 Git 历史检查、旧适配器幂等校验、驱动 C 回归及 Actions 整包构建；
这些离线检查不代表实机充电、Wi-Fi 或蜂窝验证。

在 macOS 上本地跑完整容器构建时，`check-container-support.py` 会报
`Root module differs from boot build: xt_RATEEST.ko`。这不是构建错误：内核同时提供
`net/netfilter/xt_RATEEST.c`（target）和 `xt_rateest.c`（match），两个模块只差大小写；
扁平暂存到宿主的 `out-release/modules/` 时，不区分大小写的 APFS 让一个覆盖另一个，
而归档 `modules.tar` 里两个都在。同一份产物在大小写敏感的 Linux 语义下（容器内或 CI）
校验通过，共 253 个模块。本地复验请在容器内或 CI 上做这一步。

## lts-experiment 与 e5-7.2-experiment（Landscape 镜像）

Landscape Router 镜像现在有两条内核线，分支与清单一一对应。`lts-experiment` 取
`e5-6.18`（`b93bbc3a`），清单是
[`upstream/kernel-source-lts-experiment.json`](../upstream/kernel-source-lts-experiment.json)；
`e5-7.2-experiment` 取 `e5-7.2`（7.2.11，基线 `a2de78ee6ed8`），清单是
[`upstream/kernel-source-7.2.json`](../upstream/kernel-source-7.2.json)。两条分支的内核
之外的内容完全相同，差别只在清单指向哪条内核分支，因此同一份 Landscape 集成不必维护
两遍，两边合并也不会产生内容冲突。

两个清单都要求各自内核线的 USB NCM 校验和修复：没有它，Landscape 镜像在 NCM 上取不到
DHCP 地址。6.18 侧是 `6692deff8885`，7.2 侧是把同一对提交重放过去的 `7e19780b4699`，
清单的 `minimum_revision` 固定在修复之后，构建入口据此做祖先检查。

两条线共用同一份配置片段
[`upstream/e5-landscape.config`](../upstream/e5-landscape.config)：它就是
`e5-mainline.config` 加上 Landscape 的 BPF 选项段，6.18.54 与 7.2.11 的 Kconfig 都能
原样吃下这些符号（`BPF_LSM`、`LWTUNNEL_BPF`、`NETFILTER_BPF_LINK`、
`IPV6_SEG6_LWTUNNEL`、`BPF_PRELOAD`、`HID_BPF`、`BPF_JIT_ALWAYS_ON`），所以片段按
"哪些清单算 Landscape" 来选，而不是按内核版本：`upstream/build.sh` 与
`upstream/build-native.sh` 的 `case` 匹配 `*kernel-source-*.json`，任何带后缀的清单都
落到 `e5-landscape.config`，裸的 `upstream/kernel-source.json`（发布基线）继续用
`e5-mainline.config`。发布基线因此一个选项都没动。

构建时显式选择清单：

```sh
E5_KERNEL_MANIFEST=upstream/kernel-source-lts-experiment.json upstream/build.sh   # 6.18
E5_KERNEL_MANIFEST=upstream/kernel-source-7.2.json upstream/build.sh             # 7.2
```

发布 workflow 仍默认 6.18 与 `upstream/kernel-source.json`，这是刻意的：6.18 是已经过
实机验证的那条线，默认路径不该因为多了一条实验内核线而改变；Landscape 构建 workflow
的 `source_ref` 才决定这次用哪条分支和哪份清单，它默认 `lts-experiment`（6.18），要
7.2 的镜像时把它指到 `e5-7.2-experiment`。

在 `e5-7.2-experiment`（7.2.11）上曾验证 Wi-Fi AP、5G 数据、充电、显示/触摸和音频；
6.18 已有的 charger-manager `-22`、`asoc_sprd_card_parse_of` `-517`、thermal v2t 和
sprd_serial DMA 告警在 7.2 同样存在，未新增 workqueue 告警或 Call trace。USB NCM 的
DHCP 在 7.2.11 上曾取不到地址（服务器 ACK 的 UDP 校验和固定错误 `0xcae6`，主机
`rx-checksumming` 为 `off [fixed]` 时内核直接丢包），7.2 线现在带着同一对 gadget
校验和修复，正是 `kernel-source-7.2.json` 把 `minimum_revision` 钉在修复之后的原因。

6.18 仍是发布 workflow 的默认，因为它是唯一走完整实机验证的内核线；7.2 线用于在 7.2
内核上验证 Landscape，默认值不为它改动。
