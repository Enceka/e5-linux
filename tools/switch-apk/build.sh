#!/usr/bin/env bash
# Build op-system-switcher.apk with the SDK's own tools, no Gradle:
#   aapt2 compile/link -> javac -> d8 -> zipalign -> apksigner
#
#   ./build.sh                 uses ANDROID_HOME, or the SDK at /d/Android/Sdk
#   E5_BUILD_TOOLS=... E5_PLATFORM=... ./build.sh    pin other versions
#
# The unit test of the boot control block runs first and is not optional: it
# pins what the app writes against the blocks this project ships.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"

SDK=${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}
if [ -z "$SDK" ]; then
    for candidate in /d/Android/Sdk "$HOME/AppData/Local/Android/Sdk"; do
        [ -d "$candidate" ] && SDK=$candidate && break
    done
fi
[ -n "$SDK" ] || { echo "no Android SDK found: set ANDROID_HOME" >&2; exit 1; }
BT=${E5_BUILD_TOOLS:-$SDK/build-tools/35.0.0}
PLATFORM=${E5_PLATFORM:-$SDK/platforms/android-34}
JAR=$PLATFORM/android.jar
[ -f "$JAR" ] || { echo "no $JAR (set E5_PLATFORM)" >&2; exit 1; }
# the SDK tools are Windows executables: hand them Windows paths
JARW=$(cygpath -w "$JAR")
AAPT2=$BT/aapt2.exe
D8=$BT/d8.bat
ZIPALIGN=$BT/zipalign.exe
APKSIGNER=$BT/apksigner.bat
for tool in "$AAPT2" "$D8" "$ZIPALIGN" "$APKSIGNER"; do
    [ -e "$tool" ] || { echo "missing $tool (set E5_BUILD_TOOLS)" >&2; exit 1; }
done

rm -rf build
mkdir -p build/gen build/classes build/dex

echo "== 0/6 boot control block test"
javac -nowarn -d build/test src/com/minikano/e5switch/ArmedBlock.java test/ArmedBlockTest.java
java -cp build/test ArmedBlockTest
python test/test_switcher.py

echo "== 1/6 resources"
"$AAPT2" compile --dir res -o build/res.zip
"$AAPT2" link -o build/base.apk -I "$JARW" \
    --manifest AndroidManifest.xml \
    --min-sdk-version 24 --target-sdk-version 34 --java build/gen \
    build/res.zip

echo "== 2/6 java"
# A modern JDK cannot take android.jar as -bootclasspath (it would have to
# supply java.lang too): compile for release 8 against the JDK's own java.* and
# android.jar on the classpath, exactly what d8 then dexes.
# shellcheck disable=SC2046
javac --release 8 -nowarn -classpath "$JARW" -d build/classes \
    $(find src build/gen -name '*.java')

echo "== 3/6 dex"
jar cf build/classes.jar -C build/classes .
"$D8" --release --lib "$JARW" --output build/dex build/classes.jar

echo "== 4/6 assemble"
# relative paths: the helper is a Windows python, a /d/... $PWD confuses it
python - <<'PY'
import shutil, zipfile
shutil.copy('build/base.apk', 'build/unsigned.apk')
with zipfile.ZipFile('build/unsigned.apk', 'a', zipfile.ZIP_DEFLATED) as apk:
    apk.write('build/dex/classes.dex', 'classes.dex')
print('  classes.dex added')
PY

echo "== 5/6 align"
"$ZIPALIGN" -f 4 build/unsigned.apk build/aligned.apk

echo "== 6/6 sign"
KS=debug.keystore   # relative on purpose: a /d/... path means something else to the Windows tools
if [ ! -f "$KS" ]; then
    keytool -genkeypair -keystore "$KS" -storepass android -keypass android \
        -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
        -dname "CN=Android Debug,O=Android,C=US" >/dev/null 2>&1
fi
"$APKSIGNER" sign --ks "$KS" --ks-pass pass:android --key-pass pass:android \
    --v1-signing-enabled true --v2-signing-enabled true --v4-signing-enabled false \
    --out op-system-switcher.apk build/aligned.apk

"$APKSIGNER" verify --print-certs op-system-switcher.apk | head -3
"$AAPT2" dump badging op-system-switcher.apk \
    | grep -E "^package:|^application-label:|^launchable-activity:|^sdkVersion:|^targetSdkVersion:" | head -5
echo "APK: $HERE/op-system-switcher.apk"
echo "安装 / install: adb install -r op-system-switcher.apk"
python - <<'PY'
import hashlib, json
from pathlib import Path
files = [Path('AndroidManifest.xml'), *Path('src').rglob('*.java'), *Path('res').rglob('*')]
sources = {p.as_posix(): hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
           for p in sorted(files) if p.is_file()}
Path('op-system-switcher.json').write_text(json.dumps({
    'source': sources, 'binary_sha256': hashlib.sha256(Path('op-system-switcher.apk').read_bytes()).hexdigest()
}, indent=2) + '\n', encoding='utf-8', newline='\n')
PY
