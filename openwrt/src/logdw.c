/*
 * logdw: a sink for Android's logd writer socket, so the vendor binaries of
 * the baseband chroot (liblog) can log on plain Linux (vendor-start.sh).
 *
 * Taken unchanged from mu300-linux, tools/logdw/logdw.c:
 *
 *   MIT License
 *
 *   Copyright (c) 2026 dikeckaan
 *
 *   Permission is hereby granted, free of charge, to any person obtaining a
 *   copy of this software and associated documentation files (the
 *   "Software"), to deal in the Software without restriction, including
 *   without limitation the rights to use, copy, modify, merge, publish,
 *   distribute, sublicense, and/or sell copies of the Software, and to permit
 *   persons to whom the Software is furnished to do so, subject to the
 *   following conditions:
 *
 *   The above copyright notice and this permission notice shall be included
 *   in all copies or substantial portions of the Software.
 *
 *   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
 *   OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
 *   MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
 *   NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
 *   DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
 *   OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE
 *   USE OR OTHER DEALINGS IN THE SOFTWARE.
 */
/* Minimal logd writer-socket sink: lets Android vendor binaries (liblog) log on plain Linux.
 * Binds /dev/socket/logdw (SOCK_DGRAM) and prints "time prio tag: msg" lines to stdout. */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : "/dev/socket/logdw";
    int fd = socket(AF_UNIX, SOCK_DGRAM, 0);
    struct sockaddr_un a = {.sun_family = AF_UNIX};
    strncpy(a.sun_path, path, sizeof(a.sun_path) - 1);
    unlink(path);
    if (fd < 0 || bind(fd, (struct sockaddr *)&a, sizeof(a)) < 0) { perror("logdw bind"); return 1; }
    chmod(path, 0222);
    setvbuf(stdout, NULL, _IOLBF, 0);
    static const char prios[] = "??VDIWEFS";
    unsigned char buf[5 * 1024];
    for (;;) {
        ssize_t n = recv(fd, buf, sizeof(buf) - 1, 0);
        /* android_log_header_t: id u8, tid u16, sec u32, nsec u32 = 11 bytes */
        if (n < 12) continue;
        buf[n] = 0;
        uint16_t tid; uint32_t sec;
        memcpy(&tid, buf + 1, 2); memcpy(&sec, buf + 3, 4);
        unsigned char *p = buf + 11;
        if (buf[0] == 2 /* events */ || buf[0] == 4 /* security */) continue;
        unsigned prio = p[0];
        char *tag = (char *)p + 1;
        char *msg = tag + strnlen(tag, (size_t)(buf + n - (unsigned char *)tag)) + 1;
        if ((unsigned char *)msg >= buf + n) msg = "";
        printf("%u %5u %c %s: %s\n", sec, tid, prio < sizeof(prios) - 1 ? prios[prio] : '?', tag, msg);
    }
}
