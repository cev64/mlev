#!/bin/bash
# Build the mlev Android app.
#
#   ANDROID_HOME=/path/to/android-sdk ./android/build-apk.sh
#
# Uses the SDK's own command-line tools rather than Gradle, so there is no
# plugin resolution step and nothing to download at build time beyond the SDK
# itself. Produces a debug-signed APK, which is what you want for installing on
# your own phone; it is not suitable for the Play Store.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-/opt/android-sdk}}"
API="${ANDROID_API:-36}"
# Build-tools 34's d8 cannot read class files from a modern JDK, and targeting
# Java 8 to work around that trips a separate bug in its R8. 36.x reads them
# directly, which is the simpler fix.
BUILD_TOOLS_VERSION="${ANDROID_BUILD_TOOLS:-36.1.0}"
TOOLS="$SDK/build-tools/$BUILD_TOOLS_VERSION"
PLATFORM="$SDK/platforms/android-$API/android.jar"

for required in "$TOOLS/aapt2" "$TOOLS/d8" "$TOOLS/zipalign" "$TOOLS/apksigner" "$PLATFORM"; do
  if [ ! -e "$required" ]; then
    echo "Missing: $required" >&2
    echo "Install the SDK, then: sdkmanager 'platforms;android-$API' 'build-tools;$BUILD_TOOLS_VERSION'" >&2
    exit 1
  fi
done

OUT="build"
rm -rf "$OUT"
mkdir -p "$OUT/compiled" "$OUT/classes" "$OUT/dex"

echo "[1/6] compiling resources"
find res -type f | while read -r file; do
  "$TOOLS/aapt2" compile "$file" -o "$OUT/compiled" >/dev/null
done

echo "[2/6] linking resources"
"$TOOLS/aapt2" link \
  -o "$OUT/base.apk" \
  -I "$PLATFORM" \
  --manifest AndroidManifest.xml \
  --java "$OUT/gen" \
  --min-sdk-version 24 \
  --target-sdk-version "$API" \
  "$OUT"/compiled/*.flat

echo "[3/6] compiling java"
mkdir -p "$OUT/gen"
javac -nowarn -classpath "$PLATFORM" -d "$OUT/classes" \
  $(find src "$OUT/gen" -name '*.java') 2>&1 | grep -v 'deprecat' || true

echo "[4/6] dexing"
"$TOOLS/d8" --lib "$PLATFORM" --min-api 24 --output "$OUT/dex" \
  $(find "$OUT/classes" -name '*.class') >/dev/null

echo "[5/6] packaging"
cd "$OUT" && zip -q -j base.apk dex/classes.dex && cd ..
"$TOOLS/zipalign" -f 4 "$OUT/base.apk" "$OUT/aligned.apk"

echo "[6/6] signing"
KEYSTORE="${MLEV_KEYSTORE:-$OUT/debug.keystore}"
if [ ! -f "$KEYSTORE" ]; then
  keytool -genkeypair \
    -keystore "$KEYSTORE" -storepass android -keypass android \
    -alias mlev -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=mlev, OU=local, O=mlev, L=local, S=local, C=US" >/dev/null 2>&1
fi
"$TOOLS/apksigner" sign \
  --ks "$KEYSTORE" --ks-pass pass:android --key-pass pass:android \
  --out mlev.apk "$OUT/aligned.apk"

"$TOOLS/apksigner" verify --print-certs mlev.apk >/dev/null
echo
echo "  Built android/mlev.apk  ($(du -h mlev.apk | cut -f1))"
echo "  Copy it to your phone and open it to install."
