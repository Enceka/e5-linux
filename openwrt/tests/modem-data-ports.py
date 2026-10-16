#!/usr/bin/env python3
"""Compile the shipped CID/port selector with fake sysfs and modem ports."""
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

source = (Path(sys.argv[1]) / 'plugins/unisoc/mm-broadband-bearer-unisoc.c').read_text()
start = source.index('static MMPort *\nget_context_data_port (')
end = source.index('\n}\n', start) + 3
function = source[start:end]
model = r'''
#include <glib-object.h>
#include <string.h>
typedef GObject MMPort;
typedef GObject MMBaseModem;
enum { MM_CORE_ERROR_FAILED, MM_CORE_ERROR_UNSUPPORTED, MM_CORE_ERROR_NOT_FOUND, MM_PORT_TYPE_NET };
#define MM_CORE_ERROR (g_quark_from_static_string("test-core-error"))
static const char *card = "0";
static int missing = -1, wrong_type = -1;
static gboolean fake_read(const char *path, gchar **contents, gsize *length, GError **error) {
 g_assert_cmpstr(path,==,"/sys/module/sipc_wwan/parameters/card");
 if (!card) {g_set_error_literal(error,G_FILE_ERROR,G_FILE_ERROR_NOENT,"missing parameter");return FALSE;}
 *contents=g_strdup(card);return TRUE;
}
#define g_file_get_contents fake_read
static MMPort *mm_base_modem_get_port(MMBaseModem *modem, const char *name) {
 guint n;g_assert_cmpint(sscanf(name,"sipa_eth%u",&n),==,1);
 if ((int)n == missing) return NULL;
 GObject *p=g_object_new(G_TYPE_OBJECT,NULL);
 g_object_set_data(p,"name",g_strdup(name));
 g_object_set_data(p,"type",GINT_TO_POINTER((int)n == wrong_type ? 99 : MM_PORT_TYPE_NET));return p;
}
static int mm_port_get_port_type(MMPort *port) {return GPOINTER_TO_INT(g_object_get_data(port,"type"));}
'''
tests = r'''
int main(void) {
 GError *error=NULL;char text[4],expected[32];MMPort *p;
 for (guint slot=0;slot<2;slot++) {
  g_snprintf(text,sizeof(text),"%u\n",slot);card=text;
  for(guint cid=1;cid<=8;cid++) {
   p=get_context_data_port(NULL,cid,&error);g_assert_no_error(error);g_assert_nonnull(p);
   g_snprintf(expected,sizeof(expected),"sipa_eth%u",slot*8+cid-1);
   g_assert_cmpstr(g_object_get_data(p,"name"),==,expected);
   g_free(g_object_get_data(p,"name"));g_object_unref(p);
  }
  for(guint cid=0;cid<=12;cid++) {
   if(cid>=1 && cid<=8)continue;
   g_assert_null(get_context_data_port(NULL,cid,&error));
   g_assert_error(error,MM_CORE_ERROR,MM_CORE_ERROR_UNSUPPORTED);g_clear_error(&error);
  }
 }
 card="1";missing=9;
 g_assert_null(get_context_data_port(NULL,2,&error));g_assert_nonnull(strstr(error->message,"sipa_eth9"));g_clear_error(&error);
 missing=-1;wrong_type=9;
 g_assert_null(get_context_data_port(NULL,2,&error));g_assert_error(error,MM_CORE_ERROR,MM_CORE_ERROR_NOT_FOUND);g_clear_error(&error);
 card="2";g_assert_null(get_context_data_port(NULL,1,&error));g_assert_error(error,MM_CORE_ERROR,MM_CORE_ERROR_FAILED);g_clear_error(&error);
 card=NULL;g_assert_null(get_context_data_port(NULL,1,&error));g_assert_error(error,G_FILE_ERROR,G_FILE_ERROR_NOENT);g_clear_error(&error);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path/'test.c').write_text('#include <stdio.h>\n' + model + function + tests)
    flags = shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','gobject-2.0'],text=True))
    subprocess.run(['cc','-Wall','-Werror',str(path/'test.c'),'-o',str(path/'test'),*flags],check=True)
    subprocess.run([str(path/'test')],check=True)
print('PASS: all 16 SIM/CID mappings, invalid bank/CID, missing sysfs/port and wrong port type')
