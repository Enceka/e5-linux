#!/usr/bin/env python3
"""Restore the factory removable-slot power transition contract, retaining UHS."""
from pathlib import Path


def apply(kernel):
    path = Path(kernel)/'drivers/mmc/host/sdhci-sprd.c'
    source = path.read_text()
    marker = 'Factory SD power transitions: do not reprogram RMLDO on each set_ios.'
    if marker not in source:
        anchor = '\tbool fast_hotplug;'
        if source.count(anchor) != 1:
            raise ValueError('Unknown removable SD host state')
        source = source.replace(anchor, anchor+'\n\tbool sd_power_valid;\n\tunsigned char sd_power_mode;\n\tunsigned short sd_power_vdd;', 1)
        start = source.index('static void sdhci_sprd_set_power(')
        end = source.index('\n}', start)+2
        source = source[:start]+'''static void sdhci_sprd_set_power(struct sdhci_host *host, unsigned char mode,
                                 unsigned short vdd)
{
\tstruct sdhci_sprd_host *sprd_host = TO_SPRD_HOST(host);
\tstruct mmc_host *mmc = host->mmc;
\tbool card_present = mmc_gpio_get_cd(mmc) > 0;
\tint ret = 0;

\t/* Factory SD power transitions: do not reprogram RMLDO on each set_ios.
\t * Clock/timing/bus-width changes are not slot power transitions. */
\tif (sprd_host->fast_hotplug && sprd_host->sd_power_valid &&
\t    sprd_host->sd_power_mode == mode && sprd_host->sd_power_vdd == vdd)
\t\treturn;

\tswitch (mode) {
\tcase MMC_POWER_OFF:
\t\tif (sprd_host->fast_hotplug && card_present)
\t\t\tsdhci_sprd_fast_hotplug_disable(sprd_host);
\t\tret = mmc_regulator_set_ocr(mmc, mmc->supply.vmmc, 0);
\t\tmmc_regulator_disable_vqmmc(mmc);
\t\tbreak;
\tcase MMC_POWER_ON:
\t\tret = mmc_regulator_enable_vqmmc(mmc);
\t\tif (!ret && sprd_host->fast_hotplug && card_present)
\t\t\tsdhci_sprd_fast_hotplug_enable(sprd_host);
\t\tbreak;
\tcase MMC_POWER_UP:
\t\tret = mmc_regulator_set_ocr(mmc, mmc->supply.vmmc, vdd);
\t\tif (!ret && sprd_host->fast_hotplug) {
\t\t\t/* The factory enables VQMMC after VMMC has settled. */
\t\t\tusleep_range(200, 250);
\t\t\tret = mmc_regulator_enable_vqmmc(mmc);
\t\t}
\t\tif (!ret && sprd_host->fast_hotplug && card_present)
\t\t\tsdhci_sprd_fast_hotplug_enable(sprd_host);
\t\tbreak;
\t}
\tif (ret) {
\t\tsprd_host->sd_power_valid = false;
\t\tdev_err(mmc_dev(mmc), "slot power transition %u failed: %d\\n", mode, ret);
\t\treturn;
\t}
\tsprd_host->sd_power_mode = mode;
\tsprd_host->sd_power_vdd = vdd;
\tsprd_host->sd_power_valid = true;
}'''+source[end:]
    marker = 'Do not acknowledge a removable-slot voltage switch without hardware readback.'
    if marker not in source:
        start = source.index('static int sdhci_sprd_voltage_switch(')
        end = source.index('\n}', start)
        body = source[start:end]
        anchor = '\n\tif (IS_ERR(sprd_host->pinctrl))'
        if body.count(anchor) != 1:
            raise ValueError('Unknown SD voltage-switch path')
        body = body.replace(anchor, '''
\t/* Do not acknowledge a removable-slot voltage switch without hardware readback.
\t * Keep fixed-I/O eMMC and SDIO boards on their existing path. */
\tif (sprd_host->fast_hotplug && ios->signal_voltage == MMC_SIGNAL_VOLTAGE_180) {
\t\tif (IS_ERR(mmc->supply.vqmmc))
\t\t\treturn -EOPNOTSUPP;
\t\tret = regulator_get_voltage(mmc->supply.vqmmc);
\t\tif (ret < 0)
\t\t\treturn ret;
\t\tif (ret < 1700000 || ret > 1950000) {
\t\t\tdev_err(mmc_dev(mmc), "SD 1.8V switch read back %duV\\n", ret);
\t\t\treturn -EIO;
\t\t}
\t}
''' + anchor, 1)
        source = source[:start]+body+source[end:]
    path.write_text(source)


if __name__ == '__main__':
    import sys
    apply(sys.argv[1])
