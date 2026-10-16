#!/usr/bin/env python3
"""Temporary on-device cellular/Wi-Fi capture, bounded and passive.

Run in foreground under procd; default four hours and 8 MiB RAM log ring.
No AT commands, FIFO consumers, modem logging changes or connectivity probes.
"""
import argparse
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import time


class Ring:
    def __init__(self, directory, size=1024*1024, copies=8):
        self.directory, self.size, self.copies = directory, size, copies
        self.path = directory / 'events.log'
        self.file = self.path.open('ab', buffering=0)

    def write(self, source, message):
        line = ('%s %.3f %s %s\n' % (
            time.strftime('%Y-%m-%dT%H:%M:%S%z'), time.monotonic(),
            source, message.rstrip()[:32000])).encode(errors='replace')
        if self.file.tell() + len(line) > self.size:
            self.file.close()
            (self.directory / ('events.log.%d' % (self.copies-1))).unlink(missing_ok=True)
            for n in range(self.copies-2, 0, -1):
                p = self.directory / ('events.log.%d' % n)
                if p.exists(): p.replace(self.directory / ('events.log.%d' % (n+1)))
            self.path.replace(self.directory / 'events.log.1')
            self.file = self.path.open('ab', buffering=0)
        self.file.write(line)

    def close(self): self.file.close()


def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=2)
        return p.stdout[:40000] if p.returncode == 0 else {'error':p.stderr[:300], 'status':p.returncode}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'error':str(exc)}


