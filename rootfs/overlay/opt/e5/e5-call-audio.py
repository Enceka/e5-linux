#!/usr/bin/python3
"""E5 hostless CP voice audio, implementing libcallaudio's session-bus API.

The card has no ACP ports (probing every vendor FE is not safe/useful). Voice
uses the DSP's FE_ST_VOICE, not a PipeWire client stream. Keep playback/capture
prepared and started for the call, and restore the exact mixer state afterwards.
This service never controls the modem, creates calls, answers or hangs up.
"""
import concurrent.futures
import ctypes as C
import fcntl
import logging
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import sys
import threading

NAME = 'org.mobian_project.CallAudio'
OBJECT = '/org/mobian_project/CallAudio'
XML = '''<node><interface name="org.mobian_project.CallAudio">
<method name="SelectMode"><arg type="u" direction="in"/><arg type="b" direction="out"/></method>
<method name="EnableSpeaker"><arg type="b" direction="in"/><arg type="b" direction="out"/></method>
<method name="MuteMic"><arg type="b" direction="in"/><arg type="b" direction="out"/></method>
<property name="AudioMode" type="u" access="read"/>
<property name="SpeakerState" type="u" access="read"/>
<property name="MicState" type="u" access="read"/>
</interface></node>'''


class VoicePcm:
    """A hostless PCM: no AP audio is copied into the CP voice stream."""
    def __init__(self, card, device, direction):
        self.lib = C.CDLL('libasound.so.2')
        self.handle = C.c_void_p()
        pointer = C.c_void_p
        specs = {
            'open': [C.POINTER(pointer), C.c_char_p, C.c_int, C.c_int],
            'close': [pointer], 'prepare': [pointer], 'start': [pointer],
            'hw_params_malloc': [C.POINTER(pointer)],
            'hw_params_any': [pointer, pointer],
            'hw_params_set_access': [pointer, pointer, C.c_int],
            'hw_params_set_format': [pointer, pointer, C.c_int],
            'hw_params_set_channels': [pointer, pointer, C.c_uint],
            'hw_params_set_rate': [pointer, pointer, C.c_uint, C.c_int],
            'hw_params_set_period_size_near': [pointer, pointer, C.POINTER(C.c_ulong), C.POINTER(C.c_int)],
            'hw_params_set_buffer_size_near': [pointer, pointer, C.POINTER(C.c_ulong)],
            'hw_params': [pointer, pointer],
        }
        for name, args in specs.items():
            func = getattr(self.lib, 'snd_pcm_' + name)
            func.argtypes, func.restype = args, C.c_int
        self.lib.snd_pcm_forward.argtypes = [pointer, C.c_ulong]
        self.lib.snd_pcm_forward.restype = C.c_long
        self.lib.snd_pcm_hw_params_free.argtypes = [pointer]
        self.lib.snd_pcm_hw_params_free.restype = None
        self.lib.snd_strerror.argtypes = [C.c_int]
        self.lib.snd_strerror.restype = C.c_char_p
        params = pointer()
        try:
            self.check(self.lib.snd_pcm_open(C.byref(self.handle),
                       f'hw:{card},{device}'.encode(), direction, 1), 'open')
            self.check(self.lib.snd_pcm_hw_params_malloc(C.byref(params)), 'allocate parameters')
            for name, args in [('any', ()), ('set_access', (3,)), ('set_format', (2,)),
                               ('set_channels', (1,)), ('set_rate', (8000, 0))]:
                self.check(getattr(self.lib, 'snd_pcm_hw_params_' + name)(self.handle, params, *args), name)
            period, buffer, rounding = C.c_ulong(640), C.c_ulong(1280), C.c_int(0)
            self.check(self.lib.snd_pcm_hw_params_set_period_size_near(self.handle, params, C.byref(period), C.byref(rounding)), 'period')
            self.check(self.lib.snd_pcm_hw_params_set_buffer_size_near(self.handle, params, C.byref(buffer)), 'buffer')
            self.check(self.lib.snd_pcm_hw_params(self.handle, params), 'hw_params')
            self.check(self.lib.snd_pcm_prepare(self.handle), 'prepare')
            # ALSA refuses an empty playback start. Advance its application
            # pointer without writing samples: FE_ST_VOICE has no AP DMA.
            if direction == 0:
                moved = self.lib.snd_pcm_forward(self.handle, buffer.value)
                self.check(moved, 'hostless forward')
                if not moved:
                    raise RuntimeError('hostless playback pointer did not advance')
        except Exception:
            self.close()
            raise
        finally:
            if params:
                self.lib.snd_pcm_hw_params_free(params)

    def check(self, result, operation):
        if result < 0:
            raise RuntimeError(f'{operation}: {self.lib.snd_strerror(result).decode()}')

    def start(self):
        self.check(self.lib.snd_pcm_start(self.handle), 'start')

    def close(self):
        if self.handle:
            self.lib.snd_pcm_close(self.handle)
            self.handle = C.c_void_p()


