export const helpStrings = {
  zh: {
    help:'帮助与使用指南', helpIntro:'离线可用。按主题查阅，也可以搜索型号、授权或续装问题。', close:'关闭帮助', closeGuide:'关闭新手引导',
    search:'搜索使用指南', searchPlaceholder:'搜索，例如：USB、Magisk、续装…', topics:'指南主题', noResults:'没有找到相关内容，试试“授权”“安装记录”或“TF”。', results:'个相关主题',
    guide:'新手引导', guideIntro:'先了解准备、安装选择和中途等待，再开始操作。', firstTime:'第一次使用？', firstTimeDesc:'先看三个步骤，了解安装前准备和重置后如何继续。',
    replay:'重新查看新手引导', skip:'暂时跳过', next:'下一步', back:'上一步', finish:'开始使用', step:'第', of:'步，共 3 步',
    introTitles:['准备设备和安装包','选择适合你的安装方式','等待、续装与保留备份'],
    introBodies:[
      ['完整解压安装包，从根目录 OpenWrt-Installer.exe 启动，无需另装 Python、Node 或 Rust。','先备份需要保留的数据，保持设备供电。使用数据线连接；只有无线 ADB 时，在设备选择区展开“无线 ADB 连接”，填写地址并连接。','在 Android 开启 USB 调试、允许电脑调试并准备好 root；连接多台设备时，必须明确选择目标设备。'],
      ['首次安装从“安装 OpenWrt”开始。TF 卡只格式化选定目标，不重新划卡；内置分区会先检查未分配空间。','核对最终计划里的机型、写入目标、Android 保留空间和数据影响。需要重置时，Android 用户数据会被清空。','已装好 OpenWrt 时可选择更新或临时启动；重装和有 F2FS 损坏风险的实验性镜像放在高级选项。'],
      ['首次离线分区准备可能需要数分钟，之后会自动重启。预期断线、Android 初始化和授权都是等待状态。','重置后完成 Android 初始化、开启 USB 调试并允许授权。已有 root 会直接使用；只有 root 不可用时才需要恢复 Magisk。','安装记录自动保存在电脑。关闭或重启后从“继续未完成的安装”恢复；换电脑前导出完整事务与备份。电脑记录和备份都丢失时，目前无法仅凭设备自动重建续装记录。'],
    ],
    noAction:'开始安装前，请核对设备、写入目标和数据影响，并备份重要文件。', currentHelp:'查看当前步骤帮助',
  },
  en: {
    help:'Help and user guide', helpIntro:'Available offline. Browse a topic or search for connection, authorization or recovery help.', close:'Close help', closeGuide:'Close getting started',
    search:'Search the user guide', searchPlaceholder:'Search: USB, Magisk, recovery…', topics:'Guide topics', noResults:'No matches. Try “authorization”, “records” or “TF”.', results:'matching topics',
    guide:'Getting started', guideIntro:'Learn what to prepare, which path to choose and what to do while waiting.', firstTime:'First time here?', firstTimeDesc:'Three short steps cover preparation, installation choices and resuming after a reset.',
    replay:'Replay getting started', skip:'Skip for now', next:'Next', back:'Previous', finish:'Start using the installer', step:'Step', of:'of 3',
    introTitles:['Prepare your device and package','Choose an installation path','Wait, resume and keep backups'],
    introBodies:[
      ['Extract the complete package and run OpenWrt-Installer.exe at its root. No separate Python, Node or Rust is required.','Back up important files and keep the device powered. Connect by data cable, or use Wireless ADB connection in the device section and enter its address.','Enable USB debugging on Android, authorize this computer and have root ready. When several devices are connected, select the intended device explicitly.'],
      ['Use Install OpenWrt for a first installation. TF installation formats only the selected target without repartitioning the card. Internal installation checks unallocated space first.','Review the model, write target, retained Android space and data impact in the final plan. A required Android reset erases its user data.','For installed OpenWrt, choose update or a one-time boot. Reinstallation and the experimental image option, which can damage F2FS, live under Advanced options.'],
      ['The first offline preparation may take several minutes and then reboot automatically. Expected USB disconnects, Android setup and authorization are waiting states.','After a reset, complete Android setup, enable USB debugging and grant authorization. Working root is accepted immediately; restore Magisk only if root is unavailable.','Installation records are saved automatically on the computer. After closing or restarting, choose Continue an unfinished installation. Export the full transaction and backups before moving computers. If both records and backups are lost, this version cannot reconstruct a record from the device alone.'],
    ],
    noAction:'Before installing, check the device, write target and data impact, and back up important files.', currentHelp:'Help for this step',
  },
};
