# Landscape IPv6 数据通路修复

E5 的上行是模组的 SIP 网卡，承载协商出来的 IPv6 方法只有 `dhcp`，网卡上只
拿到链路本地地址，没有全局地址也没有前缀委托。这种链路在 Landscape 0.26.3
上会让**整个 WAN 的 IPv6 完全不通**，包括路由器自己发出的报文。本文记录
根因与修复方式。

## 1. 根因

Landscape 把每条 WAN 的地址信息写进 eBPF map `wan_ip_binding`，键是
`(ifindex, l3_protocol)`。NAT 阶段的两个入口在查不到对应行时直接丢包：

```c
/* landscape-ebpf/src/bpf/nat/tc_nat6.h */
struct wan_ip_info_value *wan_ip_info =
    bpf_map_lookup_elem(&wan_ip_binding, &wan_search_key);
if (wan_ip_info == NULL) {
    return TC_ACT_SHOT;
}
```

`ipv6_egress_prefix_check_and_replace` 和
`ipv6_ingress_prefix_check_and_replace` 都是这样写的。当 WAN 链路只有 IPv4
时，map 里就只有 `l3_protocol = IPv4` 的行，IPv6 的报文在这个阶段被无条件
丢弃 —— 上行和下行都丢，连 RA/RS 与 DHCPv6 也一起吞掉，于是 LAN 侧既拿不到
前缀也没法转发。

同一个问题在路由阶段还有第二处：默认流（`resolved_flow_id == 0`）且没有
Landscape 目标时，`tc_lan_ingress_route` 和 `tc_wan_egress_route` 也以
`TC_ACT_SHOT` 收尾。

两处叠加的结果是：只要 WAN 没有 IPv6 绑定，IPv6 就完全不可用，而这条链路
其实应该退回内核路由。

## 2. 修复

`openwrt/patches/landscape-v6-nat-without-wan-binding.patch`：

1. `landscape-ebpf/src/bpf/nat/tc_nat6.h` —— 两个 v6 NAT 入口在缺绑定时由
   `TC_ACT_SHOT` 改为 `TC_ACT_UNSPEC`。没有 WAN 前缀就没有可做的 NAT，
   这一阶段应当放行，交给后续阶段和内核路由。
2. `landscape-ebpf/src/bpf/tc_lan_ingress_route.bpf.c` ——
   `tc_route6_pick_wan_in_lan` 的默认流分支返回 `TC_ACT_UNSPEC`。
3. `landscape-ebpf/src/bpf/tc_wan_egress_route.bpf.c` ——
   `tc_route6_pick_wan_in_wan_egress` 的同一情形返回 `TC_ACT_OK`。

显式流（`resolved_flow_id != 0`）缺目标时仍然 `TC_ACT_SHOT`，保持 fail-closed：
管理员明确指定了流却没有可用目标，是配置错误，不该静默走内核路由。

v4 不受影响：`tc_nat4.h` 里的 `TC_ACT_SHOT` 只出现在静态 NAT 查找
（`nat4_st_egress_lookup`）中，作用域本来就比 v6 小。

## 3. 回归测试

- 新增 `landscape-ebpf/src/tests/nat/v6/no_wan_binding.rs`：直接驱动两个 v6
  NAT 入口，断言 `wan_ip_binding` 没有该 ifindex 的 v6 行时返回
  `TC_ACT_UNSPEC` 且报文未被改写。把补丁反向变异（`UNSPEC` 改回 `SHOT`）
  该用例失败，改回即通过，因此它确实守住了这条路径。
- `landscape-ebpf/src/tests/route/tc_lan_ingress_v6/{first_packet,cache_paths}.rs`
  与 `landscape-ebpf/src/tests/route/tc_wan_egress_v6.rs`：原先断言“默认流
  无目标必须丢”的用例改为断言交给内核路由。

套件状态（`cargo test -p landscape-ebpf --features bpf-test --lib`，单线程）：
496 通过、6 失败、33 忽略。6 个失败在打补丁前就存在（4 个 truncated、2 个
runt 用例，报 `run tc_route6_wan_egress: Error: Invalid argument (os error 22)`），
用 `git show HEAD:` 的原始源码跑同样失败，是本机内核的限制。并发跑会出现与
用例无关的 SIGSEGV，用 `--test-threads=1`。

## 4. 构建

镜像里的 `/usr/sbin/landscape-webserver` 必须是打过补丁的版本，因此新增
`openwrt/build-landscape.sh`，产物落在
`out/openwrt/landscape-webserver-aarch64-static`，由 `build-rootfs.sh` 优先
取用：

- 源码是上游仓库的固定提交 `e9f019b5ff3b5306a7b336ee36693ca374618480`，
  构建前用 tree hash `9dd7bf0cb8cd53128a76765c0a52305abc287daf` 复核，
  移动或重写过的提交会在这里失败而不是悄悄换掉产物。
- 走上游自己的 `scripts/build_musl_static.sh`（cargo-zigbuild + Alpine
  sysroot 的 musl libelf/zlib/zstd），与发布产物同一条路径。
- `openwrt/landscape.Dockerfile` 固定 rust 1.98.0 以匹配该提交的
  `rust-toolchain.toml`；工具链不一致时 rustup 会去装一个没有 musl target 的
  1.98.0，报 `can't find crate for core`。
- `build-landscape.sh` 以 Dockerfile、脚本本身和全部
  `openwrt/patches/landscape-*.patch` 的哈希做 build id，命中缓存时直接复用
  并复核 `.sha256`；改任一补丁都会触发重建。
- `build-rootfs.sh` 在该产物存在且校验通过时用它替换发布二进制，并把它从
  发布资产列表里剔除；没有该产物时仍回退到上游发布二进制，同时在 stderr
  提示该二进制在本机型上没有 IPv6。

两个踩过的坑，都已写进镜像与脚本：

- `libz-ng-sys` 用 cmake 编 zlib-ng，镜像里必须装 `cmake`，否则
  `failed to execute command: No such file or directory` + `is cmake not installed?`。
- 不要在宿主机挂载的 target 目录上构建：磁盘写满时 `No space left on device`，
  脚本把 target 放在容器自己的文件系统里。

## 5. 验证要点

- 换二进制前后对比：只带路由修复的版本 `ping6` 100% 丢失，带 NAT 修复的
  版本 3/3 收到；换回旧二进制立刻复现，因果链闭合。
- LAN 侧用网络命名空间挂 veth 到 `br-lan` 当真实客户端（Mac 的 IPv4 默认
  路由被 VPN 抢走，没法直接测转发）：DHCPv4 拿到租约，IPv4 与 IPv6 转发
  均 3/3。
- 显式 v6 流、`flow_targets` 为空时该客户端 3 发 0 收，同网段默认流客户端
  正常，同一客户端的 IPv4 也正常；删除该流后立即恢复。这正是补丁刻意保留的
  fail-closed 行为。
- `/etc/init.d/landscape-router restart` 后 IPv4/IPv6 均正常，TC 钩子重新
  挂上（id 每次不同）。
- 整机 `reboot` 后约 30 s 重新拿到运营商前缀，`br-lan` 自动跟随，设备与
  LAN 客户端的转发均恢复。前缀跟着承载走，不能写死。

## 6. 未完成

- 真正需要按前缀翻译的静态 IPv6 NAT（`npt_mask != 0`）路径没有在真机上
  验证过；本机型的承载只给链路本地地址，走不到那条路径。
- `landscape-ebpf/build.rs` 里 `{e}` → `{e:#}` 的差异是调试用的错误信息
  格式改动，未纳入补丁。
