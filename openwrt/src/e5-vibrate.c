/*
 * e5-vibrate [ON_MS [OFF_MS ON_MS]...]  -- a vibration pattern on the E5
 *
 * The motor is the PMIC's (sc27xx-vibra, "sc27xx:vibrator"), a force-feedback
 * input device: one FF_RUMBLE effect, played for each ON_MS, with OFF_MS of
 * silence in between.  Default: 400 ms.  The driver takes the strength from
 * weak_magnitude alone (docs/FINDINGS.md 40), so both are set.
 *
 * E5_VIBRATOR=/dev/input/eventN overrides the lookup by name.
 */
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define NAME "sc27xx:vibrator"

static void sleep_ms(long ms)
{
	struct timespec ts = { ms / 1000, (ms % 1000) * 1000000L };
	while (nanosleep(&ts, &ts) < 0 && errno == EINTR)
		;
}

static int find_device(char *path, size_t len)
{
	const char *env = getenv("E5_VIBRATOR");
	if (env && *env) {
		snprintf(path, len, "%s", env);
		return 0;
	}
	DIR *d = opendir("/sys/class/input");
	if (!d)
		return -1;
	struct dirent *e;
	int found = -1;
	while (found < 0 && (e = readdir(d))) {
		if (strncmp(e->d_name, "event", 5))
			continue;
		char p[256], name[64] = "";
		snprintf(p, sizeof p, "/sys/class/input/%s/device/name", e->d_name);
		FILE *f = fopen(p, "r");
		if (!f)
			continue;
		if (fgets(name, sizeof name, f))
			name[strcspn(name, "\n")] = 0;
		fclose(f);
		if (!strcmp(name, NAME)) {
			snprintf(path, len, "/dev/input/%s", e->d_name);
			found = 0;
		}
	}
	closedir(d);
	return found;
}

static int play(int fd, int id, int on)
{
	struct input_event ev;
	memset(&ev, 0, sizeof ev);
	ev.type = EV_FF;
	ev.code = id;
	ev.value = on;
	return write(fd, &ev, sizeof ev) == sizeof ev ? 0 : -1;
}

int main(int argc, char **argv)
{
	char path[128];
	if (find_device(path, sizeof path) < 0) {
		fprintf(stderr, "e5-vibrate: no %s input device (sc27xx-vibra not loaded?)\n", NAME);
		return 1;
	}
	int fd = open(path, O_RDWR);
	if (fd < 0) {
		fprintf(stderr, "e5-vibrate: %s: %s\n", path, strerror(errno));
		return 1;
	}

	/* the pattern: on, off, on, ... in milliseconds, each 1..5000 */
	long pat[32];
	int n = 0;
	for (int i = 1; i < argc && n < 32; i++) {
		long v = strtol(argv[i], NULL, 10);
		pat[n++] = v < 1 ? 1 : v > 5000 ? 5000 : v;
	}
	if (!n)
		pat[n++] = 400;

	struct ff_effect e;
	memset(&e, 0, sizeof e);
	e.type = FF_RUMBLE;
	e.id = -1;
	e.u.rumble.strong_magnitude = 0xffff;
	e.u.rumble.weak_magnitude = 0xffff;
	e.replay.length = 5000;
	if (ioctl(fd, EVIOCSFF, &e) < 0) {
		fprintf(stderr, "e5-vibrate: EVIOCSFF: %s\n", strerror(errno));
		return 1;
	}

	int rc = 0;
	for (int i = 0; i < n; i++) {
		if (i % 2 == 0) {
			if (play(fd, e.id, 1) < 0) {
				rc = 1;
				break;
			}
			sleep_ms(pat[i]);
			play(fd, e.id, 0);
		} else {
			sleep_ms(pat[i]);
		}
	}
	ioctl(fd, EVIOCRMFF, e.id);
	close(fd);
	return rc;
}
