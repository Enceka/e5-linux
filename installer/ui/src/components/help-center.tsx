import {useEffect, useMemo, useRef, useState} from 'react';
import Markdown from 'react-markdown';
import {AnimatePresence, m, useReducedMotion} from 'motion/react';
import {ArrowRight, BookOpen, Check, Search, ShieldCheck, Usb} from 'lucide-react';
import {Button} from './ui/button';
import {Dialog, DialogContent, DialogDescription, DialogTitle} from './ui/dialog';
import {helpTopics} from '../help-data';
import {helpStrings} from '../help-i18n';
import type {Language} from '../i18n';

export function HelpCenter({language, open, onOpenChange, initialTopic, onGuide}:
  {language:Language; open:boolean; onOpenChange:(open:boolean)=>void; initialTopic:string; onGuide:()=>void}) {
  const t = helpStrings[language];
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState(initialTopic);
  const content = useRef<HTMLElement>(null);
  const topics = useMemo(() => helpTopics(language), [language]);
  const filtered = topics.filter(topic => `${topic.title}\n${topic.markdown}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const active = filtered.find(topic => topic.id === selected) || filtered[0];
  useEffect(() => {if (open) {setSelected(initialTopic); setSearch('');}}, [open, initialTopic]);
  useEffect(() => {content.current?.scrollTo({top:0});}, [active?.id, language]);
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent closeLabel={t.close} className="help-dialog">
      <div className="dialog-heading"><div className="eyebrow">OPENWRT · HELP</div><DialogTitle>{t.help}</DialogTitle><DialogDescription>{t.helpIntro}</DialogDescription></div>
      <div className="help-search"><Search size={17} aria-hidden="true"/><input aria-label={t.search} placeholder={t.searchPlaceholder} value={search} onChange={e => setSearch(e.target.value)}/><span aria-live="polite">{filtered.length} {t.results}</span></div>
      <div className="help-layout"><nav className="help-topics scroll-area" aria-label={t.topics}>
        {filtered.map(topic => <button key={topic.id} aria-current={active?.id === topic.id ? 'page' : undefined} onClick={() => setSelected(topic.id)}>{topic.title}</button>)}
      </nav><article ref={content} className="help-article scroll-area" tabIndex={0} aria-label={active?.title || t.noResults}>
        {active ? <><h2>{active.title}</h2><div className="help-markdown"><Markdown skipHtml components={{a:({children,href}) => <span className="help-address" title={href}>{children}</span>}}>{active.markdown}</Markdown></div></> : <p className="empty-state">{t.noResults}</p>}
      </article></div>
      <div className="dialog-footer"><Button variant="outline" onClick={onGuide}><BookOpen size={16}/>{t.replay}</Button><Button variant="ghost" onClick={() => onOpenChange(false)}>{t.close}</Button></div>
    </DialogContent>
  </Dialog>;
}

export function GettingStarted({language, open, onOpenChange}:
  {language:Language; open:boolean; onOpenChange:(open:boolean)=>void}) {
  const t = helpStrings[language];
  const [step, setStep] = useState(0);
  const reduceMotion = useReducedMotion();
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {if (open) setStep(0);}, [open]);
  useEffect(() => {body.current?.scrollTo({top:0});}, [step]);
  const Icon = [Usb, ShieldCheck, BookOpen][step];
  return <Dialog open={open} onOpenChange={onOpenChange}>
    <DialogContent closeLabel={t.closeGuide} className="onboarding-dialog">
      <div className="dialog-heading"><div className="eyebrow">OPENWRT · {t.guide}</div><DialogTitle>{t.guide}</DialogTitle><DialogDescription>{t.guideIntro}</DialogDescription></div>
      <ol className="guide-steps" aria-label={t.guide}>{t.introTitles.map((title,i) => <li key={title} aria-current={step === i ? 'step' : undefined} className={i <= step ? 'reached' : ''}><span>{i < step ? <Check size={13}/> : i+1}</span><div>{title}</div></li>)}</ol>
      <div className="onboarding-body scroll-area" ref={body}>
        <AnimatePresence mode="wait" initial={false}><m.div key={step} initial={{opacity:reduceMotion ? 1 : 0,x:reduceMotion ? 0 : 6}} animate={{opacity:1,x:0}} exit={{opacity:0}} transition={{duration:reduceMotion ? 0 : .14}}>
          <div className="guide-title"><Icon size={25} aria-hidden="true"/><h2>{t.introTitles[step]}</h2></div>
          <ul>{t.introBodies[step].map(paragraph => <li key={paragraph}>{paragraph}</li>)}</ul>
        </m.div></AnimatePresence>
        <p className="guide-no-action"><ShieldCheck size={16}/>{t.noAction}</p>
      </div>
      <div className="dialog-footer"><Button variant="ghost" onClick={() => onOpenChange(false)}>{t.skip}</Button><span className="guide-count">{t.step} {step+1} {t.of}</span><div className="guide-controls">{step > 0 && <Button variant="outline" onClick={() => setStep(step-1)}>{t.back}</Button>}<Button onClick={() => step < 2 ? setStep(step+1) : onOpenChange(false)}>{step < 2 ? t.next : t.finish}<ArrowRight size={16}/></Button></div></div>
    </DialogContent>
  </Dialog>;
}
