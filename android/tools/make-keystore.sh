#!/bin/bash
# Create the ONE persistent release signing key for this app.
#
#   ./android/tools/make-keystore.sh
#
# Run this once, on your Mac. Never run it again unless you have deliberately
# decided to start a new update chain.
#
# Why it matters: Android identifies an app by its application id AND its signing
# certificate. An APK signed with a different key cannot install over an existing
# one — the only way past that is uninstalling, which destroys the app's data.
# Losing this key means losing the ability to update the installed app, forever.
#
# The keystore is written outside the repository and must stay out of it.

set -euo pipefail

DEFAULT_DIR="$HOME/.mlev-signing"
KEYSTORE_DIR="${MLEV_KEYSTORE_DIR:-$DEFAULT_DIR}"
KEYSTORE="$KEYSTORE_DIR/mlev-release.jks"
ALIAS="mlev"

BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'; OFF=$'\033[0m'

if [ -f "$KEYSTORE" ]; then
  printf '%s\n' "${RED}A keystore already exists at $KEYSTORE${OFF}"
  printf '%s\n' "Refusing to overwrite it. Replacing this file would break your"
  printf '%s\n' "ability to update the app already installed on your phone."
  printf '\n%s\n' "If you genuinely want a new one, move the old file aside first."
  exit 1
fi

printf '%s\n\n' "${BOLD}Creating the mlev release signing key${OFF}"
read -r -s -p "Choose a password for the keystore (remember it): " PASSWORD; echo
read -r -s -p "Type it again: " CONFIRM; echo
if [ "$PASSWORD" != "$CONFIRM" ]; then
  printf '%s\n' "${RED}Passwords did not match.${OFF}"; exit 1
fi
if [ ${#PASSWORD} -lt 8 ]; then
  printf '%s\n' "${RED}Use at least 8 characters.${OFF}"; exit 1
fi

mkdir -p "$KEYSTORE_DIR"
chmod 700 "$KEYSTORE_DIR"

keytool -genkeypair \
  -keystore "$KEYSTORE" \
  -storetype PKCS12 \
  -storepass "$PASSWORD" \
  -keypass "$PASSWORD" \
  -alias "$ALIAS" \
  -keyalg RSA -keysize 4096 \
  -validity 10950 \
  -dname "CN=mlev, OU=personal, O=mlev, L=local, S=local, C=US" >/dev/null 2>&1

chmod 600 "$KEYSTORE"

# Gradle reads this; it points at the keystore and is itself gitignored.
PROPERTIES="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/keystore.properties"
cat > "$PROPERTIES" <<PROPS
storeFile=$KEYSTORE
storePassword=$PASSWORD
keyAlias=$ALIAS
keyPassword=$PASSWORD
PROPS
chmod 600 "$PROPERTIES"

printf '\n%s\n' "${GREEN}Done.${OFF}"
printf '  keystore    %s\n' "$KEYSTORE"
printf '  properties  %s  ${DIM}(gitignored)${OFF}\n' "$PROPERTIES"

printf '\n%s\n' "${BOLD}1. Back this up now${OFF}"
printf '%s\n' "Copy $KEYSTORE somewhere safe — a password manager attachment or an"
printf '%s\n' "encrypted drive. If you lose it you cannot update the installed app."

printf '\n%s\n' "${BOLD}2. Add these GitHub secrets${OFF}"
printf '%s\n' "${DIM}Settings > Secrets and variables > Actions > New repository secret${OFF}"
printf '  %s\n' "ANDROID_KEYSTORE_BASE64   (the command below prints it)"
printf '  %s\n' "ANDROID_KEYSTORE_PASSWORD $(printf '%*s' 0 '')the password you just chose"
printf '  %s\n' "ANDROID_KEY_ALIAS         $ALIAS"
printf '  %s\n' "ANDROID_KEY_PASSWORD      the same password"

printf '\n%s\n' "To print the base64 (it is long; copy all of it):"
printf '  %s\n' "base64 -i \"$KEYSTORE\" | pbcopy    ${DIM}# copies straight to your clipboard${OFF}"

printf '\n%s\n' "${DIM}Nothing above is printed to any build log. Keep it that way.${OFF}"
