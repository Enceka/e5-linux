#!/usr/bin/env python3
"""Test the OpenWrt audio lifecycle with fake ALSA, never a modem."""
import importlib.machinery
import importlib.util
from pathlib import Path
source = Path(__file__).resolve().parents[1] / 'overlay/usr/libexec/e5-voice-audio'
loader = importlib.machinery.SourceFileLoader('openwrt_voice', str(source))
spec = importlib.util.spec_from_loader(loader.name, loader)
voice = importlib.util.module_from_spec(spec)
loader.exec_module(voice)
class Hardware:
    def __init__(self): self.speaker = False; self.events = []
    def start(self): self.events.append('start')
    def stop(self): self.events.append('stop'); self.speaker = False
    def set_speaker(self, value): self.speaker = value
    def mute(self, value): self.events.append(('mute', value))
hw=Hardware(); suspends=[]; c=voice.Controller(hw,suspends.append)
assert not c.update([{'id':'0','state':'--'}],{})['active']
assert not hw.events and not suspends
assert c.update([{'id':'1','state':'dialing'}],{})['active']
assert suspends==[True] and hw.events==['start']
# No timer expires or ends an active call; only observed modem state controls audio.
for _ in range(100): assert c.update([{'id':'1','state':'active'}],{})['active']
assert hw.events==['start']
r=c.update([{'id':'1','state':'active'}],{'speaker':True,'muted':True})
assert r['speaker'] and r['muted']
assert ('mute', True) in hw.events
assert not c.update([{'id':'1','state':'terminated'}],{})['active']
assert hw.events[-1]=='stop' and suspends==[True,False]
class Fails(Hardware):
    def start(self): raise RuntimeError('PCM not available')
f=voice.Controller(Fails(),suspends.append)
r=f.update([{'id':'2','state':'active'}],{})
assert not r['active'] and r['error']=='PCM not available'
# The watcher has no API or CLI branch for starting, answering or ending calls.
text=source.read_text()
for forbidden in ('--start','--accept','--hangup','--voice-create-call','--voice-delete-call'):
    assert forbidden not in text
print('OpenWrt voice audio checks passed')
# Notification lifecycle: incoming rings alert, answering stops owned alerts;
# an already-active call only vibrates for a waiting call.
from unittest.mock import patch
class AlertProcess:
    pid = 987654
    def poll(self): return None
spawned=[]; now=[0]
def spawn(argv): spawned.append(argv); return AlertProcess()
ringer=voice.RingAlert(spawn,lambda:now[0])
with patch.object(voice.os,'killpg') as kill:
    ringer.update([{'id':'3','state':'ringing-in'}],{'sound':True,'vibrate':True,'tone':'call'},False)
    assert spawned[0][0]=='paplay' and spawned[1][0]=='e5-vibrate'
    ringer.update([{'id':'3','state':'active'}],{'sound':True,'vibrate':True},True)
    assert kill.call_count==2 and not ringer.call_ids
    spawned.clear();now[0]=3
    ringer.update([{'id':'4','state':'waiting'}],{'sound':True,'vibrate':True},True)
    assert len(spawned)==1 and spawned[0][0]=='e5-vibrate'
    ringer.update([],{'sound':False,'vibrate':False},False)
assert not voice.Controller(Hardware(),suspends.append).update([{'id':'5','state':'ringing-in'}],{})['active']
print('Incoming ringtone/vibration checks passed')