class VoiceHardware:
    # Handsfree gains and codec routes from this device's Android parameters.
    ROUTES = {
        'S_VOICE_P_CODEC SWITCH': 'on', 'S_VOICE_C_CODEC SWITCH': 'on',
        'VBC_MUX_DAC1_IIS_PORT_SEL': 'VBC_IIS_PORT_IIS0',
        # Android's only_codec_p route uses DAC0 here, including voice.
        'VBC_MUX_IIS0_PORT_DO_SEL': 'IIS_DO_VAL_DAC0',
        'VBC_MUX_ADC2': 'ADC_IN_IIS1_ADC',
        'VBC_MUX_ADC2_IIS_PORT_SEL': 'VBC_IIS_PORT_IIS1',
        'VBC DAC1 DG Set': '24,24', 'VBC DAC1 DSP MDG Set': '1,1024',
        # Android forces DL mute during route changes and explicitly releases
        # it after startup. A cached "disable" does not prove DSP is unmuted.
        'VBC_DL_MUTE': 'enable',
        'VBC ADC2 DG Set': '24,24',
        # The HAL sets this to voice_volume + 1, after applying AS/CVS.
        'VBC_VOLUME': '7',
        # Own Android Handsfree/NB1, volume 7: dacs=0, ao=3.
        'DAC Gain DAC Playback Volume': '0', 'AO Gain AO Playback Volume': '3',
        'Speaker Function': 'on', 'Speaker Mute': 'off',
        'Earpiece Function': 'off', 'Mic Function': 'on',
        'AOL EAR Sel': 'AOL', 'AO Mixer AOL Switch': 'on',
        'AO Mixer AOR Switch': 'on', 'DA AOR Switch': 'on',
    }
    # The E5 driver's CVS selector retains the old NXP label (same profile 2).
    PROFILES = ('DSP VBC Profile Select', 'Audio Structure Profile Select', 'NXP Profile Select')

    def __init__(self):
        pcm = Path('/proc/asound/pcm').read_text()
        match = re.search(r'^(\d+)-(\d+): FE_ST_VOICE ', pcm, re.M)
        if not match:
            raise RuntimeError('no FE_ST_VOICE PCM')
        self.card, self.device = map(int, match.groups())
        if 'sprdphone-sc2730' not in Path('/proc/asound/cards').read_text():
            raise RuntimeError('not an E5 sound card')
        self.saved, self.handles = {}, []
        self.band = 0

    @staticmethod
    def profile_word(band):
        # Handsfree NB1/WB1/SWB1/FB1. Param ID equals the mode's logical ID;
        # the low byte is DAI_ID_VOICE=5, as in the Unisoc HAL.
        mode = (7, 9, 11, 12)[band]
        return (mode << 24) | (mode << 16) | 5

    def profiles(self):
        word = self.profile_word(getattr(self, 'band', 0))
        for name in self.PROFILES:
            self.put(name, word)
        self.put('VBC_VOLUME', 7)
        logging.info('voice profiles=%#x, bandwidth=%d, VBC_VOLUME=7', word, getattr(self, 'band', 0))

    def unmute_downlink(self):
        self.put('VBC DAC1 DSP MDG Set', '0,1024')
        self.put('VBC_DL_MUTE', 'disable')
        logging.info('voice downlink unmuted after PCM startup/parameters')

    def network(self, net, band):
        if band not in (0, 1, 2, 3):
            logging.warning('unsupported DSP voice bandwidth %s', band)
            return
        self.band = band
        logging.info('DSP network message net=%#x, bandwidth=%d', net, band)
        if self.handles:
            self.profiles()
            self.unmute_downlink()

    def get(self, name):
        text = subprocess.check_output(['amixer', '-c', str(self.card), 'cget', 'name=' + name], text=True)
        match = re.search(r': values=(.+)', text)
        if not match:
            raise RuntimeError('cannot read mixer ' + name)
        return match.group(1).strip()

    def put(self, name, value):
        # VBC_VOLUME declares UINT_MAX as a signed max (-1); amixer clamps any
        # positive value to -1. Profile selects also have understated maxima.
        if name in self.PROFILES or name == 'VBC_VOLUME':
            command = ['/opt/e5/e5-ctl-raw', name, str(value), str(self.card)]
        else:
            command = ['amixer', '-q', '-c', str(self.card), 'cset', 'name=' + name, str(value)]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)

    def start(self):
        if self.handles:
            return
        # Read the full snapshot before changing even the first route.
        self.saved = {name: self.get(name) for name in (*self.ROUTES, *self.PROFILES)}
        try:
            self.profiles()
            for name, value in self.ROUTES.items():
                self.put(name, value)
            for direction in (0, 1):
                self.handles.append(VoicePcm(self.card, self.device, direction))
            # Android prepares both directions before starting either one.
            for pcm in self.handles:
                pcm.start()
            # The vendor applies the parameters again after starting both PCMs.
            self.profiles()
            self.unmute_downlink()
            logging.info('VOICE-RUNNING hw:%s,%s playback/capture, speaker, 8000 Hz', self.card, self.device)
        except Exception:
            self.stop()
            raise

    def stop(self):
        for pcm in reversed(self.handles):
            pcm.close()
        self.handles.clear()
        errors = []
        for name, value in reversed(tuple(self.saved.items())):
            try:
                self.put(name, value)
            except Exception as error:
                errors.append(str(error))
        self.saved.clear()
        if errors:
            raise RuntimeError('; '.join(errors))
        logging.info('VOICE-STOPPED; prior mixer/profile state restored')

    def mute(self, mute):
        if self.handles:
            self.put('VBC ADC2 DG Set', '0,0' if mute else '24,24')


