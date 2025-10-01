#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# LiveDepth — dev/beta release packager (no Apple dev account required)
# - Builds with PyInstaller (auto-bumps BUILD_NUMBER via LiveDepth.spec)
# - Reads version + build from the built app's Info.plist
# - Produces a versioned zip in ./release without touching dist/
# -----------------------------------------------------------------------------
set -euo pipefail

APP_NAME="LiveDepth"
SPEC_FILE="LiveDepth.spec"
DIST_APP="dist/${APP_NAME}.app"
PLIST="${DIST_APP}/Contents/Info.plist"
RELEASE_DIR="release"

# Optional: base marketing version if plist missing (last resort)
FALLBACK_VERSION="$(cat VERSION.txt 2>/dev/null || echo '0.9.0-beta')"
FALLBACK_BUILD="$(cat BUILD_NUMBER.txt 2>/dev/null || echo '0')"

# 1) Build (also bumps BUILD_NUMBER in the spec)
echo "🔨 Building with PyInstaller..."
pyinstaller "${SPEC_FILE}" --noconfirm

# 2) Verify the app exists
if [[ ! -d "${DIST_APP}" ]]; then
  echo "❌ ${DIST_APP} not found. Build failed?"
  exit 2
fi

# 3) Read versions directly from the built app’s Info.plist
read_plist_key() {
  local key="$1"
  # Try PlistBuddy first (ships with macOS)
  if /usr/libexec/PlistBuddy -c "Print :${key}" "${PLIST}" &>/dev/null; then
    /usr/libexec/PlistBuddy -c "Print :${key}" "${PLIST}"
    return 0
  fi
  # Fallback to plutil (also on macOS)
  if plutil -extract "${key}" raw "${PLIST}" &>/dev/null; then
    plutil -extract "${key}" raw "${PLIST}"
    return 0
  fi
  return 1
}

APP_VERSION="$(read_plist_key CFBundleShortVersionString || echo "${FALLBACK_VERSION}")"
BUILD_NUMBER="$(read_plist_key CFBundleVersion || echo "${FALLBACK_BUILD}")"

# Normalize empties
[[ -z "${APP_VERSION}" ]] && APP_VERSION="${FALLBACK_VERSION}"
[[ -z "${BUILD_NUMBER}" ]] && BUILD_NUMBER="${FALLBACK_BUILD}"

echo "ℹ️  Version (CFBundleShortVersionString): ${APP_VERSION}"
echo "ℹ️  Build   (CFBundleVersion)           : ${BUILD_NUMBER}"

# 4) Stage a renamed .app just for zipping (don’t mutate dist/)
STAGING_DIR="$(mktemp -d)"
STAGED_APP="${STAGING_DIR}/${APP_NAME}-${APP_VERSION}-b${BUILD_NUMBER}.app"

echo "📦 Staging app as: ${STAGED_APP}"
cp -R "${DIST_APP}" "${STAGED_APP}"

# 5) Zip with ditto (preserves resource forks, correct macOS metadata)
mkdir -p "${RELEASE_DIR}"
ZIP_NAME="${APP_NAME}-v${APP_VERSION}-b${BUILD_NUMBER}-macOS.zip"
ZIP_PATH="${RELEASE_DIR}/${ZIP_NAME}"

echo "🧩 Creating zip: ${ZIP_PATH}"
ditto -c -k --sequesterRsrc --keepParent "${STAGED_APP}" "${ZIP_PATH}"

# 6) Cleanup staging
rm -rf "${STAGING_DIR}"

echo
echo "✅ Build app      : ${DIST_APP}"
echo "✅ Release zip    : ${ZIP_PATH}"
echo "👉 Share the zip with your testers."
echo "   (App remains unsigned; Gatekeeper instructions are in your README/RELEASE notes.)"
