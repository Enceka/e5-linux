"""Exercise actual SD power/voltage callbacks without opening any hardware."""
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
name = 'drivers/mmc/host/sdhci-sprd.c'
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); source = root/name; source.parent.mkdir(parents=True)
    source.write_bytes((Path(sys.argv[1])/name).read_bytes())
    apply = runpy.run_path(str(HERE/'sd-power.py'))['apply']
    apply(root); first = source.read_bytes(); apply(root); assert source.read_bytes() == first
    text = source.read_text()
    def function(signature):
        start = text.index(signature); end = text.index('\n}', start)+2
        return text[start:end]
    prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <errno.h>
#define MMC_POWER_OFF 0
#define MMC_POWER_UP 1
#define MMC_POWER_ON 2
#define MMC_SIGNAL_VOLTAGE_180 1
#define MMC_SIGNAL_VOLTAGE_330 0
#define SDHCI_RESET_CMD 1
#define SDHCI_RESET_DATA 2
#define IS_ERR(p) ((long)(p)<0)
#define TO_SPRD_HOST(h) ((void)(h),&state)
#define dev_err(...) ((void)0)
#define pr_err(...) ((void)0)
#define fallthrough __attribute__((fallthrough))
struct mmc_host { struct {void *vmmc,*vqmmc;} supply; };
struct mmc_ios { int signal_voltage; };
struct sdhci_host {struct mmc_host *mmc;};
struct sdhci_sprd_host {bool fast_hotplug,sd_power_valid;unsigned char sd_power_mode;
 unsigned short sd_power_vdd;void *pinctrl,*pins_uhs,*pins_default;};
static struct sdhci_sprd_host state;
static struct sdhci_host host;
static int steps[100],n,fail,vq_fail,voltage=1800000,resets,switch_fail,pin_fail;
static bool present=true;
static void *mmc_priv(struct mmc_host*m){(void)m;return &host;}
static int mmc_gpio_get_cd(struct mmc_host*m){(void)m;return present;}
static int mmc_regulator_set_ocr(struct mmc_host*m,void*r,int v){(void)m;(void)r;(void)v;steps[n++]=1;return fail;}
static int mmc_regulator_enable_vqmmc(struct mmc_host*m){(void)m;steps[n++]=3;return vq_fail ? vq_fail : fail;}
static void mmc_regulator_disable_vqmmc(struct mmc_host*m){(void)m;steps[n++]=5;}
static void usleep_range(int a,int b){(void)a;(void)b;steps[n++]=2;}
static void sdhci_sprd_fast_hotplug_enable(struct sdhci_sprd_host*s){(void)s;steps[n++]=4;}
static void sdhci_sprd_fast_hotplug_disable(struct sdhci_sprd_host*s){(void)s;steps[n++]=6;}
static int mmc_regulator_set_vqmmc(struct mmc_host*m,struct mmc_ios*i){(void)m;(void)i;return switch_fail;}
static int regulator_get_voltage(void*r){(void)r;return voltage;}
static int pinctrl_select_state(void*p,void*s){(void)p;(void)s;return pin_fail;}
static void sdhci_reset(struct sdhci_host*h,int bits){(void)h;assert(bits==3);resets++;}
'''
    checks = r'''
int main(void){
 struct mmc_host m={.supply={.vmmc=(void*)1,.vqmmc=(void*)2}};
 struct mmc_ios ios={.signal_voltage=MMC_SIGNAL_VOLTAGE_180};host.mmc=&m;
 state.fast_hotplug=true;state.pinctrl=(void*)-1;
 sdhci_sprd_set_power(&host,MMC_POWER_UP,18);
 assert(n==4&&steps[0]==1&&steps[1]==2&&steps[2]==3&&steps[3]==4);
 sdhci_sprd_set_power(&host,MMC_POWER_ON,18);assert(n==6);
 sdhci_sprd_set_power(&host,MMC_POWER_ON,18);assert(n==6);
 assert(!sdhci_sprd_voltage_switch(&m,&ios)&&resets==1);
 voltage=3000000;assert(sdhci_sprd_voltage_switch(&m,&ios)==-EIO&&resets==1);
 voltage=-EIO;assert(sdhci_sprd_voltage_switch(&m,&ios)==-EIO);
 voltage=1800000;switch_fail=-EIO;assert(sdhci_sprd_voltage_switch(&m,&ios)==-EIO);switch_fail=0;
 m.supply.vqmmc=(void*)-1;assert(sdhci_sprd_voltage_switch(&m,&ios)==-EOPNOTSUPP);
 m.supply.vqmmc=(void*)2;
 sdhci_sprd_set_power(&host,MMC_POWER_OFF,0);assert(n==9&&steps[6]==6&&steps[7]==1&&steps[8]==5);
 fail=-EIO;sdhci_sprd_set_power(&host,MMC_POWER_UP,18);assert(!state.sd_power_valid&&n==10);
 fail=0;sdhci_sprd_set_power(&host,MMC_POWER_UP,18);assert(state.sd_power_valid&&n==14);
 /* VMMC may succeed while VQMMC fails: no hotplug write or cached success. */
 n=0;state.sd_power_valid=false;vq_fail=-EIO;
 sdhci_sprd_set_power(&host,MMC_POWER_UP,18);assert(n==3&&!state.sd_power_valid);
 vq_fail=0;sdhci_sprd_set_power(&host,MMC_POWER_UP,18);assert(n==7&&state.sd_power_valid);
 /* Pinctrl failure propagates without pretending the controller was reset. */
 state.pinctrl=(void*)1;pin_fail=-EIO;int previous_resets=resets;
 assert(sdhci_sprd_voltage_switch(&m,&ios)==-EIO&&resets==previous_resets);
 pin_fail=0;ios.signal_voltage=MMC_SIGNAL_VOLTAGE_330;
 assert(!sdhci_sprd_voltage_switch(&m,&ios)&&resets==previous_resets+1);
 state.pinctrl=(void*)-1;ios.signal_voltage=MMC_SIGNAL_VOLTAGE_180;
 state.fast_hotplug=false;voltage=3000000;
 assert(!sdhci_sprd_voltage_switch(&m,&ios));
 n=0;sdhci_sprd_set_power(&host,MMC_POWER_UP,18);assert(n==1&&steps[0]==1);
 sdhci_sprd_set_power(&host,MMC_POWER_UP,18);assert(n==2&&steps[1]==1);
 /* An empty removable slot must not arm hotplug when powering its supplies. */
 n=0;present=false;state.fast_hotplug=true;state.sd_power_valid=false;
 sdhci_sprd_set_power(&host,MMC_POWER_UP,18);assert(n==3&&steps[2]==3);
 sdhci_sprd_set_power(&host,MMC_POWER_OFF,0);assert(n==5&&steps[3]==1&&steps[4]==5);
 return 0;
}
'''
    code = prelude+function('static void sdhci_sprd_set_power(')+'\n'+function('static int sdhci_sprd_voltage_switch(')+checks
    (root/'test.c').write_text(code)
    subprocess.run(['cc','-Wall','-Wextra','-Werror',str(root/'test.c'),'-o',str(root/'test')],check=True)
    subprocess.run([str(root/'test')],check=True)
print('SD power sequencing, timing-only updates, voltage errors, retry and eMMC isolation passed')
