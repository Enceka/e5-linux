'use strict';
'require baseclass';
'require fs';

return baseclass.extend({

	_mmcliBin: '/usr/bin/mmcli',

	_emptyStringValue: '--',

	_parseIndex: function (dbusPath) {
		if (typeof dbusPath != 'string') return NaN;
		var index = dbusPath.split('/').slice(-1);
		return parseInt(index);
	},

	_parseOutput: function (output) {
		try {
			return this._removeEmptyStrings(JSON.parse(output));
		} catch (err) {
			return null;
		}
	},

	_removeEmptyStrings: function (obj) {
		if (obj == null) {
			return obj;
		}

		if (typeof obj == 'string') {
			if (obj == this._emptyStringValue) {
				obj = null;
			}
		} else if (Array.isArray(obj)) {
			obj = obj.map(L.bind(function (it) {
				return this._removeEmptyStrings(it);
			}, this));
		} else {
			var keys = Object.keys(obj);
			keys.forEach(L.bind(function (key) {
				obj[key] = this._removeEmptyStrings(obj[key]);
			}, this));
		}

		return obj;
	},

	getModems: function () {
		return fs.exec_direct(this._mmcliBin, [ '-L', '-J' ]).then(L.bind(function (res) {
			var json = this._parseOutput(res);
			if (json == null) {
				return [];
			}
			var modems = json['modem-list'];
			var tasks = [];

			modems.forEach(L.bind(function (modem) {
				var index = this._parseIndex(modem);
				if (!isNaN(index)) {
					tasks.push(this.getModem(index));
				}
			}, this));
			return Promise.all(tasks);
		}, this));
	},

	getModem: function (index) {
		return fs.exec_direct(this._mmcliBin, [ '-m', index, '-J' ]).then(L.bind(function (modem) {
			return this._parseOutput(modem);
		}, this));
	},

	getModemSims: function (modem) {
		// Keep physical slot positions even when a slot has no SIM object.
		var slots = Array.isArray(modem.generic['sim-slots']) ? modem.generic['sim-slots'].slice() : [];
		var current = modem.generic.sim;
		var primary = parseInt(modem.generic['primary-sim-slot']);
		if (current && !isNaN(this._parseIndex(current)) && !slots.includes(current)) {
			if (primary > 0) slots[primary - 1] = current;
			else if (!slots.length) slots.push(current);
		}
		return Promise.all(Array.from(slots, L.bind(function (path, position) {
			var slot = position + 1;
			var index = this._parseIndex(path);
			if (isNaN(index)) return { slot: slot, sim: null, empty: true };
			return this.getSim(index).then(function (result) {
				if (!result) return { slot: slot, sim: null, unavailable: true };
				result.slot = slot;
				return result;
			}, function () { return { slot: slot, sim: null, unavailable: true }; });
		}, this)));
	},

	getSim: function (index) {
		return fs.exec_direct(this._mmcliBin, [ '-i', index, '-J' ]).then(L.bind(function (sim) {
			return this._parseOutput(sim);
		}, this));
	},

	getModemLocation: function (modem) {
		var index = this._parseIndex(modem['dbus-path']);
		return fs.exec_direct(this._mmcliBin, [ '-m', index, '--location-get', '-J' ]).then(L.bind(function (location) {
			return this._parseOutput(location);
		}, this));
	}
});
