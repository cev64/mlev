#!/bin/bash
# Unit-test the parts of the Android app that do not need a device.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-/opt/android-sdk}}"
API="${ANDROID_API:-36}"
PLATFORM="$SDK/platforms/android-$API/android.jar"
OUT=build/test
rm -rf "$OUT" && mkdir -p "$OUT"
javac -nowarn -classpath "$PLATFORM" -d "$OUT" \
  src/com/mlev/app/MainActivity.java test/com/mlev/app/NormaliseTest.java \
  2>&1 | grep -v 'deprecat' || true
java -classpath "$OUT:$PLATFORM" com.mlev.app.NormaliseTest
