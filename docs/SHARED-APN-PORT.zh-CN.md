# 公共 APN 管理移植

来源：MU300 clean-tf-7.2 的独立看板 APN 页面和配置管理逻辑。

## 适用范围

E5、T551M、M8 都从 `openwrt/luci-app-t551m` 和
`devices/t551m/ui.py` 获取同一份功能；目录的历史名字不表示仅支持 T551M。
TF、公共 rootfs 和调用此 stager 的更新归档都会纳入页面、RPC、私有解析器、
默认配置和 netifd 拨号钩子。配置文件是 conffile，重复 staging 不覆盖用户配置。

## 功能与行为

- 蜂窝 → 接入点 APN：添加、编辑、删除、切换，最多 32 项。
- IPv4 / IPv4+IPv6；无鉴权、PAP、CHAP、PAP+CHAP；用户名、写入式密码。
- 编辑时空密码保留旧密码，勾选清除才删除；RPC 不返回密码。
- 切换默认按当前上网 SIM 的 ICCID 记忆；不是按看板查看卡槽记忆。
- 自动匹配公网运营商 APN，未知运营商使用 SIM 默认，不猜测专网 APN。
- 每次 netifd 拨号都解析当前 SIM，开机、断线重拨、切卡共用同一路径。
- 未绑定 SIM 使用全局接口设置，不继承另一张 SIM 的专网配置。
- 与切卡共用 flock；缺少 SIM 身份时禁止按卡配置绕过绑定。
- 只重新建立蜂窝连接，不重启整个网络、Wi-Fi 或 USB。
- 复用插件弹窗、toast、loading；官方主题及 Aurora 的令牌/回退样式。
- 中文、英文、土耳其语；菜单同时提供 PO 和 LMO。

## 平台适配

不复制 MU300 的 `mobile-data`，不另开 AT 串口读者。
`iptype`、`allowedauth`、`username`、`password` 使用 ModemManager 的 netifd 字段。
按卡配置仅改拨号的局部参数，不在切卡时改写全局 network UCI。
旧 `e5-apn-auto` 在公共解析器存在时退出，避免背景作业覆盖按卡选择。

公共 ModemManager 补丁 `modemmanager-13-unisoc-bearer-auth.patch` 在
SPSWDATA / CGACT / CGDATA 前，通过原有 AT owner 下发 CGPCO 鉴权。
拒绝引号、反斜杠、逗号、控制字符和非 ASCII 凭据，避免 AT/mmcli 参数注入。
鉴权失败不伪报成功，也不回传可能含密码的模组回显。

必须重新构建 ModemManager（E5REV=15），再构建 rootfs；已有 APK 构建状态
检查会发现新补丁。TF 用已有 clean base 增量组装时，base 也必须包含新版 MM。
仅更新看板而仍使用旧 MM 时，PAP/CHAP 应用被能力检查拒绝，不会假装生效。
全局无鉴权配置仍可使用；新的鉴权下发逻辑必须靠新版二进制才能执行。

独立漫游 IP 协议和初始附着 APN 编辑暂不支持，页面明确禁用、后端拒绝。
不操作 IMS CID，不把普通 APN 的代理字段伪装成系统 HTTP 代理。

## 验证与限制

可复现的本地检查：

```text
python devices/t551m/test_apn.py
node devices/t551m/test_feature_i18n.js
MU300_BROWSER_TESTS=1 MU300_BROWSER_CHANNEL=msedge python devices/t551m/test_apn_browser.py
python openwrt/luci-app-t551m/compile-menu.py
```

测试覆盖三个 profile 的公共文件 staging、用户配置保留、幂等 netifd hook、
SIM 身份与切卡锁、私有 RPC 防泄露、旧 MM 鉴权拒绝、原生补丁零 fuzz 应用、
三语言移动端增删改切与确认取消/失败状态。

`openwrt/tests/apn.uc` 是隔离 UCI 的配置/双卡回归：
用 ucode 的模块路径指向插件 `root/usr/libexec/unisoc-modem` 后执行。
本次 WSL 返回 HCS_E_CONNECTION_TIMEOUT，因此没有完成它的实际执行，
也没有完成新 MM 的交叉编译；本地 UI/adapter 检查不等于实机拨号验收。
本次没有连接 E5/T551M/M8 实机，也没有发送 AT、重启或改变其配置。
运营商真实 PAP/CHAP、各机型冷启动和切卡上网仍需用新版固件验收。

