#!/usr/bin/env python3
"""Compile production MM power-plan callbacks with fake AT results, no hardware."""
from pathlib import Path
import subprocess
import sys
import tempfile

input_path = Path(sys.argv[1])
source = (input_path if input_path.is_file() else input_path / 'plugins/unisoc/mm-broadband-modem-unisoc.c').read_text()


def function(name):
    start = source.index('static void\n' + name + ' (')
    return source[start:source.index('\n}\n', start) + 3]


model = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
typedef unsigned guint; typedef char gchar; typedef int gboolean;
typedef void (*GAsyncReadyCallback)(void);
typedef struct {char *command; unsigned timeout;} MMBaseModemAtCommandAlloc;
typedef MMBaseModemAtCommandAlloc MMBaseModemAtCommand;
typedef struct {MMBaseModemAtCommandAlloc cmds[9]; gboolean present[2]; guint probe,own;} CardsOnContext;
typedef struct {CardsOnContext *data;} GTask;
typedef int MMBaseModem;
typedef struct {int code;} GError;
typedef struct {const char *response;int code;} GAsyncResult;
#define FALSE 0
#define MM_MOBILE_EQUIPMENT_ERROR 1
#define MM_MOBILE_EQUIPMENT_ERROR_SIM_NOT_INSERTED 10
#define mm_obj_info(...) ((void)0)
static int sequenced,next;
static void cards_on_sequence_ready(void) {}
static void cards_on_probe_next(GTask *task) {next++;}
static void *g_task_get_task_data(GTask *t){return t->data;}
static const char *mm_base_modem_at_command_finish(MMBaseModem *m,GAsyncResult *r,GError **error){
 if(error && r->code){*error=malloc(sizeof(GError));(*error)->code=r->code;}
 return r->response;
}
static int g_error_matches(GError *error,int domain,int code){return error->code==code;}
static void g_clear_error(GError **error){free(*error);*error=NULL;}
static char *g_strdup(const char *s){return strdup(s);}
static char *g_strdup_printf(const char *fmt,...){va_list args;char *out;va_start(args,fmt);vasprintf(&out,fmt,args);va_end(args);return out;}
static void mm_base_modem_at_sequence(MMBaseModem *m,const MMBaseModemAtCommand *commands,void *a,void *b,GAsyncReadyCallback cb,GTask *t){
 sequenced++;
 assert(commands==t->data->cmds && commands[8].command==NULL);
}
'''

tests = r'''
static void check(int first,int second,unsigned own){
 CardsOnContext ctx={0};ctx.present[0]=first;ctx.present[1]=second;ctx.own=own;
 GTask task={&ctx};MMBaseModem modem=0;GAsyncResult modes={"+SPTESTMODE: 98,134,0,19,3,1",0};
 cards_on_testmode_ready(&modem,&modes,&task);
 unsigned i=0,sfun[2]={0},data=0;
 for(;ctx.cmds[i].command;i++){
  char *command=ctx.cmds[i].command;unsigned card;
  assert(sscanf(command,"+SPACTCARD=%u;",&card)==1 && card<2);
  if(strstr(command,"SFUN=") || strstr(command,"SPTESTMODEM=") || strstr(command,"SPSWDATA"))
    assert(ctx.present[card]);
  if(strstr(command,"SFUN="))sfun[card]++;
  if(strstr(command,"SPSWDATA")){assert(card==own);data++;}
  if(strstr(command,"SPTESTMODEM="))assert(strstr(command,"=98,134"));
 }
 assert(i==(unsigned)(1+3*(first+second)+(ctx.present[own]?1:0)));
 assert(sfun[0]==(unsigned)(first?2:0) && sfun[1]==(unsigned)(second?2:0));
 assert(data==(unsigned)(ctx.present[own]?1:0));
 char ending[40];snprintf(ending,sizeof(ending),"+SPACTCARD=%u;+CFUN?",own);
 assert(!strcmp(ctx.cmds[i-1].command,ending));
 // Preserve vendor RIL ordering when both cards are inserted.
 if(first&&second){
  assert(!strcmp(ctx.cmds[0].command,"+SPACTCARD=0;+SFUN=2"));
  assert(!strcmp(ctx.cmds[1].command,"+SPACTCARD=1;+SFUN=2"));
  assert(strstr(ctx.cmds[2].command,"+SPACTCARD=1;+SPTESTMODEM="));
  assert(strstr(ctx.cmds[3].command,"+SPACTCARD=0;+SPTESTMODEM="));
  assert(!strcmp(ctx.cmds[5].command,"+SPACTCARD=0;+SFUN=4"));
  assert(!strcmp(ctx.cmds[6].command,"+SPACTCARD=1;+SFUN=4"));
 }
 for(unsigned j=0;j<i;j++)free(ctx.cmds[j].command);
}
int main(void){
 for(int first=0;first<2;first++)for(int second=0;second<2;second++)for(unsigned own=0;own<2;own++)check(first,second,own);
 CardsOnContext ctx={0};ctx.present[0]=ctx.present[1]=1;GTask task={&ctx};MMBaseModem modem=0;
 GAsyncResult absent={NULL,10},busy={NULL,14};
 cards_on_probe_ready(&modem,&absent,&task);assert(!ctx.present[0] && ctx.probe==1);
 cards_on_probe_ready(&modem,&busy,&task);assert(ctx.present[1] && ctx.probe==2);
 assert(sequenced==8 && next==2);
 puts("SIM power checks passed: 8 slot/preference plans, absent vs busy, vendor order, selected AT context");
}
'''
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / 'test.c').write_text(model + function('cards_on_testmode_ready') +
                               function('cards_on_probe_ready') + tests)
    subprocess.run(['cc', '-D_GNU_SOURCE', '-Wall', '-Werror', str(root / 'test.c'), '-o', str(root / 'test')], check=True)
    subprocess.run([str(root / 'test')], check=True)
