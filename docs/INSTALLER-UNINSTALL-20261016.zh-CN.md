# 内置 OpenWrt 卸载与空间归还验证记录

日期：2026-10-16。**这是初版记录；2026-10-17 已增加未加密 data 保留与明确格式化选择，见 `INSTALLER-UNINSTALL-PRESERVE-20261017.zh-CN.md`。**此文为开发验证报告；面向用户的操作说明在 `installer/GUIDE.md`，并显示于安装器帮助页。

## 实现范围

E5 与 MU300 共用 `installer/backend/uninstall.py`、`uninstall_boot.py`、`uninstall_worker.py`、协议及 React 页面。入口为“高级选项 → 卸载并归还空间”。保留原 CLI、Python、Magisk 安装方式；没有恢复 FM_U20 支持。

- 缩容创建的 `e5root`/`mu300root`：移除该分区，恢复原 userdata 边界，通过原厂 Recovery 重置 Android。该路径清空 Android 用户数据，不宣称无损扩容。
- 使用原有 GPT 未分配空间创建的分区：移除 OpenWrt，释放空间为未分配，不扩大或重置 Android。
- 只支持有匹配原安装器分区创建记录及已校验 GPT 备份的独立内置分区。单独重装记录、TF、userdata 镜像及旧隐藏区域安装不作为此功能的恢复证据。记录或可信证据缺失时停止，不推测原容量。
- MU300 旧 `uninstall.sh` / `uninstall.ps1` 遇到 GPT `mu300root` 时转而提示使用新 GUI，避免误用旧隐藏区域卸载逻辑。

## 后端行为与安全边界

1. 计划阶段仅探测设备、读取布局及文件系统；要求原 CID、机型系列、GPT 身份、userdata 身份及其他分区条目一致，核对实际缩容几何关系或记录中的空闲区域位置。旧的大容量备份不能被用来额外吞并出厂空闲空间。
2. 确认前在应用数据目录持久化卸载记录、前后 GPT 快照及校验和。导入时重新计算允许的分区变更；即使重新计算文件校验和，也不能修改 NV、其他分区、目标范围或隐瞒必须重置的事实。
3. 执行时取得共用 CID/ADB 设备锁，重新核对当前 Android 槽、布局和备份。备份复用现有设备内 `dd` 后 ADB pull 的二进制传输，不使用 Base64。原 Android 启动槽始终作为只读源。
4. 基于已验证的安装包 boot v4 追加一次性 ramdisk，保留内核、机型驱动及初始化顺序。离线执行点位于根分区安装/更新/挂载之前；请求和 GPT 快照位于 ramdisk，不依赖重置后会消失的 `/data` 文件。已有周期 boot 日志写入在该一次性镜像中停用，避免与恢复 Android boot 的写入相互覆盖。
5. 离线执行校验 CID、分区未占用、前后 GPT 和工具数据。GPT 备份副本先写、刷新并回读，再写主副本并回读。缩容卸载由原厂 Recovery 负责格式化及加密；空闲区域卸载只清理已证明属于 OpenWrt 的签名。不会直接格式化 TF、NV 或校准分区。
6. 将当前可用 Android boot 复制到另一槽并回读校验，设置 Android 启动。Android 返回后复核分区表、OpenWrt 分区消失、userdata 容量、ext4/F2FS 超级块与设备映射容量、Recovery 请求已消费，以及 Android 启动控制；容量未达到要求不会宣告完成。
7. 完成或重连不会重放已完成的 GPT 变更或重新请求重置。中断的 boot 写入通过明确回读恢复；部分 GPT、未知布局或证据不足时停止并保留备份，要求离线恢复。该限制不能被“已进入 Android”或重新确认按钮绕过。
8. 已准备的一次性镜像带 `openwrt.uninstall=1` 标记。新的安装/临时启动遇到此标记或本地未完成卸载时停止，包括丢失电脑记录的情况。

Android 初始化和调试/root 授权没有固定等待时限。重置后无线地址改变或改接 USB 时，用户可暂停后在记录页明确选择新连接；后端核对 CID、机型和 Android 槽位后只更改传输入口，并对连接历史脱敏。不能自动选择另一台设备。

取消只停止电脑端协调器在安全边界后的操作。已下发的离线卸载不能靠关闭电脑撤回；确认页、执行页和使用指南均说明该行为。底层写入期间不会强杀进程。完成页保留 Android 实际容量，不展示 OpenWrt 访问地址或默认密码。

## 验证结果

- E5：`python -m unittest discover -s installer/tests -p 'test_*.py' -q`，165 项，7 项按环境跳过，其余通过。
- MU300：同一命令，165 项，9 项按环境跳过，其余通过。
- 新增 `test_uninstall.py` 共 22 项。Windows 的 3 项 BusyBox 测试跳过后，在 WSL 单独运行这 3 项，全部通过。
- BusyBox 测试使用临时稀疏普通文件：完整执行 GPT 提交、BCB 写入及 boot 复制；覆盖 A/B Android 槽、缩容重置请求、空闲区域不重置、已完成布局不重放重置、混合 GPT 副本的离线前滚、备份副本写入失败时不写主副本、未知布局不写入，并校验 Android/NV 数据标记不变。没有运行真实 Recovery 或格式化设备。
- 自动化还覆盖原备份缺失/损坏、重算校验和的越权布局、旧布局误归还额外空间、应用重启、预期断连、ADB 未授权、root 等待、设备身份不符、连接切换与脱敏、互斥、写入中取消延后、最终容量不足、Android boot 恢复，以及完成后仅复核不重装。
- 对现有 E5/M8/T551M 三个发布载荷及 MU300 `boot-mainline-7.2.img`、`boot-linux-slotb-tf.img` 做内存中的一次性 ramdisk 接入检查：原内核字节保持一致，执行点可定位且新增内容不越过保留区域。未写回这些载荷。
- `node node_modules/typescript/bin/tsc --noEmit --incremental false` 类型检查通过，不生成构建输出。
- `python -X utf8 installer/tests/uninstall_smoke.py --source` 在隔离临时 Vite 缓存及随机本地端口上运行，通过中英文、浅深主题、800×650 最小窗口、单次最终确认、持续可见的数据影响、已下发提示、Android 完成页面及明确选择重连设备的浏览器检查。后端桥接为测试传输；没有生成 `ui/dist`、EXE 或 APP。

主要页面：`installer/screenshots/uninstall-plan-reset-zh.png`、`uninstall-plan-gap-en.png`、`uninstall-complete-zh.png`。

**没有实机验证卸载、原厂 Recovery、设备离线启动或真实加密 userdata 重置。没有连接或修改用户设备；没有编译后端/Tauri 或重新打包，现有发布 EXE/APP 不包含本次源码更新。** 正式发布前仍需在明确授权的目标机上验证上述硬件路径。
