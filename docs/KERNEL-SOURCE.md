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

## lts-experiment（Landscape 镜像）

`lts-experiment` 是 Landscape Router 镜像所用的分支与配置，内核仍取 `e5-6.18`
（`b93bbc3a`）：6.18.54 的 Kconfig 已经提供 Landscape 数据路径需要的全部选项
（`BPF_LSM`、`LWTUNNEL_BPF`、`NETFILTER_BPF_LINK`、`IPV6_SEG6_LWTUNNEL`、
`BPF_PRELOAD`、`HID_BPF`、`BPF_JIT_ALWAYS_ON`），因此不需要另开实验内核分支。

配置片段随清单走：`E5_KERNEL_MANIFEST` 选中
`upstream/kernel-source-lts-experiment.json` 时，`upstream/build.sh` 使用
`upstream/e5-lts-experiment.config`（即 `e5-mainline.config` 加上 Landscape 的 BPF
选项段），发布基线 `e5-mainline.config` 与 `kernel-source.json` 保持不变。

（旧的 `e5-7.2-experiment` 分支不是 LTS：Linux 7.2 没有进入 longterm 列表，它只是把
`e5-6.18` 的设备提交重放到 7.2.11（`a2de78ee6ed8`），并修正 7.2 移除的 API
（`strncpy()`、`of_gpio.h`、`alarm_start_timer()`、per-CPU workqueue 等）。它与 6.18
没有共同历史，因此不能通过 `upstream/kernel-source.json` 的祖先检查。该分支保留作
参考，Landscape 镜像不再使用它。）

Landscape 构建的固定清单是
[`upstream/kernel-source-lts-experiment.json`](../upstream/kernel-source-lts-experiment.json)，
最低提交 `b93bbc3a36fd3c1acae0e44b93d909f7fe942182`（即 `e5-6.18`）。构建时显式选择：

```sh
E5_KERNEL_MANIFEST=upstream/kernel-source-lts-experiment.json upstream/build.sh
```

发布 workflow 仍默认 6.18 与 `upstream/kernel-source.json`；只有 Landscape 构建
workflow 使用 lts-experiment 清单与其配置片段。

在 `e5-7.2-experiment`（7.2.11）上曾验证 Wi-Fi AP、5G 数据、充电、显示/触摸和音频；
6.18 已有的 charger-manager `-22`、`asoc_sprd_card_parse_of` `-517`、thermal v2t 和
sprd_serial DMA 告警在 7.2 同样存在，未新增 workqueue 告警或 Call trace。USB NCM 的
DHCP 在 7.2.11 上取不到地址（服务器 ACK 的 UDP 校验和固定错误 `0xcae6`，主机
`rx-checksumming` 为 `off [fixed]` 时内核直接丢包），这也是改用 6.18 构建 Landscape
镜像的原因之一。
