#!/usr/bin/env python3
"""Check voice setup/rollback without hardware or a modem."""
import importlib.util
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'overlay/opt/e5/e5-call-audio.py'
spec=importlib.util.spec_from_file_location('voice_backend',p)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
class Hardware(module.VoiceHardware):
    def __init__(self):
        self.values={name:'before-'+name for name in (*self.ROUTES,*self.PROFILES)}
        self.original=dict(self.values)
        self.events=[]
        self.saved={}; self.handles=[]; self.card=0; self.device=5
    def get(self,name):return self.values[name]
    def put(self,name,value):self.values[name]=value; self.events.append(('put',name,value))
class Pcm:
    opened=[]
    def __init__(self,card,device,stream):
        self.closed=False; self.stream=stream; self.opened.append(self)
        hardware.events.append(('prepare',stream))
    def start(self):hardware.events.append(('start',self.stream))
    def close(self):self.closed=True
module.VoicePcm=Pcm
hardware=Hardware()
hardware.start()
assert len(hardware.handles)==2
assert hardware.values['VBC_VOLUME']==7
assert hardware.values['NXP Profile Select']==0x07070005
assert hardware.values['VBC_DL_MUTE']=='disable'
assert hardware.values['VBC DAC1 DSP MDG Set']=='0,1024'
assert hardware.events.index(('prepare',1)) < hardware.events.index(('start',0))
assert hardware.events.index(('start',1)) < hardware.events.index(('put','VBC_DL_MUTE','disable'))
hardware.network(0x10,1)
assert hardware.values['NXP Profile Select']==0x09090005
hardware.start()
assert len(hardware.handles)==2
hardware.mute(True)
assert hardware.values['VBC ADC2 DG Set']=='0,0'
hardware.mute(False)
hardware.stop()
assert hardware.values==hardware.original
assert all(pcm.closed for pcm in Pcm.opened)
class FailingPcm(Pcm):
    def __init__(self,card,device,stream):
        if stream==1:raise RuntimeError('capture setup failed')
        super().__init__(card,device,stream)
module.VoicePcm=FailingPcm
hardware=Hardware()
try:hardware.start()
except RuntimeError:pass
else:raise AssertionError('failure was hidden')
assert hardware.values==hardware.original
assert not hardware.handles
class FailingStartPcm(Pcm):
    def start(self):
        super().start()
        if self.stream==1:raise RuntimeError('capture start failed')
module.VoicePcm=FailingStartPcm
hardware=Hardware()
try:hardware.start()
except RuntimeError:pass
else:raise AssertionError('start failure was hidden')
assert hardware.values==hardware.original
assert not hardware.handles
assert ('put','VBC_DL_MUTE','disable') not in hardware.events
print('Voice state checks passed')
