// Test production LuCI helper/rendering with in-memory MM objects; no device access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
String.prototype.format = function (value) {return this.replace('%d', value).replace('%%', '%');};
const root = path.resolve(__dirname, '../overlay/www/luci-static/resources');
const L = {bind: (fn, context) => fn.bind(context)};
const helper = new Function('baseclass', 'fs', 'L', fs.readFileSync(path.join(root, 'modemmanager_helper.js'), 'utf8'))(
  {extend: x => x}, {}, L);
const E = (tag, attrs, children) => ({tag, attrs, children, firstElementChild: {appendChild() {}, childNodes: []}});
const translate = text => text;
const view = new Function('view', 'ui', 'poll', 'dom', 'helper', 'L', 'E', '_',
  fs.readFileSync(path.join(root, 'view/modemmanager/status.js'), 'utf8'))(
  {extend: x => x}, {tabs: {initTabGroup() {}}}, {}, {}, helper, L, E, translate);

(async () => {
  const one = '/org/freedesktop/ModemManager1/SIM/41';
  const two = '/org/freedesktop/ModemManager1/SIM/0';
  helper.getSim = async index => ({sim: {properties: {active: true, 'operator-name': 'fixture'}}});
  for (const [slots, current, primary] of [[['/', two], two, '2'], [[one, '/'], one, '1'],
                                         [[one, two], two, '2'], [['/', '/'], null, '0']]) {
    const modem = {generic: {'sim-slots': slots, sim: current, 'primary-sim-slot': primary,
      'own-numbers': [], 'access-technologies': [], 'signal-quality': {value: '70'}}, '3gpp': {}};
    const originalSlots = slots.slice();
    const sims = await helper.getModemSims(modem);
    assert.deepEqual(sims.map(sim => sim.slot), [1, 2]);
    assert.deepEqual(modem.generic['sim-slots'], originalSlots);
    assert.deepEqual(sims.map(sim => !!sim.empty), slots.map(slot => slot === '/'));
    const titles = [];
    view.renderSection = (title, table) => {titles.push(String(title)); return {title, table};};
    view.renderSections = () => ({});
    view.renderContent([{modem, sims}]);
    assert(titles.includes('SIM 1') && titles.includes('SIM 2'), titles);
  }
  // An individual query failing retains its slot and cannot be called an empty slot.
  helper.getSim = async () => {throw new Error('temporarily unavailable');};
  const failed = await helper.getModemSims({generic: {'sim-slots': ['/', two], sim: two}});
  assert(failed[1].unavailable && !failed[1].empty && failed[1].slot === 2);
  // Legacy mmcli without a slot list still retains a known primary slot.
  helper.getSim = async () => ({sim: {properties: {}}});
  const legacy = await helper.getModemSims({generic: {sim: two, 'primary-sim-slot': '2'}});
  assert.equal(legacy[1].slot, 2);
  const withoutSlots = {generic: {sim: two, 'primary-sim-slot': '2', 'sim-slots': []}};
  await helper.getModemSims(withoutSlots);
  assert.deepEqual(withoutSlots.generic['sim-slots'], []);
  console.log('LuCI physical SIM slot checks passed: SIM2-only, SIM1-only, dual, empty, unavailable, legacy');
})().catch(error => {console.error(error); process.exitCode = 1;});
