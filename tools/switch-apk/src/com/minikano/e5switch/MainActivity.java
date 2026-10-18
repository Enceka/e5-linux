package com.minikano.e5switch;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.os.Bundle;
import android.content.res.Configuration;
import android.view.ContextThemeWrapper;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Nothing but the dialog: tapping the icon puts up "switch to OpenWrt?" at once
 * (the activity itself is translucent, there is no screen behind it), a
 * confirmation runs the switch and reports what it wrote, and the activity
 * finishes.
 */
public class MainActivity extends Activity {

    private static final String TAG = "e5switch";
    private static final Pattern BLOCK = Pattern.compile("BC=([0-9a-f]{64})");

    private boolean busy;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        ask('b');
    }

    /** Every dialog is built with a dialog theme: the activity's own is translucent. */
    private AlertDialog window(String title, String message) {
        boolean dark = (getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
                == Configuration.UI_MODE_NIGHT_YES;
        return new AlertDialog.Builder(new ContextThemeWrapper(this,
                dark ? R.style.SwitchDialogDark : R.style.SwitchDialogLight))
                .setTitle(title)
                .setMessage(message)
                .create();
    }

    private void ask(final char slot) {
        final boolean linux = slot == 'b';
        AlertDialog dialog = window(linux ? "启动 OpenWrt？" : "启动 Android？",
                "仅切换下次启动，不改默认设置。");
        android.util.Log.i(TAG, "ask slot=" + slot);
        dialog.setButton(DialogInterface.BUTTON_NEUTRAL, linux ? "Android" : "OpenWrt",
                (d, w) -> ask(linux ? 'a' : 'b'));
        dialog.setButton(DialogInterface.BUTTON_NEGATIVE, "取消", (d, w) -> finish());
        dialog.setButton(DialogInterface.BUTTON_POSITIVE,
                "切换", (d, w) -> apply(slot));
        dialog.setOnCancelListener(d -> finish());
        dialog.show();
    }

    private void report(String title, String message, boolean offerReboot) {
        busy = false;
        AlertDialog dialog = window(title, message);
        if (offerReboot) {
            dialog.setButton(DialogInterface.BUTTON_NEGATIVE, "稍后", (d, w) -> finish());
            dialog.setButton(DialogInterface.BUTTON_POSITIVE, "现在重启", (d, w) -> {
                new Thread(() -> su("reboot")).start();
                finish();
            });
        } else {
            dialog.setButton(DialogInterface.BUTTON_POSITIVE, "好", (d, w) -> finish());
        }
        dialog.setOnCancelListener(d -> finish());
        dialog.show();
    }

    // ------------------------------------------------------------- the work

    private void apply(final char slot) {
        busy = true;
        final AlertDialog progress = window("正在切换", "请稍候…");
        progress.setCancelable(false);
        progress.show();
        new Thread(() -> {
            try {
                String read = su("BY=/dev/block/by-name; "
                        + "[ -b $BY/misc ] || { echo NO-MISC; exit 4; }; "
                        + "echo SLOT=$(getprop ro.boot.slot_suffix); "
                        + "echo BC=$(dd if=$BY/misc bs=1 skip=2048 count=32 2>/dev/null"
                        + " | od -An -tx1 | tr -d ' \\n')");
                if (read.contains("NO-MISC")) {
                    throw new IllegalStateException("找不到 misc 分区（这台设备不支持？）");
                }
                Matcher found = BLOCK.matcher(read);
                if (!found.find()) {
                    throw new IllegalStateException("读不到 misc 的启动控制块：\n" + read.trim());
                }
                if (!read.contains("SLOT=_a\n")) {
                    throw new IllegalStateException("当前不是 Android A 槽，停止切换。");
                }
                byte[] wanted = ArmedBlock.armed(unhex(found.group(1)), slot);
                // Only misc is changed. Root selection and persistent defaults
                // belong to the running OpenWrt, never an Android mount.
                String written = su("set -e; BY=/dev/block/by-name; "
                        + "tmp=$(mktemp /data/local/tmp/e5-switch-bc.XXXXXX); "
                        + "trap 'rm -f \"$tmp\"' EXIT; "
                        + "printf '%b' '" + ArmedBlock.octalEscapes(wanted)
                        + "' > \"$tmp\"; "
                        + "dd if=\"$tmp\" of=$BY/misc bs=1 seek=2048 count=32"
                        + " conv=notrunc,fsync 2>/dev/null; "
                        + "echo BC=$(dd if=$BY/misc bs=1 skip=2048 count=32 2>/dev/null"
                        + " | od -An -tx1 | tr -d ' \\n')");
                Matcher check = BLOCK.matcher(written);
                final String expect = ArmedBlock.hex(wanted);
                if (!check.find() || !expect.equals(check.group(1))) {
                    android.util.Log.e(TAG, "misc verification mismatch: " + written.trim());
                    throw new IllegalStateException("启动设置校验失败，请勿重启。");
                }
                final String title = "已选择 " + (slot == 'b' ? "OpenWrt" : "Android");
                runOnUiThread(() -> {
                    progress.dismiss();
                    report(title, "现在重启？", true);
                });
            } catch (final RuntimeException error) {
                runOnUiThread(() -> {
                    progress.dismiss();
                    report("切换未完成，请勿重启", String.valueOf(error.getMessage()), false);
                });
            }
        }).start();
    }

    // ---------------------------------------------------------------- the su

    /** Run a script as root; never throws, the output carries everything. */
    private String su(String script) {
        StringBuilder out = new StringBuilder();
        try {
            Process process = Runtime.getRuntime().exec(new String[] {"su", "-c", script});
            BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()));
            String line;
            while ((line = reader.readLine()) != null) {
                out.append(line).append('\n');
            }
            reader.close();
            BufferedReader errors = new BufferedReader(new InputStreamReader(process.getErrorStream()));
            while ((line = errors.readLine()) != null) {
                out.append(line).append('\n');
            }
            errors.close();
            int code = process.waitFor();
            if (code != 0 && out.indexOf("BC=") < 0) {
                out.append("exit ").append(code);
            }
        } catch (Exception error) {
            out.append("su 不可用（Magisk 里给这个 app 授权）：").append(error);
        }
        return out.toString();
    }

    private static byte[] unhex(String hex) {
        byte[] out = new byte[hex.length() / 2];
        for (int i = 0; i < out.length; i++) {
            out[i] = (byte) Integer.parseInt(hex.substring(2 * i, 2 * i + 2), 16);
        }
        return out;
    }
}
