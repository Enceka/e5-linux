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
- 回退只是本机的手动路径。CI 设置 `E5_LANDSCAPE_DAEMON_REQUIRED=1`，产物
  缺失或与 `.sha256` 不符就直接失败，不再悄悄装回发布二进制。

### 4.1 CI

`e5-linux-release` 的 `landscape.yml` 原先只有 block-mount、kernel、image
三个 job，镜像里的 daemon 一直是上游发布资产，本补丁根本没有进 CI。现在多了
一个 `daemon` job（`needs: resolve`，与 kernel 并行）：

1. 先确认 `landscape_version` 输入与 `build-landscape.sh` 里的 `LS_VER`
   一致（web UI／redirect handler 来自该发布，daemon 来自源码固定的那个
   commit，两边版本不同就是错配），再取 `openwrt/build-landscape.sh
   --build-id`：该子命令只算哈希、不碰 Docker，任何 job 都能在不建容器的
   前提下复核"这个二进制是哪套输入造的"。build id 覆盖
   `landscape.Dockerfile`、两个构建脚本和全部
   `openwrt/patches/landscape-*.patch`。
2. 用 `actions/cache` 把 `work/landscape-cargo`（crate registry）跨 run 带
   过去；每个 runner 都是干净的，Docker 命名卷带不走。为此
   `build-landscape.sh` 现在接受 `E5_LANDSCAPE_CARGO`：是路径就 bind
   mount，是名字才是命名卷。
3. 构建后复核 `.sha256`、`.build-id` 和新增的 `.patches` 出处文件（固定
   commit + 每个补丁的 SHA-256），然后作为 `landscape-daemon-<run>` artifact
   上传，连同三个旁挂文件。
4. `image` job 改成 `needs: [resolve, kernel, daemon]`，把 artifact 还原到
   `out/openwrt` 并再校验一遍（含"build id 与当前源码一致"），然后
   `make-flash-bundle.sh` 在 `E5_LANDSCAPE_DAEMON_REQUIRED=1` 下组装镜像。

最后一步的打包校验也变了：原来是 `python3 tools/tests/landscape-bundle.py`
不带参数，它只拿 `openwrt/landscape` 目录造一个合成镜像，从来没看过真正的
产物。现在传 `--bundle <刚打出来的 zip> --daemon <构建的 daemon>`，
`landscape-bundle.py` 会把镜像里的 `/usr/sbin/landscape-webserver` dump 出来
和构建产物逐字节比较 —— 这正是"镜像里装的是不是打过补丁的那个"的直接证据，
而不是"镜像里有没有一个 aarch64 的 daemon"。

`tools/tests/landscape-image.py` 增加了一组静态检查（`class Daemon`）和一条
`E5_LANDSCAPE_DAEMON_REQUIRED` 的顺序检查，跑在 kernel/image 两个 job 的
"Check the OpenWrt landscape integration" 步骤里，所以补丁路径、build id 的
覆盖范围或缓存挂载被改动而没同步时，CI 会先在这里失败。

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
- CI 里新增的 `daemon` job 只在本机验证过它的校验逻辑（build id、`.patches`、
  `landscape-bundle.py --daemon` 的正反例），完整跑通要等下一次
  `Build Landscape Router OpenWrt` 的实际运行。

## 7. LAN 侧 IPv6：daemon 之外还有一处缺口

NAT 补丁修好了转发，镜像仍然没有 IPv6：客户端只拿到链路本地地址。原因是
Landscape 镜像的网络默认值本身没给 LAN 前缀，也没人发 RA。

### 7.1 现象与定位

- 镜像里的 `/etc/config/network`（`openwrt/standalone/network.landscape`）
  是 `proto 'none'` 且没有 `ip6assign`，`99-landscape` 又把 odhcpd 停掉，
  于是 br-lan 没有全局地址，也没有进程响应 RS。
