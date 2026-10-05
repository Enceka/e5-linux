"""SMS-DELIVER decoding (3GPP TS 23.038/23.040), without third-party modules."""
from datetime import datetime, timedelta, timezone
import hashlib
import math
import re

GSM7 = ('@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ'
        ' !"#¤%&\'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§'
        '¿abcdefghijklmnopqrstuvwxyzäöñüà')
EXT = {10: '\f', 20: '^', 40: '{', 41: '}', 47: '\\', 60: '[', 61: '~', 62: ']', 64: '|', 101: '€'}


def septets(data, count, offset=0):
    if offset + count * 7 > len(data) * 8:
        raise ValueError('truncated GSM7 user data')
    value = int.from_bytes(data, 'little')
    result, escape = [], False
    for i in range(count):
        code = (value >> (offset + i * 7)) & 127
        if escape:
            result.append(EXT.get(code, '\ufffd')); escape = False
        elif code == 27:
            escape = True
        else:
            result.append(GSM7[code])
    if escape:
        result.append('\ufffd')
    return ''.join(result)


def decode(pdu):
    data = bytes.fromhex(pdu)
    if not data:
        raise ValueError('empty SMS PDU')
    pos = 1 + data[0]

    def take(size):
        nonlocal pos
        if pos + size > len(data):
            raise ValueError('truncated SMS PDU')
        result = data[pos:pos + size]; pos += size
        return result

    flags = take(1)[0]
    if flags & 3 != 0:
        return None  # submit/status-report are handled by ModemManager
    size, toa = take(2)
    address = take((size + 1) // 2)
    if toa & 0x70 == 0x50:
        number = septets(address, size * 4 // 7)
    else:
        digits = ''.join(f'{byte & 15:X}{byte >> 4:X}' for byte in address)[:size]
        number = ('+' if toa & 0x70 == 0x10 else '') + digits
    pid, dcs = take(2)
    scts = take(7)
    semi = lambda b: (b & 15) * 10 + (b >> 4)
    values = [semi(b) for b in scts[:6]]
    tz = semi(scts[6] & 0xf7) * 15 * (-1 if scts[6] & 8 else 1)
    dt = datetime(2000 + values[0], *values[1:], tzinfo=timezone(timedelta(minutes=tz)))
    udl = take(1)[0]
    if dcs & 0xc0 == 0:
        if dcs & 0x20:
            raise ValueError('compressed SMS is unsupported')
        alphabet = (dcs >> 2) & 3
    elif dcs & 0xf0 in (0xc0, 0xd0, 0xe0):
        alphabet = 2 if dcs & 0xf0 == 0xe0 else 0
    elif dcs & 0xf0 == 0xf0:
        alphabet = 1 if dcs & 4 else 0
    else:
        raise ValueError('unsupported SMS alphabet')
    user = take(math.ceil(udl * 7 / 8) if alphabet == 0 else udl)
    header_bytes, concat = 0, None
    if flags & 0x40:
        if not user:
            raise ValueError('missing SMS header')
        header_bytes = user[0] + 1
        if header_bytes > len(user):
            raise ValueError('truncated SMS header')
        at = 1
        while at < header_bytes:
            if at + 2 > header_bytes:
                raise ValueError('invalid SMS header element')
            tag, length = user[at:at + 2]; at += 2
            item = user[at:at + length]; at += length
            if at > header_bytes:
                raise ValueError('invalid SMS header length')
            if tag == 0 and length == 3:
                concat = {'ref': item[0], 'total': item[1], 'part': item[2]}
            elif tag == 8 and length == 4:
                concat = {'ref': int.from_bytes(item[:2], 'big'), 'total': item[2], 'part': item[3]}
            elif tag in (0x24, 0x25) and any(item):
                raise ValueError('SMS national language shift table unsupported')
        if concat and not 1 <= concat['part'] <= concat['total'] <= 255:
            raise ValueError('invalid concatenated SMS numbering')
    if alphabet == 0:
        header_septets = math.ceil(header_bytes * 8 / 7)
        text = septets(user, udl - header_septets, header_septets * 7)
    elif alphabet == 2:
        text = user[header_bytes:].decode('utf-16-be', errors='replace')
    elif alphabet == 1:
        text = user[header_bytes:].decode('latin1')
    else:
        raise ValueError('reserved SMS alphabet')
    return {'number': number, 'text': text, 'time': dt.isoformat(timespec='seconds'),
            'epoch': int(dt.timestamp()), 'concat': concat, 'dcs': dcs,
            'fingerprint': hashlib.sha256(data).hexdigest()}


def listing(response):
    parts, errors, header = [], [], None
    for line in response.splitlines():
        line = line.strip()
        match = re.match(r'\+CMGL:\s*(\d+)\s*,\s*(\d+)\s*,', line)
        if match:
            header = {'storage_index': int(match[1]), 'storage_status': int(match[2])}
        elif header and re.fullmatch(r'[a-fA-F0-9]+', line):
            try:
                sms = decode(line)
                if sms:
                    parts.append({**sms, **header})
            except (ValueError, IndexError) as error:
                errors.append({'storage_index': header['storage_index'], 'error': str(error)})
            header = None
    if header:
        errors.append({'storage_index': header['storage_index'], 'error': 'missing SMS PDU'})
    return parts, errors


def assemble(parts):
    groups = []
    for part in sorted(parts, key=lambda p: (p['epoch'], p['storage_index'])):
        c = part['concat']
        group = None
        if c:
            for old in reversed(groups):
                ref = old[0]['concat']
                if (ref and old[0]['number'] == part['number'] and old[0]['dcs'] == part['dcs']
                        and ref['ref'] == c['ref'] and ref['total'] == c['total']
                        and abs(old[0]['epoch'] - part['epoch']) < 600
                        and all(p['concat']['part'] != c['part'] for p in old)):
                    group = old; break
        if group is None:
            group = []; groups.append(group)
        group.append(part)
    result = []
    for group in groups:
        c = group[0]['concat']; ordered = sorted(group, key=lambda p: p['concat']['part'] if c else 1)
        complete = not c or len(ordered) == c['total']
        first = min(group, key=lambda p: p['epoch'])
        result.append({'number': first['number'], 'time': first['time'], 'epoch': first['epoch'],
                       'text': ''.join(p['text'] for p in ordered), 'state': 'received' if complete else 'receiving',
                       'parts': [{'index': p['storage_index'], 'fingerprint': p['fingerprint']} for p in ordered],
                       'concat': c, 'total_parts': c['total'] if c else 1})
    return result


def submit(number, text, reference=None):
    """SMS-SUBMIT PDUs, GSM7 including extensions or UTF-16 with 16-bit UDH."""
    import secrets
    number = re.sub(r'[ -]', '', number)
    if not re.fullmatch(r'\+?[0-9]{3,20}', number):
        raise ValueError('Invalid recipient number')
    if not text or len(text.encode('utf-8')) > 4000:
        raise ValueError('Message is empty or exceeds 4000 UTF-8 bytes')
    digits = number.lstrip('+')
    semi = digits + ('F' if len(digits) % 2 else '')
    address = bytes(int(semi[i + 1] + semi[i], 16) for i in range(0, len(semi), 2))
    gsm = {char: [i] for i, char in enumerate(GSM7) if i != 27}
    gsm.update({char: [27, i] for i, char in EXT.items()})
    is_gsm = all(char in gsm for char in text)
    encoded = [gsm[char] if is_gsm else char.encode('utf-16-be') for char in text]
    length = sum(len(item) for item in encoded)
    # A 16-bit concatenation header is 7 bytes (8 GSM septets).
    single, multiple = (160, 152) if is_gsm else (140, 132)
    limit = single if length <= single else multiple
    chunks, chunk, used = [], [], 0
    for item in encoded:
        if used + len(item) > limit:
            chunks.append(chunk); chunk, used = [], 0
        chunk.append(item); used += len(item)
    chunks.append(chunk)
    if len(chunks) > 255:
        raise ValueError('Too many SMS parts')
    reference = secrets.randbelow(65536) if reference is None else reference
    result = []
    for index, chunk in enumerate(chunks, 1):
        header = bytes([6, 8, 4, reference >> 8, reference & 255, len(chunks), index]) if len(chunks) > 1 else b''
        if is_gsm:
            codes = [code for item in chunk for code in item]
            offset = math.ceil(len(header) * 8 / 7) * 7
            bits = int.from_bytes(header, 'little')
            for at, code in enumerate(codes):
                bits |= code << (offset + at * 7)
            udl = offset // 7 + len(codes)
            user = bits.to_bytes(math.ceil(udl * 7 / 8), 'little')
        else:
            user = header + b''.join(chunk); udl = len(user)
        pdu = (bytes([0, 0x41 if header else 1, 0, len(digits), 0x91 if number.startswith('+') else 0x81])
               + address + bytes([0, 0 if is_gsm else 8, udl]) + user)
        result.append(pdu.hex().upper())
    return result
