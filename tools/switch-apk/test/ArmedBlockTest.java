import com.minikano.e5switch.ArmedBlock;

/**
 * Pins the arithmetic against the blocks this project actually ships.
 *
 * The armed block is the one in the packages (files/boot-misc-slot-b.bin, which
 * boot/build-boot-image.py derives from the device's own misc head), and the
 * "back to Android" block is the stock state read off a device.  If either the
 * layout or the checksum in ArmedBlock drifts, this fails.
 *
 *   javac -d /tmp/abtest src/com/minikano/e5switch/ArmedBlock.java test/ArmedBlockTest.java
 *   java -cp /tmp/abtest ArmedBlockTest
 */
public class ArmedBlockTest {

    private static final String STOCK =
            "5f61000042434142010200009f001e000000000000000000000000000be17146";
    private static final String ARMED_B =
            "5f62000042434142010200009e002f000000000000000000000000009bf8546d";

    public static void main(String[] args) {
        byte[] stock = unhex(STOCK);

        byte[] armed = ArmedBlock.armed(stock, 'b');
        check("arm slot b", ARMED_B, ArmedBlock.hex(armed));

        // Arming is idempotent, and arming from an already-armed block is the
        // same block (a device that was switched twice must not drift).
        check("arm slot b again", ARMED_B, ArmedBlock.hex(ArmedBlock.armed(unhex(ARMED_B), 'b')));

        byte[] back = ArmedBlock.armed(unhex(ARMED_B), 'a');
        check("back to slot a", STOCK, ArmedBlock.hex(back));

        // The octal form the device's printf '%b' receives has to decode to the
        // same 32 bytes.
        String escapes = ArmedBlock.octalEscapes(armed);
        StringBuilder rebuilt = new StringBuilder();
        for (String piece : escapes.substring(1).split("\\\\")) {
            rebuilt.append(String.format("%02x", Integer.parseInt(piece, 8)));
        }
        check("octal escapes", ARMED_B, rebuilt.toString());

        for (int offset : new int[] {4, 8, 9, 20, 28}) {
            byte[] corrupt = stock.clone(); corrupt[offset] ^= 1;
            try {
                ArmedBlock.armed(corrupt, 'b');
                throw new AssertionError("Accepted corrupt boot control at " + offset);
            } catch (IllegalArgumentException expected) { }
        }

        System.out.println("ArmedBlock: all checks passed");
    }

    private static void check(String what, String expected, String actual) {
        if (!expected.equals(actual)) {
            throw new AssertionError(what + ": expected " + expected + " got " + actual);
        }
        System.out.println("  ok " + what + " " + actual);
    }

    private static byte[] unhex(String hex) {
        byte[] out = new byte[hex.length() / 2];
        for (int i = 0; i < out.length; i++) {
            out[i] = (byte) Integer.parseInt(hex.substring(2 * i, 2 * i + 2), 16);
        }
        return out;
    }
}
