/*
 * blkgen: does the eMMC keep what it acknowledged as flushed?  (docs/FINDINGS.md 48, STATUS "Now")
 *
 *   blkgen DEV write GEN [DIRTY]  every data block with generation GEN in a random order, fdatasync, then
 *                                 GEN into the header as done, fdatasync; DIRTY more blocks with GEN+1
 *                                 after that, not flushed (the power cut then finds them either way)
 *   blkgen DEV verify             every data block against the header's done generation: ok (== done),
 *                                 newer (> done: written after the last flush, allowed), OLDER (< done:
 *                                 a flushed write lost), bad (not this tag or pattern: garbage, another
 *                                 block's data, torn); exit 0 only with no older and no bad block
 *   blkgen DEV cycle              the header's cycle count; blkgen DEV cycle N sets it
 *   blkgen DEV log TEXT           a line into the result log (the last MiB, outside the test area)
 *   blkgen DEV showlog            the result log
 *
 * Layout, 4 KiB blocks: 0 the header; 1 .. N-257 data; the last 256 blocks the log.  Through the page
 * cache and fdatasync, as a filesystem writes: the flush is the block layer's cache flush (REQ_PREFLUSH).
 * Destroys what DEV held: back it up first.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
#include <linux/fs.h>

#define BS 4096
#define LOG_BLOCKS 256
#define MAGIC 0x45354752454e4b31ull   /* "E5GRENK1" */
#define HMAGIC 0x4535474e48445231ull  /* "E5GNHDR1" */

struct tag { uint64_t magic, blk, gen, cycle; };
struct hdr { uint64_t magic, done, cycle, nblocks; };

static int fd;
static uint64_t nblk, ndata;   /* all blocks; data blocks are 1 .. ndata */

static void die(const char *what) { fprintf(stderr, "blkgen: %s: %s\n", what, strerror(errno)); exit(2); }

static uint64_t mix(uint64_t x)
{
	x ^= x >> 33; x *= 0xff51afd7ed558ccdull; x ^= x >> 33; x *= 0xc4ceb9fe1a85ec53ull; x ^= x >> 33;
	return x;
}

static void fill(uint64_t *b, uint64_t blk, uint64_t gen, uint64_t cycle)
{
	struct tag t = { MAGIC, blk, gen, cycle };
	memcpy(b, &t, sizeof t);
	uint64_t s = mix(blk * 0x9e3779b97f4a7c15ull ^ gen);
	for (size_t i = sizeof t / 8; i < BS / 8; i++)
		b[i] = s = mix(s + i);
}

/* 0 fine, 1 not this block's tag or pattern */
static int check(const uint64_t *b, uint64_t blk, uint64_t *gen)
{
	struct tag t;
	memcpy(&t, b, sizeof t);
	if (t.magic != MAGIC || t.blk != blk)
		return 1;
	uint64_t s = mix(blk * 0x9e3779b97f4a7c15ull ^ t.gen);
	for (size_t i = sizeof t / 8; i < BS / 8; i++)
		if (b[i] != (s = mix(s + i)))
			return 1;
	*gen = t.gen;
	return 0;
}

static void rd(void *b, uint64_t blk) { if (pread(fd, b, BS, blk * BS) != BS) die("read"); }
static void wr(const void *b, uint64_t blk) { if (pwrite(fd, b, BS, blk * BS) != BS) die("write"); }
static void flush(void) { if (fdatasync(fd)) die("fdatasync"); }

static struct hdr header(void)
{
	static uint64_t b[BS / 8];
	struct hdr h;
	rd(b, 0);
	memcpy(&h, b, sizeof h);
	if (h.magic != HMAGIC || h.nblocks != nblk)
		memset(&h, 0, sizeof h);
	return h;
}

static void put_header(struct hdr h)
{
	static uint64_t b[BS / 8];
	memset(b, 0, BS);
	h.magic = HMAGIC; h.nblocks = nblk;
	memcpy(b, &h, sizeof h);
	wr(b, 0);
}

static double now(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec / 1e9; }

static int do_write(uint64_t gen, uint64_t dirty)
{
	static uint64_t b[BS / 8];
	struct hdr h = header();
	uint64_t *order = malloc(ndata * sizeof *order);
	if (!order) die("malloc");
	for (uint64_t i = 0; i < ndata; i++)
		order[i] = i + 1;
	uint64_t r = mix(gen ^ (uint64_t)time(NULL));
	for (uint64_t i = ndata - 1; i > 0; i--) {   /* random order, as a filesystem's metadata goes out */
		r = mix(r + i);
		uint64_t j = r % (i + 1), x = order[i];
		order[i] = order[j]; order[j] = x;
	}
	double t0 = now();
	for (uint64_t i = 0; i < ndata; i++) {
		fill(b, order[i], gen, h.cycle);
		wr(b, order[i]);
	}
	double t1 = now();
	flush();
	double t2 = now();
	h.done = gen;
	put_header(h);
	flush();
	for (uint64_t i = 0; i < dirty && i < ndata; i++) {  /* after the last flush: may land or not */
		fill(b, order[i], gen + 1, h.cycle);
		wr(b, order[i]);
	}
	printf("write gen=%" PRIu64 " blocks=%" PRIu64 " write=%.1fs flush=%.1fs dirty=%" PRIu64 "\n",
	       gen, ndata, t1 - t0, t2 - t1, dirty);
	return 0;
}

