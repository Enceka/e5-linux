import {useEffect, useState} from 'react';
import {Copy, Github, Heart, Star} from 'lucide-react';
import {Button} from './ui/button';
import {Dialog, DialogContent, DialogDescription, DialogTitle} from './ui/dialog';
import {strings, type Language} from '../i18n';
import fallback from '../assets/donation-fallback.png';

export const REPOSITORIES = [
  {id:'e5',name:'e5-linux',url:'https://github.com/sprd-linux-devs/e5-linux',authors:'Enceka · Minikano'},
  {id:'mu300',name:'mu300-linux',url:'https://github.com/dikeckaan/mu300-linux',authors:'dikeckaan · Minikano'},
] as const;
export type RepositoryId = typeof REPOSITORIES[number]['id'];
export const DONATION_IMAGE = 'https://api.kanokano.cn/pay/zsm.png';
const GROUPS = [[0,'376737485'],[2,'1016263950'],[3,'950666902'],[4,'262019320']] as const;

export function SupportInfo({language,onCopy,onRepository,onSupport}:
  {language:Language;onCopy:(number:string)=>void;onRepository:(repository:RepositoryId)=>void;onSupport:()=>void}) {
  const t = strings[language];
  return <div className="support-info">
    <div className="support-author"><span>{t.installerAuthor}: <strong>Minikano</strong></span></div>
    <div className="community-groups">{GROUPS.map(([group,number]) => <button key={group} title={t.copyGroup} aria-label={`${t.copyGroup}: ${number}`} onClick={() => onCopy(number)}><span>{t.qqGroup}{group}:</span><span className="community-number">{number}</span><Copy size={11}/></button>)}</div>
    <Button variant="outline" className="support-entry" onClick={onSupport}><Heart size={14} aria-hidden="true"/>{t.support}</Button>
    {REPOSITORIES.map(repo => <a key={repo.id} className="repository-link" href={repo.url} title={`${repo.url}\n${t.author}: ${repo.authors}`} aria-label={`${repo.name} · ${t.author}: ${repo.authors}`} onClick={event => {event.preventDefault();onRepository(repo.id);}}><Github size={16} aria-hidden="true"/><span><strong>{repo.name}</strong><small>{repo.authors}</small></span></a>)}
  </div>;
}

export function SupportDialog({language,onOpenChange,onRepository}:{language:Language;onOpenChange:(open:boolean)=>void;onRepository:(repository:RepositoryId)=>void}) {
  const t = strings[language];
  const [source,setSource] = useState<'online'|'fallback'|'failed'>('online');
  const [loaded,setLoaded] = useState(false);
  useEffect(() => {
    if (source !== 'online' || loaded) return;
    const timeout = setTimeout(() => setSource('fallback'),5000);
    return () => clearTimeout(timeout);
  }, [source,loaded]);
  return <Dialog open onOpenChange={onOpenChange}>
    <DialogContent closeLabel={t.closeSupport} className="support-dialog">
      <div className="dialog-heading"><div className="eyebrow">MINIKANO · OPENWRT INSTALLER</div><DialogTitle>{t.support}</DialogTitle><DialogDescription>{t.supportDescription}</DialogDescription></div>
      <div className="support-body scroll-area">
        <div className="support-star-intro"><strong>{t.starTitle}</strong><p>{t.starDescription}</p></div>
        <div className="support-repositories">{REPOSITORIES.map(repo => <a key={repo.id} className="support-repository" href={repo.url} title={repo.url} aria-label={`${t.starAction}: ${repo.name}`} onClick={event => {event.preventDefault();onRepository(repo.id);}}>
          <Github size={21} aria-hidden="true"/><div><strong>{repo.name}</strong><p>{t.author}: {repo.authors}</p><span>{repo.url}</span></div><Star size={18} aria-hidden="true"/>
        </a>)}</div>
        {source === 'failed' ? <p role="status">{t.supportImageUnavailable}</p> : <div className="support-image">
          {!loaded && <p className="support-image-loading" role="status">{t.supportImageLoading}</p>}
          <img key={source} src={source === 'online' ? DONATION_IMAGE : fallback} width={613} height={514} alt={t.supportImageAlt} referrerPolicy="no-referrer" onLoad={() => setLoaded(true)} onError={() => {setLoaded(false);setSource(source === 'online' ? 'fallback' : 'failed');}}/>
        </div>}
      </div>
      <div className="dialog-footer"><span>{t.supportOptional}</span><Button onClick={() => onOpenChange(false)}>{t.continueUsing}</Button></div>
    </DialogContent>
  </Dialog>;
}
