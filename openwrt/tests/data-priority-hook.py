#!/usr/bin/env python3
"""Compile actual MM preference hooks with fake spawn/finish callbacks, no modem."""
from pathlib import Path
import subprocess
import sys
import tempfile

source = (Path(sys.argv[1]) / 'plugins/unisoc/mm-broadband-modem-unisoc.c').read_text()


def function(name):
    start = source.index('\n' + name + ' (')
    start = source.rfind('static ', 0, start)
    return source[start:source.index('\n}\n', start) + 3]


model = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
typedef int gboolean;
typedef char gchar;
typedef void *gpointer;
typedef struct {const char *message;} GError;
typedef struct {int ready;} GAsyncResult;
typedef int MMBaseModem;
typedef int MMIfaceModem;
typedef int MMBroadbandModem;
#define MM_BASE_MODEM(x) (x)
#define G_TASK(x) (x)
#define G_SPAWN_STDOUT_TO_DEV_NULL 1
#define G_SPAWN_STDERR_TO_DEV_NULL 2
#define mm_obj_warn(...) (warnings++)
static unsigned slot, spawned, warnings;
static int radio_allowed=1;
static gboolean sim_radio_enabled(unsigned card) {assert(card==slot); return radio_allowed;}
static int spawn_fails, parent_ready=1, parent_calls;
static unsigned port_card(void) {return slot;}
static gboolean g_task_propagate_boolean(GAsyncResult *res,GError **error) {return res->ready;}
static gboolean parent_stop(MMBroadbandModem *self,gpointer ports,GError **error) {
    assert(ports==self); parent_calls++; return parent_ready;
}
static struct {gboolean (*initialization_stopped)(MMBroadbandModem*,gpointer,GError**);} parent={parent_stop};
#define MM_BROADBAND_MODEM_CLASS(x) (&parent)
#define mm_broadband_modem_unisoc_parent_class (&parent)
static int g_spawn_async(void *cwd,char **argv,void *env,int flags,void *a,void *b,void *c,GError **error) {
    static GError failure={"test spawn failure"};
    assert(!cwd && !env && !a && !b && !c);
    assert(flags==(G_SPAWN_STDOUT_TO_DEV_NULL|G_SPAWN_STDERR_TO_DEV_NULL));
    assert(!strcmp(argv[0],"/opt/e5/e5-data-priority"));
    assert(!strcmp(argv[1],"queue"));
    assert(argv[2][0]=='0'+slot && !argv[2][1] && !argv[3]);
    spawned++;
    if(spawn_fails) {*error=&failure; return 0;}
    return 1;
}
static void g_clear_error(GError **error) {*error=NULL;}
'''
tests = r'''
int main(void) {
    MMBaseModem modem=0;
    GAsyncResult ok={1},bad={0};
    for(slot=0;slot<2;slot++) for(spawn_fails=0;spawn_fails<2;spawn_fails++) {
        unsigned before=spawned;
        parent_ready=1;
        assert(initialization_stopped(&modem,&modem,NULL));
        assert(modem_power_up_finish(&modem,&ok,NULL));
        assert(spawned==before+2); /* helper failure never alters MM success */
        parent_ready=0;
        assert(!initialization_stopped(&modem,&modem,NULL));
        assert(!modem_power_up_finish(&modem,&bad,NULL));
        assert(modem_power_finish(&modem,&ok,NULL)); /* radio-off path unchanged */
        assert(spawned==before+2);
    }
    assert(parent_calls==8 && warnings==4);
    radio_allowed=0;
    unsigned before=spawned;
    parent_ready=1;
    assert(initialization_stopped(&modem,&modem,NULL));
    assert(modem_power_up_finish(&modem,&ok,NULL));
    assert(spawned==before); /* disabled data RF must not queue priority AT */
    puts("PASS: MM hooks retain parent results, address both SIMs, detach, survive spawn failure, exclude power-down");
}
'''
assert 'iface->modem_power_up_finish = modem_power_up_finish;' in source
assert 'broadband_modem_class->initialization_stopped = initialization_stopped;' in source
with tempfile.TemporaryDirectory(prefix='e5-policy-hook-') as directory:
    root = Path(directory)
    (root / 'test.c').write_text(model + '\n'.join(function(name) for name in (
        'queue_data_priority', 'modem_power_finish', 'modem_power_up_finish', 'initialization_stopped')) + tests)
    subprocess.run(['cc', '-Wall', '-Werror', str(root / 'test.c'), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