static int do_verify(void)
{
	static uint64_t b[BS / 8];
	struct hdr h = header();
	uint64_t ok = 0, newer = 0, older = 0, bad = 0, gen, first_older = 0, first_bad = 0, oldest = UINT64_MAX;
	if (!h.magic) {
		printf("verify: no header (not written yet)\n");
		return 3;
	}
	double t0 = now();
	for (uint64_t blk = 1; blk <= ndata; blk++) {
		rd(b, blk);
		if (check(b, blk, &gen)) {
			if (!bad++) first_bad = blk;
		} else if (gen == h.done) {
			ok++;
		} else if (gen > h.done) {
			newer++;
		} else {
			if (!older++) first_older = blk;
			if (gen < oldest) oldest = gen;
		}
	}
	printf("verify cycle=%" PRIu64 " done=%" PRIu64 " ok=%" PRIu64 " newer=%" PRIu64 " OLDER=%" PRIu64
	       " bad=%" PRIu64 " read=%.1fs", h.cycle, h.done, ok, newer, older, bad, now() - t0);
	if (older) printf(" first_older=%" PRIu64 " oldest_gen=%" PRIu64, first_older, oldest);
	if (bad) printf(" first_bad=%" PRIu64, first_bad);
	printf("\n");
	return (older || bad) ? 1 : 0;
}

static int do_log(const char *text)
{
	static char buf[LOG_BLOCKS * BS];
	uint64_t base = nblk - LOG_BLOCKS;
	if (pread(fd, buf, sizeof buf, base * BS) != (ssize_t)sizeof buf) die("read log");
	size_t n = strnlen(buf, sizeof buf);
	if (memcmp(buf, "E5LOG\n", 6)) { memset(buf, 0, sizeof buf); strcpy(buf, "E5LOG\n"); n = 6; }
	size_t l = strlen(text);
	if (n + l + 2 >= sizeof buf) { memmove(buf + 6, buf + sizeof buf / 2, sizeof buf / 2); n = strnlen(buf, sizeof buf); }
	memcpy(buf + n, text, l); buf[n + l] = '\n';
	if (pwrite(fd, buf, sizeof buf, base * BS) != (ssize_t)sizeof buf) die("write log");
	flush();
	return 0;
}

static int do_showlog(void)
{
	static char buf[LOG_BLOCKS * BS + 1];
	if (pread(fd, buf, LOG_BLOCKS * BS, (nblk - LOG_BLOCKS) * BS) != LOG_BLOCKS * BS) die("read log");
	if (memcmp(buf, "E5LOG\n", 6)) { printf("(no log)\n"); return 0; }
	fputs(buf + 6, stdout);
	return 0;
}

int main(int argc, char **argv)
{
	if (argc < 3) {
		fprintf(stderr, "usage: blkgen DEV write GEN [DIRTY] | verify | cycle [N] | log TEXT | showlog\n");
		return 2;
	}
	fd = open(argv[1], O_RDWR);
	if (fd < 0) die(argv[1]);
	uint64_t bytes;
	struct stat st;
	if (ioctl(fd, BLKGETSIZE64, &bytes)) {   /* (a plain file: to test the tool itself) */
		if (fstat(fd, &st)) die("fstat");
		bytes = st.st_size;
	}
	nblk = bytes / BS;
	if (nblk < LOG_BLOCKS + 64) { fprintf(stderr, "blkgen: %s is too small\n", argv[1]); return 2; }
	ndata = nblk - LOG_BLOCKS - 1;
	const char *c = argv[2];
	if (!strcmp(c, "write") && argc >= 4)
		return do_write(strtoull(argv[3], NULL, 0), argc >= 5 ? strtoull(argv[4], NULL, 0) : 0);
	if (!strcmp(c, "verify"))
		return do_verify();
	if (!strcmp(c, "cycle")) {
		struct hdr h = header();
		if (argc >= 4) { h.cycle = strtoull(argv[3], NULL, 0); put_header(h); flush(); }
		printf("%" PRIu64 "\n", h.cycle);
		return 0;
	}
	if (!strcmp(c, "log") && argc >= 4)
		return do_log(argv[3]);
	if (!strcmp(c, "showlog"))
		return do_showlog();
	fprintf(stderr, "blkgen: unknown command %s\n", c);
	return 2;
}
