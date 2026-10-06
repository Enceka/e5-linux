/* Read physical SIM availability before SIPC WWAN/ModemManager takes ownership.
 * Only CPIN queries are sent. No SIM/radio power, PIN, data or call operation. */
#define _DEFAULT_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>

static long long milliseconds(void) {
 struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t);
 return (long long)t.tv_sec*1000+t.tv_nsec/1000000;
}
static int query(int fd,const char *command,char *reply,size_t size,int timeout) {
 size_t used=0;long long due=milliseconds()+timeout;
 reply[0]=0;
 if(write(fd,command,strlen(command))!=(ssize_t)strlen(command))return -1;
 while(milliseconds()<due && used+1<size) {
  struct pollfd p={fd,POLLIN,0};
  int ready=poll(&p,1,100);
  if(ready<=0)continue;
  ssize_t n=read(fd,reply+used,size-used-1);
  if(n<=0){if(errno==EAGAIN||errno==EINTR)continue;return -1;}
  used+=(size_t)n;reply[used]=0;
  if(strstr(reply,"\nOK")||strstr(reply,"\nERROR")||strstr(reply,"+CME ERROR:"))return 0;
 }
 return -1;
}
static int presence(const char *reply) {
 const char *p=strstr(reply,"+CME ERROR:");int code=-1;
 if(p && sscanf(p,"+CME ERROR: %d",&code)==1 && code==10)return 0;
 if(strstr(reply,"+CPIN:"))return 1; /* READY, PIN/PUK locked still means inserted */
 return -1;
}
static int select_card(int preferred,int first,int second) {
 int statuses[2]={first,second};
 return statuses[preferred]==0 && statuses[1-preferred]==1 ? 1-preferred : preferred;
}
int main(int argc,char **argv) {
 const char *port=argc>1?argv[1]:"/dev/stty_nr1";
 int preferred=argc>2 && !strcmp(argv[2],"1")?1:0;
 int status[2]={-1,-1};char response[4096],command[64];
 struct stat st;
#ifndef E5_SIM_PROBE_TEST
 if(!stat("/sys/module/sipc_wwan",&st)){fprintf(stderr,"SIM probe: WWAN already owns the channel\n");return 1;}
#else
 (void)st;
#endif
 /* The node may exist before CP opens its channel (open returns ENODEV).
  * Wait before loading WWAN, so first boot cannot miss the sole inserted SIM. */
 long long due=milliseconds()+30000;
 int fd;
 do {
  fd=open(port,O_RDWR|O_NONBLOCK|O_CLOEXEC);
  if(fd>=0)break;
  if(errno!=ENODEV && errno!=ENOENT && errno!=EAGAIN && errno!=EBUSY)break;
  usleep(200000);
 } while(milliseconds()<due);
 if(fd<0){perror("SIM probe open");return 1;}
 if(isatty(fd)){struct termios t;if(!tcgetattr(fd,&t)){cfmakeraw(&t);tcsetattr(fd,TCSANOW,&t);}}
 /* The spipe node exists before CP boot. Wait for a final AT response before
  * associating CPIN replies with cards; never guess an absent card on timeout. */
 due=milliseconds()+30000;
 int alive=0;
 while(milliseconds()<due) {
  if(query(fd,"AT\r",response,sizeof(response),1000)==0 && strstr(response,"OK")){alive=1;break;}
  usleep(200000);
 }
 if(!alive){close(fd);fprintf(stderr,"SIM probe: AT not ready; retaining preference\n");printf("%d\n",preferred);return 0;}
 for(int card=0;card<2;card++) {
  usleep(400000);
  snprintf(command,sizeof(command),"AT+SPACTCARD=%d;+CPIN?\r",card);
  if(!query(fd,command,response,sizeof(response),3000))status[card]=presence(response);
 }
 /* Leave the channel on the chosen card. This final query is read-only. */
 int selected=select_card(preferred,status[0],status[1]);
 usleep(400000);snprintf(command,sizeof(command),"AT+SPACTCARD=%d;+CFUN?\r",selected);
 query(fd,command,response,sizeof(response),3000);close(fd);
 fprintf(stderr,"SIM probe: SIM1=%s SIM2=%s selected=SIM%d\n",status[0]==1?"inserted":status[0]==0?"absent":"unknown",status[1]==1?"inserted":status[1]==0?"absent":"unknown",selected+1);
 printf("%d\n",selected);return 0;
}
