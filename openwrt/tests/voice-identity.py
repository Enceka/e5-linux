#!/usr/bin/env python3
"""Compile the production MM matching/routing functions against an in-memory model.

Pass the patched ModemManager src directory. No modem, D-Bus or call operation
is used: even AT command checks only compare returned strings.
"""
from pathlib import Path
import subprocess, sys, tempfile
src=Path(sys.argv[1])
def function(path,name,signature):
 text=(src/path).read_text();start=text.index(signature+'\n'+name+' (')
 return text[start:text.index('\n}\n',start)+3]
matcher=function('mm-iface-modem-voice.c','match_single_call_info','static gboolean')
route=function('mm-base-call.c','call_command_for_card','static gchar *')
model=r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
typedef unsigned guint; typedef char gchar; typedef int gboolean;
#define TRUE 1
#define FALSE 0
#define MM_GDBUS_CALL(x) (x)
#define G_OBJECT(x) (x)
#define mm_obj_dbg(...) ((void)0)
#define MM_CALL_STATE_REASON_UNKNOWN 0
typedef enum {MM_CALL_STATE_UNKNOWN,MM_CALL_STATE_DIALING,MM_CALL_STATE_RINGING_OUT,MM_CALL_STATE_RINGING_IN,MM_CALL_STATE_ACTIVE,MM_CALL_STATE_HELD,MM_CALL_STATE_WAITING,MM_CALL_STATE_TERMINATED} MMCallState;
typedef enum {MM_CALL_DIRECTION_UNKNOWN,MM_CALL_DIRECTION_INCOMING,MM_CALL_DIRECTION_OUTGOING} MMCallDirection;
typedef void MMIfaceModemVoice;
typedef struct {int e5;} Modem;
typedef struct {Modem *modem;} Private;
typedef struct {guint index,sim_slot;MMCallDirection direction;MMCallState state;char *number;} MMCallInfo;
typedef struct {guint index,slot,refreshes;MMCallDirection direction;MMCallState state;char *number;Private *priv;} MMBaseCall;
MMCallState mm_base_call_get_state(MMBaseCall*c){return c->state;}
MMCallDirection mm_base_call_get_direction(MMBaseCall*c){return c->direction;}
const char *mm_base_call_get_number(MMBaseCall*c){return c->number;}
guint mm_base_call_get_index(MMBaseCall*c){return c->index;}
guint mm_gdbus_call_get_sim_slot(MMBaseCall*c){return c->slot;}
gboolean mm_base_call_get_multiparty(MMBaseCall*c){return 0;}
void mm_base_call_set_number(MMBaseCall*c,const char*n){c->number=strdup(n);}
void mm_base_call_set_index(MMBaseCall*c,guint i){c->index=i;}
void mm_base_call_change_state(MMBaseCall*c,MMCallState s,int r){c->state=s;}
void mm_base_call_incoming_refresh(MMBaseCall*c){c->refreshes++;}
int g_strcmp0(const char*a,const char*b){return a&&b?strcmp(a,b):(a!=b);}
char *g_strdup(const char*s){return strdup(s);}
int g_str_has_prefix(const char*s,const char*p){return !strncmp(s,p,strlen(p));}
char *g_strdup_printf(const char*fmt,...){va_list a;char *s;va_start(a,fmt);vasprintf(&s,fmt,a);va_end(a);return s;}
void *g_object_get_data(Modem*m,const char*k){return m->e5?(void*)1:NULL;}
'''
tests=r'''
int main(void){
 Modem modem={1};Private priv={&modem};
 MMBaseCall one={1,1,0,MM_CALL_DIRECTION_INCOMING,MM_CALL_STATE_ACTIVE,"10099",&priv};
 MMCallInfo other={1,2,MM_CALL_DIRECTION_INCOMING,MM_CALL_STATE_RINGING_IN,"10099"};
 assert(!match_single_call_info(NULL,&other,&one));assert(one.state==MM_CALL_STATE_ACTIVE&&one.refreshes==0);
 MMCallInfo waiting={2,1,MM_CALL_DIRECTION_INCOMING,MM_CALL_STATE_WAITING,"10099"};
 assert(!match_single_call_info(NULL,&waiting,&one));
 MMBaseCall pending={0,2,0,MM_CALL_DIRECTION_OUTGOING,MM_CALL_STATE_DIALING,"18000000000",&priv};
 MMCallInfo connected={1,2,MM_CALL_DIRECTION_OUTGOING,MM_CALL_STATE_ACTIVE,"+8618000000000"};
 assert(match_single_call_info(NULL,&connected,&pending));assert(pending.index==1&&pending.state==MM_CALL_STATE_ACTIVE);
 MMCallInfo reused={1,1,MM_CALL_DIRECTION_INCOMING,MM_CALL_STATE_RINGING_IN,"10010"};
 assert(!match_single_call_info(NULL,&reused,&one));
 char *s=call_command_for_card(&pending,"ATD10099;");assert(!strcmp(s,"AT+SPACTCARD=1;D10099;"));free(s);
 s=call_command_for_card(&pending,"ATA");assert(!strcmp(s,"AT+SPACTCARD=1;A"));free(s);
 s=call_command_for_card(&pending,"+CHLD=11");assert(!strcmp(s,"AT+SPACTCARD=1;+CHLD=11"));free(s);
 s=call_command_for_card(&one,"AT+VTS=5");assert(!strcmp(s,"AT+SPACTCARD=0;+VTS=5"));free(s);
 modem.e5=0;s=call_command_for_card(&pending,"ATA");assert(!strcmp(s,"ATA"));free(s);
 puts("Voice identity and routing checks passed: duplicate numbers/indices, pending dial, reused index, addressed controls");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 path=Path(tmp);(path/'test.c').write_text(model+matcher+route+tests)
 subprocess.run(['cc','-D_GNU_SOURCE','-Wall','-Werror',str(path/'test.c'),'-o',str(path/'test')],check=True)
 subprocess.run([str(path/'test')],check=True)
