// The E5's text messages for LuCI (服务 -> 短信): rpcd object "e5-sms" over
// /usr/libexec/e5-sms.  The text to send goes to it in a file, not on a
// command line.
'use strict';

import { popen, writefile, unlink } from 'fs';

const TOOL = '/usr/libexec/e5-sms';

function q(s) {
	return "'" + replace(`${s}`, "'", "'\\''") + "'";
}

function run(args) {
	let p = popen(`${TOOL} ${args} 2>&1`);
	let out = p ? p.read('all') : '';
	if (p) p.close();
	try {
		return json(out ?? '');
	}
	catch (e) {
		return { ok: false, error: trim(out ?? '') || 'e5-sms returned no data' };
	}
}

return {
	'e5-sms': {
		list: {
			call: function() {
				return run('list');
			}
		},
		sim: {
			call: function() {
				return run('sim');
			}
		},
		// the card in use (the data card too): e5-sim, in the background --
		// ModemManager takes some 20-60 s to have the new card's modem up
		switch_card: {
			args: { card: 0 },
			call: function(req) {
				let card = int(req.args?.card ?? -1);
				if (card != 0 && card != 1)
					return { ok: false, error: 'bad card' };
				system(`(e5-sim ${card} >/dev/null 2>&1 &)`);
				return { ok: true };
			}
		},
		send: {
			args: { number: '', text: '', card: '' },
			call: function(req) {
				let text = `${req.args?.text ?? ''}`;
				if (text == '')
					return { ok: false, error: 'no text' };
				let c = clock(true);
				let f = `/tmp/e5-sms-send.${c[0]}${c[1]}`;
				writefile(f, text);
				let card = `${req.args?.card ?? ''}`;
				let r = run(`send ${q(req.args?.number ?? '')} ${q(f)}` + ((card == '0' || card == '1') ? ` ${card}` : ''));
				unlink(f);
				return r;
			}
		},
		delete: {
			args: { id: 0 },
			call: function(req) {
				return run(`delete ${int(req.args?.id ?? -1)}`);
			}
		},
		forward_test: {
			call: function() {
				return run('forward-test');
			}
		},
		forward_log: {
			call: function() {
				return run('forward-log');
			}
		}
	}
};