- 上行本身没问题：`sipa_eth0` 有运营商的 `/64` 和默认路由，路由器
  `ping6` 外网 0% 丢失。缺的只是 LAN 侧通告。

### 7.2 为什么不能用 Landscape 自己的 LAN IPv6

两条路都试过，都走不通，根因和 §39 记的 relay 限制是同一个：`sipa_eth0`
是 raw-IP（NOARP）设备，`PACKET_ADD_MEMBERSHIP` 在上面失败。

1. **wan link 的 PD 客户端**。它把 UDP socket 绑到设备上再向 all-servers
   组播 soliciting，收不到 Advertise。通过 API 打开 `pd.enable` 后
   `runtime-status` 一直停在 `soliciting`：`expected_pd_len` 取 60/56/64、
   以及在 odhcp6c 让出 546 的情况下共 4 轮、每轮 60-80 秒，全部超时
   （日志 `DHCPv6 solicit timeout exceeded limit`）；同一时刻 netifd 的
   odhcp6c 在同一个 iface 上几秒内就拿到 `240a:42a4:1401:13d7::/64`。
2. **把委托前缀当静态父级**。`PUT /services/lan_ipv6` 用
   `parent.t = "static"` 指向运营商 `/64` 被拒：409
   `lan_ipv6.prefix_conflict.wan_reserved` —— 该 /64 槽位在 Landscape 里
   是给 WAN 保留的。

### 7.3 修法：委托留在 netifd，前缀下移到 LAN

和 §39 给非 Landscape 镜像验证过的做法一致：

- `network.landscape` 给 `lan` 加 `ip6assign '64'`。`proto 'none'` 保留，
  netifd 仍然不碰 IPv4（那是 Landscape DHCPv4 的，会被它删掉）。
- `99-landscape` 不再停 odhcpd，但只让它做 IPv6：`dhcpv4='disabled'`、
  `odhcpd.maindhcp='0'`（因此不会占用 67，Landscape 继续独占）、
  `ra='server'` + `ra_slaac='1'` 发地址、`ra_flags='other-config'` 让客户端
  用无状态 DHCPv6 取 DNS、`ndp='disabled'`（中继 NDP 正是这条链路做不到的
  那个模式）。dnsmasq 仍然关闭，53 还是 Landscape 的。

`ip6assign` 的地址由 netifd 在**接口重新配置**时下发：`/etc/init.d/network
reload` 不会重新分配，`/etc/init.d/network restart` 才会（实测：删掉 br-lan
上的全局地址后 reload 不回来，restart 立刻恢复）。这是 netifd 的正常行为，
不是缺陷。

### 7.4 验证

- 在设备上按 `99-landscape` 的 uci 命令逐条应用：odhcpd 起在
  `Features: ra ndp dhcpv6 no-dhcpv4 ubus`，67 仍是
  `landscape-webserver`。
- `/etc/init.d/network restart` 后 br-lan 拿到 `240a:42a4:1401:13d7::1/64`，
  `ubus call network.interface.lan status` 的 `ipv6-prefix-assignment`
  与 `wan_6` 的委托前缀一致。
- USB 网卡上的主机随即拿到同前缀的全局地址，默认路由 `proto ra`；
  `ping6 2400:3200::1` 与 `2001:4860:4860::8888` 均 3/3。
- 开机瞬间 odhcpd 会报 `No default route present, setting ra_lifetime to 0!`
  和一次 `Failed to send to ff02::1`：那是默认路由还没装好的短暂窗口，
  路由就位后停止，之后 40 秒静默。

`tools/tests/landscape-image.py` 原先断言了缺陷本身
（`assertNotIn('ip6assign', landscape)`）并要求 odhcpd 被关闭；两处都已
反转，另加一条测试把 odhcpd 钉在"只做 IPv6"。三条断言都做了变异检验：
去掉 `ip6assign`、把 odhcpd 改回 disable、把 `maindhcp` 改成 1，各自都会
让套件失败。
