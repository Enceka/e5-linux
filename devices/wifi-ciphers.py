#!/usr/bin/env python3
"""Filter LuCI cipher choices by the radio's actual nl80211 capabilities."""
import argparse
from pathlib import Path
import re


def patch(root):
    path = Path(root) / 'www/luci-static/resources/view/network/wireless.js'
    if not path.is_file():
        return
    text = path.read_text(encoding='utf-8')
    if 'e5ReadCipher' in text:
        return
    text, count = re.subn(
        r'return network\.getWifiNetwork\(s\.section\)\.then\(function\(radioNet\)\s*\{',
        "return network.getWifiNetwork(s.section).then(async function(radioNet) {\n"
        "const e5CipherCaps = await fs.exec_direct('/usr/libexec/e5-wifi-ciphers', [radioNet.getWifiDeviceName()], 'json').catch(() => ({}));\n",
        text)
    if count != 1:
        raise ValueError('Unexpected LuCI wireless modal source')
    # Filter suites by IEEE OUI/type, never by a translated display name.
    for option, suite in [('ccmp', '4'), ('ccmp256', '10'), ('gcmp', '8'),
                          ('gcmp256', '9'), ('tkip', '2')]:
        pattern = r"o\.value\('" + option + r"',\s*_\('[^']+'\)\);"
        text, count = re.subn(pattern,
            lambda m: "if (!e5CipherCaps.suites || e5CipherCaps.suites.includes('00-0f-ac:" + suite + "')) " + m[0], text)
        if count != 1:
            raise ValueError('Unexpected LuCI cipher option: ' + option)
    pattern = r"o\.value\('tkip\+ccmp',\s*_\('[^']+'\)\);"
    text, count = re.subn(pattern, lambda m:
        "if (!e5CipherCaps.suites || ['00-0f-ac:2','00-0f-ac:4'].every(c => e5CipherCaps.suites.includes(c))) " + m[0], text)
    if count != 1:
        raise ValueError('Unexpected LuCI mixed cipher option')
    # Keep an old invalid choice visible as an error, without silently choosing auto.
    # Sources may be minified or formatted; anchor only the cipher's cfgvalue.
    start = text.index("'cipher',")
    m = re.search(r'o\.cfgvalue\s*=\s*function\(section_id\)', text[start:])
    if not m:
        raise ValueError('Unexpected LuCI cipher reader')
    pos = start + m.start()
    validate = """const e5CipherTypes = {ccmp:['4'],ccmp256:['10'],gcmp:['8'],gcmp256:['9'],tkip:['2'],'tkip+ccmp':['2','4']};
    o.validate = function(section_id, value) {
        const suites = e5CipherCaps.suites;
        const needed = e5CipherTypes[value];
        if (suites && needed && !needed.every(c => suites.includes('00-0f-ac:' + c)))
            return /^zh/.test(L.env.lang) ? '无线驱动不支持此密码套件，请选择支持的套件。' :
                /^tr/.test(L.env.lang) ? 'Kablosuz sürücüsü bu şifreleme paketini desteklemiyor. Desteklenen bir paket seçin.' :
                'The wireless driver does not support this cipher. Select a supported cipher.';
        return true;
    };
"""
    text = text[:pos] + validate + text[pos:]
    preserve = """const e5ReadCipher = o.cfgvalue;
    o.cfgvalue = function(section_id) {
        const value = e5ReadCipher.call(this, section_id);
        // Native <select> chooses its first option if a stored value vanishes.
        // Keep ONLY the existing unsupported value; validation still rejects it.
        if (e5CipherTypes[value] && !this.keylist.includes(value))
            this.value(value, value.toUpperCase() + ' (' + _('Unsupported') + ')');
        return value;
    };
"""
    text, count = re.subn(r'const crypto_modes\s*=\s*\[\];', lambda m: preserve + m[0], text)
    if count != 1:
        raise ValueError('Unexpected LuCI cipher controls ending')
    path.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    patch(parser.parse_args().root)
