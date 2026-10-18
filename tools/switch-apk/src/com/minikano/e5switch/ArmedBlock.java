package com.minikano.e5switch;

import java.util.zip.CRC32;

/**
 * The 32-byte A/B boot control block of the Unisoc LK, as it lives at offset
 * 2048 of the misc partition.
 *
 * Layout (packed, little endian), the same one the vendor flashing tool writes
 * (spreadtrum_flash common.c: set_active / bootloader_control):
 *
 *   0..3   slot_suffix[4]      "5f 62 00 00" = 0x5F + "_b"
 *   4..7   magic               0x42414342 "BCAB"
 *   8      version             1            (the block's, 0x201 little endian)
 *   9..10  nb_slot:3 | recovery_tries_remaining:3 | merge_status:3  = 0x02 0x00
 *   11     reserved
 *   12..19 slot_info[4], 2 bytes each:
 *            priority:4 | tries_remaining:3 | successful_boot:1
 *            verity_corrupted:1 | reserved:7
 *   20..27 reserved
 *   28..31 crc32_le of bytes 0..27
 *
 * Arming a slot means: that slot gets priority 15 with tries to try and not
 * successful, the other one priority 14, successful and one try -- exactly what
 * `set_active b` writes, except that this project arms slot B with two tries
 * instead of six: one attempt, then LK rolls back to Android on its own.
 *
 * The values in the block shipped in the packages
 * (files/boot-misc-slot-b.bin, 5f62000042434142010200009e002f...9bf8546d) are
 * what {@link #armed} has to reproduce; the unit test in test/ pins that.
 */
public final class ArmedBlock {

    public static final int SIZE = 32;

    private ArmedBlock() {
    }

    /** Priority 15, tries 2, not successful: one Linux boot, then slot A again. */
    private static final int SLOT_ACTIVE = 0x2f;
    /** Successful Android, priority 14, one try: the fallback stays bootable. */
    private static final int SLOT_OTHER = 0x0e;

    /**
     * The block to write for a slot, based on the one already in misc.
     *
     * Bytes 0..11 are kept from the device (the vendor's magic and version are
     * the same everywhere, but nothing is invented here); only the slot suffix,
     * the two slot status bytes and the checksum change.
     */
    public static byte[] armed(byte[] current, char slot) {
        if (current == null || current.length != SIZE) {
            throw new IllegalArgumentException("misc boot control must be " + SIZE + " bytes");
        }
        if (slot != 'a' && slot != 'b') {
            throw new IllegalArgumentException("slot must be a or b");
        }
        if (current[4] != 'B' || current[5] != 'C' || current[6] != 'A' || current[7] != 'B'
                || current[8] != 1 || (current[9] & 7) != 2) {
            throw new IllegalArgumentException("启动控制块格式不正确，未切换。");
        }
        CRC32 previous = new CRC32(); previous.update(current, 0, 28);
        long checksum = 0;
        for (int i = 0; i < 4; i++) checksum |= (long) (current[28 + i] & 0xff) << (8 * i);
        if (previous.getValue() != checksum) {
            throw new IllegalArgumentException("启动控制块校验失败，未切换。");
        }
        byte[] block = current.clone();
        block[1] = (byte) slot;
        if (slot == 'b') {
            // a: keep its priority (14/15) and successful bit, one try left
            block[12] = (byte) ((block[12] & 0xf0) | SLOT_OTHER);
            block[14] = (byte) SLOT_ACTIVE;
        } else {
            // a: priority 15, one try, successful; b: back to priority 14, unusable
            block[12] = (byte) 0x9f;
            block[14] = (byte) 0x1e;
        }
        block[13] = 0;
        block[15] = 0;
        for (int i = 16; i < 28; i++) {
            block[i] = 0;
        }
        CRC32 crc = new CRC32();
        crc.update(block, 0, 28);
        long value = crc.getValue();
        for (int i = 0; i < 4; i++) {
            block[28 + i] = (byte) (value >>> (8 * i));
        }
        return block;
    }

    public static String hex(byte[] data) {
        StringBuilder out = new StringBuilder(data.length * 2);
        for (byte b : data) {
            out.append(String.format("%02x", b & 0xff));
        }
        return out.toString();
    }

    /** The block as an argument for the device's printf '%b' (octal escapes). */
    public static String octalEscapes(byte[] data) {
        StringBuilder out = new StringBuilder(data.length * 4);
        for (byte b : data) {
            out.append(String.format("\\%03o", b & 0xff));
        }
        return out.toString();
    }
}
