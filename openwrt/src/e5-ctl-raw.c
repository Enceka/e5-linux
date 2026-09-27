/*
 * e5-ctl-raw: write one INTEGER mixer control by name, without amixer's clamp
 * to the declared maximum -- rootfs/overlay/opt/e5/e5-ctl-raw (Python) for a
 * system without Python (OpenWrt).
 *
 *   e5-ctl-raw 'DSP VBC Profile Select' 0x404B0000 [card]
 *
 * The VBC profile selects are declared with max 0x0fffffff, but the value is
 * (mode_offset << 24) | (param_id << 16) | dsp_case and Android writes e.g.
 * 0x404B0000; amixer clamps that to 0x0fffffff, which the kernel then applies
 * as dsp_case 0xffff.  The kernel's put() does not range-check, so the value
 * goes in through SNDRV_CTL_IOCTL_ELEM_WRITE directly.
 */
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <sound/asound.h>

int main(int argc, char **argv)
{
	struct snd_ctl_elem_value v, r;
	char path[32];
	long val;
	int card = 0, fd;

	if (argc < 3) {
		fprintf(stderr, "usage: %s NAME VALUE [card]\n", argv[0]);
		return 2;
	}
	val = strtol(argv[2], NULL, 0);
	if (argc > 3)
		card = atoi(argv[3]);
	snprintf(path, sizeof(path), "/dev/snd/controlC%d", card);
	fd = open(path, O_RDWR);
	if (fd < 0) {
		perror(path);
		return 1;
	}

	memset(&v, 0, sizeof(v));
	v.id.iface = SNDRV_CTL_ELEM_IFACE_MIXER;
	strncpy((char *)v.id.name, argv[1], sizeof(v.id.name) - 1);
	v.value.integer.value[0] = val;
	if (ioctl(fd, SNDRV_CTL_IOCTL_ELEM_WRITE, &v) < 0) {
		perror("write");
		return 1;
	}
	memset(&r, 0, sizeof(r));
	r.id.iface = SNDRV_CTL_ELEM_IFACE_MIXER;
	strncpy((char *)r.id.name, argv[1], sizeof(r.id.name) - 1);
	if (ioctl(fd, SNDRV_CTL_IOCTL_ELEM_READ, &r) < 0) {
		perror("read");
		return 1;
	}
	printf("%s: wrote %#lx, reads %#lx\n", argv[1], val,
	       (unsigned long)(r.value.integer.value[0] & 0xffffffffUL));
	close(fd);
	return 0;
}