def snapshot():
    result = {'uptime':Path('/proc/uptime').read_text().strip(),
              'load':Path('/proc/loadavg').read_text().strip()}
    result['links'] = command(['ip','-j','-s','link','show'])
    result['wan'] = command(['ubus','call','network.interface.wan','status'])
    result['wan6'] = command(['ubus','call','network.interface.wan_6','status'])
    result['clients'] = command(['ubus','call','hostapd.wlan0','get_clients'])
    # mmcli -K reads D-Bus properties; it does not send an AT command.
    modem = command(['mmcli','-m','0','-K'])
    if isinstance(modem, str):
        modem = '\n'.join(line for line in modem.splitlines() if re.match(
            r'\s*modem\.(generic\.(state|access-technologies|signal-quality)|'
            r'3gpp\.(registration-state|operator-code|operator-name))', line))
    result['modem'] = modem
    result['routes'] = command(['ip','route','show','table','all'])
    result['routes6'] = command(['ip','-6','route','show','table','all'])
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seconds', type=int, default=4*3600)
    ap.add_argument('--directory', type=Path, default=Path('/tmp/e5-field-capture'))
    ap.add_argument('--fault-directory', type=Path, default=Path('/root/e5-field-capture-fault'))
    a = ap.parse_args()
    if not 60 <= a.seconds <= 24*3600:
        ap.error('capture duration must be between one minute and 24 hours')
    a.directory.mkdir(exist_ok=False)
    ring = Ring(a.directory)
    selector = selectors.DefaultSelector()
    children, buffers, probes = [], {}, []
    stopping = False
    started = time.monotonic()
    deadline = started + a.seconds
    trace = Path('/sys/kernel/tracing')
    instance = trace / 'instances/e5_field_capture'
    mounted = False
    saved_fault = False
    counts = {}

    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    wake_read, wake_write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    previous_wakeup = signal.set_wakeup_fd(wake_write)
    selector.register(wake_read, selectors.EVENT_READ, 'stop')

    def register(fd, source):
        os.set_blocking(fd, False)
        selector.register(fd, selectors.EVENT_READ, source)
        buffers[fd] = b''

    def child(args, source):
        p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        children.append(p)
        register(p.stdout.fileno(), source)

    def probe_write(line):
        fd = os.open(trace/'kprobe_events', os.O_WRONLY|os.O_APPEND)
        try: os.write(fd, (line+'\n').encode())
        finally: os.close(fd)

    def status(state):
        data = {'state':state, 'pid':os.getpid(), 'elapsed_seconds':round(time.monotonic()-started),
                'remaining_seconds':max(0,round(deadline-time.monotonic())), 'events':counts,
                'log_limit_bytes':8*1024*1024, 'fault_saved':saved_fault,
                'profile':Path('/etc/e5/device-profile').read_text().strip()}
        (a.directory/'status.json').write_text(json.dumps(data,indent=2)+'\n')

    def save_fault(message):
        nonlocal saved_fault
        if saved_fault: return
        # One bounded disk save, only for a severe kernel/WCN fault, so an
        # unexpected reboot does not erase all evidence. Normal logs stay RAM.
        a.fault_directory.mkdir(exist_ok=True)
        shutil.copy2(ring.path, a.fault_directory/'events.log')
        (a.fault_directory/'trigger.txt').write_text(message+'\n')
        stacks = []
        for proc in Path('/proc').glob('[0-9]*'):
            try:
                name=(proc/'comm').read_text().strip()
                if name.startswith(('sdiohal','SC2355','irq/33')):
                    stacks.append(proc.name+' '+name+'\n'+(proc/'stack').read_text())
            except OSError: pass
        (a.fault_directory/'stacks.txt').write_text('\n'.join(stacks))
        saved_fault = True
        (a.fault_directory/'state.json').write_text(json.dumps(snapshot(),indent=2))

    kernel_keep = re.compile(r'(sprd-wlan|misc wlan|WCN|SDIO|mmc2|sipa|watchdog|lockup|Oops|panic)',re.I)
    kernel_event = re.compile(r'(timeout|assert|error|failed|fail:|disconnect|connected|station|'
                              r'ctx_id:.*action:|hif->exit|watchdog|lockup|Oops|panic|FW_ERROR|reset|CMD_POWER_SAVE)',re.I)
    severe = re.compile(r'(CMD_.*timeout|fw assert|hif->exit|NETDEV WATCHDOG|soft lockup|Oops|Kernel panic)',re.I)
    syslog_keep = re.compile(r'(modem|ModemManager|netifd|hostapd|odhcp6c|sc2355-recovery|sipa)',re.I)
    try:
        ring.write('start', json.dumps({'kernel':os.uname().release, 'seconds':a.seconds}))
        (a.directory/'initial.json').write_text(json.dumps(snapshot(),indent=2))
        kmsg=os.open('/dev/kmsg',os.O_RDONLY|os.O_NONBLOCK)
        os.lseek(kmsg,0,os.SEEK_END)
        register(kmsg,'kernel')
        # logread's regex dialect differs across builds. Filter here so an
        # unsupported alternation cannot silently discard all daemon events.
        child(['logread','-f','-Z','0'], 'syslog')
        child(['ip','-ts','monitor','link','address','route'],'network')
        # Observe registration and bearer changes without competing for the
        # mobility FIFO or changing modem verbosity/AT polling rates.
        matches=["type='signal',interface='org.freedesktop.DBus.Properties',member='PropertiesChanged',"
                 "path_namespace='/org/freedesktop/ModemManager1',arg0='%s'" % interface
                 for interface in ('org.freedesktop.ModemManager1.Modem',
                                   'org.freedesktop.ModemManager1.Modem.Modem3gpp',
                                   'org.freedesktop.ModemManager1.Bearer')]
        child(['dbus-monitor','--system',*matches],'modem')
        try:
            if not (trace/'kprobe_events').exists():
                subprocess.run(['mount','-t','tracefs','tracefs',str(trace)],check=True)
                mounted=True
            instance.mkdir()
            (instance/'buffer_size_kb').write_text('32')
            for name, spec in {
                'e5_field_sta':'p:e5_field_sta sprd_report_softap connected=$arg2:u8 ie_len=$arg5:u16',
                'e5_field_deauth':'p:e5_field_deauth sprd_report_mgmt_deauth len=$arg3:u16 fc=+0($arg2):x16 reason=+24($arg2):u16',
                'e5_field_disassoc':'p:e5_field_disassoc sprd_report_mgmt_disassoc len=$arg3:u16 fc=+0($arg2):x16 reason=+24($arg2):u16',
                'e5_field_lut':'p:e5_field_lut sc2355_event_sta_lut ctx=+0($arg2):u8 action=+1($arg2):u8 lut=+2($arg2):u8',
                'e5_field_assert':'p:e5_field_assert sc2355_assert_cmd cmd=$arg2:u8 reason=$arg3:u8',
            }.items():
                probe_write(spec); probes.append(name)
                (instance/'events/kprobes'/name/'enable').write_text('1')
            (instance/'tracing_on').write_text('1')
            register(os.open(instance/'trace_pipe',os.O_RDONLY|os.O_NONBLOCK),'wifi-event')
        except (OSError,subprocess.CalledProcessError) as exc:
            ring.write('diagnostic', 'optional Wi-Fi tracing unavailable: '+str(exc))
        status('running')
        print('Ready: passive field capture, 4-hour default, 8 MiB RAM ring.',flush=True)
        next_snapshot=time.monotonic()+60
        while not stopping and time.monotonic()<deadline:
            timeout=max(0,min(deadline,next_snapshot)-time.monotonic())
            for key,_ in selector.select(timeout):
                try: data=os.read(key.fd,65536)
                except BlockingIOError: continue
                except OSError as exc:
                    if key.data=='kernel' and exc.errno==32:
                        ring.write('diagnostic','kernel ring overrun');continue
                    selector.unregister(key.fd);continue
                if not data:
                    selector.unregister(key.fd)
                    ring.write('diagnostic',key.data+' event stream closed')
                    continue
                if key.data == 'stop': continue
                if key.data=='kernel':
                    chunks=data.splitlines()
                    # kmsg records carry a sequence/timestamp prefix. Preserve
                    # it to correlate events even if wall clock is corrected.
                else:
                    chunks=(buffers[key.fd]+data).split(b'\n')
                    buffers[key.fd]=chunks.pop()
                for chunk in chunks:
                    line=chunk.decode(errors='replace')
                    if not line: continue
                    if key.data=='kernel' and not (kernel_keep.search(line) and kernel_event.search(line)):
                        continue
                    if key.data=='syslog' and not syslog_keep.search(line): continue
                    ring.write(key.data,line)
                    counts[key.data]=counts.get(key.data,0)+1
                    if key.data=='kernel' and severe.search(line): save_fault(line)
            if time.monotonic()>=next_snapshot:
                ring.write('snapshot',json.dumps(snapshot(),separators=(',',':')))
                next_snapshot=time.monotonic()+60
                status('running')
        status('stopped')
    finally:
        ring.write('stop','capture ending; cleaning temporary observers')
        for p in children:
            if p.poll() is None: p.terminate()
        for p in children:
            try:p.wait(timeout=2)
            except subprocess.TimeoutExpired:p.kill();p.wait()
        for key in list(selector.get_map().values()):
            selector.unregister(key.fd)
            if key.data in ('kernel','wifi-event','stop'):os.close(key.fd)
        signal.set_wakeup_fd(previous_wakeup)
        os.close(wake_write)
        selector.close()
        if instance.exists():
            (instance/'tracing_on').write_text('0')
            for name in probes:(instance/'events/kprobes'/name/'enable').write_text('0')
            instance.rmdir()
        for name in probes:probe_write('-:'+name)
        if mounted:subprocess.run(['umount',str(trace)],check=True)
        ring.close()


if __name__=='__main__': main()
