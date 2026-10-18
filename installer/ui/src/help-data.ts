import guide from '../../GUIDE.md?raw';
import type {Language} from './i18n';

/** The in-app manual and START-HERE.md use the same checked-in document. */
export function helpTopics(language: Language) {
  const localized = language === 'zh' ? guide.split('## 中文')[1]?.split('## English')[0] : guide.split('## English')[1];
  const parts = (localized || '').trim().split(/^### (.+)\r?$/m);
  const sections = new Map<string, string>();
  for (let i=1; i<parts.length; i+=2) sections.set(parts[i].trim(), parts[i+1].trim());
  const zh = language === 'zh';
  return [
    {id:'start', title:zh ? '开始之前' : 'Before you start', markdown:parts[0]},
    {id:'purpose', title:zh ? '选择安装方式' : 'Choose your purpose', markdown:sections.get(zh ? '选择用途' : 'Choose your purpose')},
    {id:'storage', title:zh ? 'TF 卡与内置容量' : 'TF card and capacity', markdown:zh ? `### TF 卡\n\n${sections.get('TF 卡')}\n\n### 独立内置分区\n\n${sections.get('独立内置分区')}` : sections.get('Storage and capacity')},
    {id:'reset', title:zh ? 'Android 重置后续装' : 'Resume after Android reset', markdown:sections.get(zh ? '加密 userdata：重置后自动续装' : 'Encrypted userdata and reset')},
    {id:'update', title:zh ? '更新与自动重启' : 'Updates and automatic restart', markdown:sections.get(zh ? '更新与自动重启' : 'Updates and automatic restart')},
    {id:'uninstall', title:zh ? '卸载并归还空间' : 'Uninstall and return space', markdown:sections.get(zh ? '卸载内置 OpenWrt 并归还空间' : 'Remove internal OpenWrt and return space')},
    {id:'recovery', title:zh ? '安装记录与失败恢复' : 'Records and recovery', markdown:sections.get(zh ? '暂停、关闭与失败恢复' : 'Recovery and results')},
    {id:'faq', title:zh ? '连接与常见问题' : 'Connection and troubleshooting', markdown:sections.get(zh ? '连接与常见问题' : 'Connection and troubleshooting')},
  ].map(topic => ({...topic, markdown:topic.markdown || ''}));
}

