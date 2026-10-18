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