## 屏幕 APN 联动补全

屏幕入口：设置 → 网络 → 接入点 APN。E5、T551M、M8 共用屏幕 stager。
原来的 APN 字符串选择器、全局 WAN 写入和独立 e5-apn-auto 调用已经移除。
新增 `/api/apn` GET/POST 桥接公共 `mu300dash.apn_get/apn_set`，仅开放
`save/delete/apply/auto`，以 JSON 传递参数；不开放私有 `resolve`，不拼 shell/AT。

屏幕支持添加、编辑、删除、切换、运营商自动匹配、IPv4/双栈及鉴权配置。
密码从不预填；空密码保留原值，显式勾选清除才清除。保存仅更新配置列表，
应用与删除需要二次点按；失败保留编辑内容，公共后端错误有对应翻译。
认证 APN 在旧 MM 上禁用应用，可以先保存配置；不添加不支持的附着或漫游编辑。

按当前上网卡记忆选择，不跟随屏幕的查看/控制卡槽。屏幕提交时携带读到的
`data_sim`，公共后端在切卡互斥锁内校验当前卡；发生变化返回 `apn_sim_changed`，
要求刷新重新确认，避免把旧页面选择套到新卡。这个可选保护不改变既有网页请求。
当前上网卡发生变化时复用屏幕现有状态更新触发一次 APN 读取；缺失卡槽、
同一状态或暂时读取失败不触发持续重试，不新增后台轮询。

界面采用主题变量、可换行卡片、屏幕键盘可编辑输入，以及自绘协议/鉴权按钮，
避免原生 select 弹层不匹配主题；加载使用标题栏的既有指示，不挤动列表。
APN 文案有中文、英文、土耳其语版本，保留屏幕现有语言选择范围。

补全验证：

```text
python devices/t551m/test_apn.py
python devices/t551m/test_screen_apn.py
python devices/t551m/test_screen_apn_browser.py
node devices/t551m/test_feature_i18n.js
```

公共适配检查 15 项、三机型屏幕 staging/RPC 合约检查 2 项通过。
真实 staged 屏幕在 Chromium 的 320×480 视口完成增删改切、自动匹配、二次确认、
密码保留/清除、失败保留草稿、切卡刷新、鉴权能力限制和三语言明暗主题检查。
浏览器使用模拟 RPC，不连接实机；未把这些结果当作真实拨号验证，也未部署或
重新打包含新 MM 的刷机包。实际鉴权拨号仍需要先编译新版 MM。

### T551M 热部署（2026-10-12）

随后按用户要求部署到已连接的 T551M。确认 `/etc/e5/device-profile=t551m` 和
`6.18.54-t551m-otg10` 后，更新屏幕四个文件、公共 APN RPC/配置解析器、网页 APN
页面及菜单/ACL/翻译、旧自动 APN 兼容脚本，并补入当前 netifd 协议的 APN 解析钩子。
现有 `unisoc_apn` 配置保留；缺失时才创建默认配置。不修改当前选择或触发重拨。

真实 ARM64/ucode 隔离 UCI 回归 70 项通过，API 模板和 settings 的编译检查通过。
上传文件逐个 SHA256 回读通过；`mu300dash.apn_get` 与屏幕 `/api/apn` 均返回成功，
当前 SIM 1 身份可读取、WAN 保持已连接。rpcd 重启后的短暂未注册情况采用有限等待，
不会新增运行时重试循环。屏幕 api/seatd/ui 服务及 Cog/WPE 进程正常。

只重启 rpcd 和屏幕服务，不重启整机、热点、USB 或基带。原文件备份位于
`/root/update-backups/screen-apn-20261012-191859/`。
本次未更新 ModemManager 二进制：实机 `auth_supported=false`，需要鉴权的接入点
仍禁用应用；不能把界面上线视为 PAP/CHAP 拨号验收。E5、M8 本次没有实机部署。