def main():
    import gi
    gi.require_version('Gio', '2.0')
    from gi.repository import Gio, GLib
    logging.basicConfig(level=logging.INFO, format='%(asctime)s e5-call-audio: %(message)s')
    hardware = VoiceHardware()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    loop = GLib.MainLoop()
    states = {'AudioMode': 0, 'SpeakerState': 1, 'MicState': 1}
    connection = None
    pipe_fd = None
    pipe_stop = threading.Event()

    def voice_notifications():
        nonlocal pipe_fd
        try:
            pipe_fd = os.open('/dev/audio_pipe_voice', os.O_RDWR)
            logging.info('DSP voice notification channel opened')
            while not pipe_stop.is_set():
                try:
                    data = os.read(pipe_fd, 20)
                except OSError:
                    if pipe_stop.is_set():
                        break
                    raise
                if pipe_stop.is_set():
                    break
                if len(data) != 20:
                    raise RuntimeError('short DSP notification')
                command, channel, p0, p1, p2, p3 = struct.unpack('<HH4I', data)
                logging.info('DSP notification cmd=%#x channel=%d params=%#x,%#x,%#x,%#x', command, channel, p0, p1, p2, p3)
                if command == 0 and channel == 2:
                    executor.submit(hardware.network, p0, p1)
                elif command == 0x35 and channel == 2:
                    # Stock HAL logs this as "cp voice enable", not bandwidth.
                    logging.info('CP voice enabled=%s (mask=%#x)', bool(p0), p0)
        except Exception:
            if not pipe_stop.is_set():
                logging.exception('DSP voice notification listener failed')
        finally:
            if pipe_fd is not None:
                os.close(pipe_fd)
                pipe_fd = None

    pipe_thread = threading.Thread(target=voice_notifications, daemon=True)
    pipe_thread.start()

    def properties():
        return {name: GLib.Variant('u', value) for name, value in states.items()}

    def finish(invocation, future):
        try:
            future.result()
            success = True
        except Exception:
            logging.exception('audio operation failed')
            success = False
        if connection:
            connection.emit_signal(None, OBJECT, 'org.freedesktop.DBus.Properties',
                                   'PropertiesChanged', GLib.Variant('(sa{sv}as)', (NAME, properties(), [])))
        invocation.return_value(GLib.Variant('(b)', (success,)))
        return False

    def operation(method, value):
        if method == 'SelectMode':
            if value:
                hardware.start()
            else:
                hardware.stop()
            states['AudioMode'] = int(value)
            states['MicState'] = 1
        elif method == 'EnableSpeaker':
            # The receiver was silent in prior tests. Keep the validated speaker
            # as the call output until an earpiece route is separately verified.
            if not value:
                raise RuntimeError('E5 call output currently supports speaker only')
            states['SpeakerState'] = 1
        else:
            hardware.mute(value)
            states['MicState'] = 0 if value else 1

    def method_call(bus, sender, path, interface, method, parameters, invocation):
        value = parameters.unpack()[0]
        if method == 'SelectMode' and value not in (0, 1):
            invocation.return_dbus_error('org.freedesktop.DBus.Error.InvalidArgs', 'mode must be 0 or 1')
            return
        logging.info('%s(%s)', method, value)
        future = executor.submit(operation, method, value)
        future.add_done_callback(lambda result: GLib.idle_add(finish, invocation, result))

    def acquired(bus, name):
        nonlocal connection
        connection = bus
        info = Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]
        bus.register_object(OBJECT, info, method_call,
                            lambda b, s, p, i, name: GLib.Variant('u', states[name]), None)

    def shutdown(*args):
        pipe_stop.set()
        if pipe_fd is not None:
            # AUDIO_PIPE_WAKEUP releases the driver's blocking receive.
            try:
                fcntl.ioctl(pipe_fd, 0x40044100, struct.pack('i', 1))
            except OSError:
                pass
        future = executor.submit(hardware.stop)
        future.add_done_callback(lambda result: GLib.idle_add(loop.quit))
        return False

    Gio.bus_own_name(Gio.BusType.SESSION, NAME, Gio.BusNameOwnerFlags.NONE,
                     acquired, None, lambda *args: shutdown())
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, shutdown)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, shutdown)
    try:
        loop.run()
    finally:
        pipe_stop.set()
        pipe_thread.join(timeout=2)
        executor.shutdown(wait=True)
        hardware.stop()


if __name__ == '__main__':
    main()
