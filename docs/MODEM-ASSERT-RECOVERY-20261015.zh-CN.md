# CP 断言后等待 dump 导致“无模组”的恢复补齐

## 问题边界

E5 故障报告记录了：CP 先出现 `Modem Alive`，约 23 秒后发生
`drm_rfresourcehandle.c:3925 / Drm allocate spr rf path fail! / res_type=16`，
随后 `modem_control` 等待 dump 完成，界面显示无模组。

报告观测的断言后约 78 秒未超过历史上已测得的 300 秒 dump 等待上限，
不能据此认定永远不能恢复。射频断言本身的触发条件也尚未证明；
FINDINGS §47.2 有同签名历史，不能把该样机的频段经验硬编码到所有设备。

当前公共构建安装了 `e5-modemd` 和服务脚本，却没有默认启用 E5 的服务。
M8 已单独启用，现统一为 E5／T551M／M8 的公共 staging 功能。

## 实现

- 启用 `S22e5-modemd`，仅订阅厂商的抽象 Unix socket `@modemd`。
- 收到 Assert／Blocked 事件或连接时对应的状态快照，回复带 NUL 的
  `SLOGMODEM DUMP COMPLETE`，允许厂商按既有流程复位 CP。
- 这表示跳过 CP 内存 dump；原有 Android 文本日志仍保留断言原因。
- 跨 `read()` 保存有限长度的状态后缀，兼容拆分、合并、无末尾 NUL 和较长原因文本。
- 完整发送确认；处理 EINTR 和断连，不因 SIGPIPE 静默退出。
- 断连后由原有 procd respawn 重连，不增加正常运行时轮询。
- `K09e5-modemd` 在厂商服务退出前停止本助手；不改变厂商/NV 服务的内部启停顺序。
- 普通 rootfs 构建和三机型 staging 均接入；三机型打包入口检查启用链接，缺失则拒绝打包。

**没有修改**开机回放、AT 路由、ModemManager 初始化及拨号命令顺序。
助手不调用 AT、mmcli、SFUN、ifup/ifdown，不操作 NV、不重放配置，
也不自动重启 ModemManager 或厂商服务。手动 `e5-modemd blocked` 入口保留，
不会由监听路径自动执行。

本次只解除 dump 等待这一宿主侧恢复堵点，不宣称修好了射频固件断言本身，
也不承诺所有基带构建都能在固定秒数内恢复。

## 验证与部署

- `openwrt/tests/modem-recovery.py`：10 项测试，真实编译 C 程序、使用私有抽象 socket；
  包含四类异常通知每个前缀拆分位置、合并／无 NUL 消息、长原因、正常启动静默、
  断连重启、服务晚启动及离线 staging 幂等／保留现有配置。
- 既有回放 9 项、AT 路由 3 项、网络启动 8 项测试通过。
- ARM64 静态程序使用 `-Wall -Wextra -Werror` 编译通过，未修改内核或 ModemManager 二进制。
- 已热部署到当前连接的 `192.168.9.1` E5，只替换助手与服务脚本并启用。
  确认收到 `Modem State: Alive`；基带、ModemManager PID 及模组枚举结果保持不变。
- 没有主动触发实机 CP 断言／复位，真实故障后的完整恢复耗时仍待确认。
- 打包保持暂停；已有发布 ZIP 尚未包含本次恢复修复。

测试命令（Linux／WSL，不访问真实 modem／AT／NV）：

```sh
python3 openwrt/tests/modem-recovery.py
python3 devices/t551m/test_boot_replay.py
python3 devices/t551m/test_at_routing.py
```
