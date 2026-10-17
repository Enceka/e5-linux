"""Compile the actual charger-manager notification paths with capability mocks."""
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
name = 'drivers/power/supply/charger-manager.c'
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); source = root/name; source.parent.mkdir(parents=True)
    source.write_bytes((Path(sys.argv[1])/name).read_bytes())
    apply = runpy.run_path(str(HERE/'charger-capabilities.py'))['apply']
    apply(root); first = source.read_bytes(); apply(root); assert source.read_bytes() == first
    text = source.read_text()
    def function(signature):
        start = text.index(signature); end = text.index('\n}', start)+2
        return text[start:end]
    prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
enum { POWER_SUPPLY_PROP_PRESENT=1 };
struct power_supply;
struct psy_desc { int (*property_is_writeable)(struct power_supply*,int); };
struct power_supply { struct psy_desc *desc; };
struct charger_desc { const char **psy_charger_stat,**psy_wl_charger_stat; };
struct charger_manager { struct charger_desc *desc; int dev; };
union power_supply_propval { int intval; };
static int capability,puts,writes,wireless,errors,fail;
static int writable(struct power_supply *p,int prop){(void)p;assert(prop==1);return capability;}
static struct psy_desc pd={writable};static struct power_supply supply={&pd};
static struct power_supply *power_supply_get_by_name(const char *name){(void)name;return &supply;}
static void power_supply_put(struct power_supply *p){assert(p==&supply);puts++;}
static int power_supply_set_property(struct power_supply*p,int prop,union power_supply_propval*v){
 (void)v;assert(p==&supply&&prop==1);writes++;return fail;}
#define dev_err(...) ((void)errors++)
static int cm_set_primary_charge_wirless_type(struct charger_manager*c,bool b){(void)c;(void)b;wireless++;return fail;}
static int try_wireless_charger_enable_by_psy(struct charger_manager*c,bool b){(void)c;(void)b;wireless++;return 0;}
static int try_wireless_cp_converter_enable_by_psy(struct charger_manager*c,bool b){(void)c;(void)b;wireless++;return 0;}
'''
    checks = r'''
int main(void){
 const char *chargers[] = {"charger",NULL},*empty[]={NULL},*wl[]={"wireless",NULL};
 struct charger_desc d={chargers,NULL};struct charger_manager c={&d,0};
 cm_set_charger_present(&c,true);assert(puts==1&&!writes&&!errors);
 pd.property_is_writeable=NULL;cm_set_charger_present(&c,false);assert(puts==2&&!writes);
 pd.property_is_writeable=writable;capability=1;cm_set_charger_present(&c,true);assert(puts==3&&writes==1);
 fail=-5;cm_set_charger_present(&c,false);assert(puts==4&&writes==2&&errors==1);fail=0;
 try_wireless_charger_enable(&c,false);assert(!wireless);
 d.psy_wl_charger_stat=empty;try_wireless_charger_enable(&c,false);assert(!wireless);
 d.psy_wl_charger_stat=wl;try_wireless_charger_enable(&c,true);assert(wireless==3);
 fail=-5;try_wireless_charger_enable(&c,false);assert(wireless==4&&errors==2);
 return 0;
}
'''
    code = prelude+function('static void cm_set_charger_present(')+'\n'+function('static void try_wireless_charger_enable(')+checks
    (root/'test.c').write_text(code)
    subprocess.run(['cc','-Wall','-Wextra','-Werror',str(root/'test.c'),'-o',str(root/'test')],check=True)
    subprocess.run([str(root/'test')],check=True)
print('Charger capabilities, wired/wireless isolation, errors and reference ownership passed')
