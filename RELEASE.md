# RELEASING

---

## A) Quick DEV/Test release (unsigned)

1. **Build the app**

```bash
pyinstaller LiveDepth.spec --noconfirm
```

Result: `dist/LiveDepth.app`

2. **(Optional) Ad-hoc sign** (reduces some warnings)

```bash
codesign --force --deep --sign - --options runtime "dist/LiveDepth.app"
```

3. **Zip it correctly** (this preserves bundle metadata; do NOT `zip -r`)

```bash
ditto -c -k --sequesterRsrc --keepParent "dist/LiveDepth.app" "LiveDepth-macOS.zip"
```

4. **Ship** the zip.
   Recipient will likely need to **Right-click → Open** the first time (Gatekeeper).

---

## B) Proper end-user release (Developer ID + Notarized)

**Prereqs:** Xcode CLI tools, Apple Developer account, a **Developer ID Application** certificate set up in Keychain.

1. **Build**

```bash
pyinstaller LiveDepth.spec --noconfirm
```

2. **Codesign** the app bundle (adjust the identity to your Developer ID)

```bash
codesign --force --deep --timestamp --options runtime \
  --sign "Developer ID Application: Your Company (TEAMID)" \
  "dist/LiveDepth.app"
```

3. **Verify signing** (should say “accepted” and show hardened runtime)

```bash
codesign --verify --deep --strict --verbose=2 "dist/LiveDepth.app"
spctl --assess --type execute --verbose "dist/LiveDepth.app"
```

4. **Create the notarization ZIP** (Apple wants a zip, not a dmg, for submit)

```bash
ditto -c -k --sequesterRsrc --keepParent \
  "dist/LiveDepth.app" "LiveDepth-macOS.zip"
```

5. **Notarize** (choose one auth method)

* Using a keychain profile (recommended):

```bash
xcrun notarytool submit "LiveDepth-macOS.zip" \
  --keychain-profile "AC_NOTARY_PROFILE" --wait
```

* Or with Apple ID creds:

```bash
xcrun notarytool submit "LiveDepth-macOS.zip" \
  --apple-id "you@domain.com" --team-id "TEAMID" --password "app-specific-password" --wait
```

6. **Staple** the ticket to the app:

```bash
xcrun stapler staple "dist/LiveDepth.app"
xcrun stapler validate "dist/LiveDepth.app"
```

7. **Final ship ZIP** (post-staple)

```bash
ditto -c -k --sequesterRsrc --keepParent \
  "dist/LiveDepth.app" "LiveDepth-macOS-notarized.zip"
```

---

## Optional: DMG instead of ZIP

ZIP is fine and Apple-approved. If you prefer a DMG:

```bash
hdiutil create -volname "LiveDepth" -srcfolder "dist/LiveDepth.app" \
  -ov -format UDZO "LiveDepth-macOS.dmg"
```

> If you distribute a DMG, codesign & notarize the **app** first (as above). You do **not** need to notarize the DMG when the contained app is already notarized & stapled.

---

## What to include in the release

* `LiveDepth-macOS.zip` (or `.dmg`)
* `README.md` (quick start + camera permissions note)
* License / credits as needed

---

## Notes specific to this project

* The app serves a local **HTTPS** UI using bundled localhost certs. First load may show a browser warning; your status-bar **Open Viewer** menu item already targets `https://127.0.0.1:8443`, which users can proceed to/trust locally.
* Logs go to: `~/Library/Logs/LiveDepth/LiveDepth.log`
* Build number auto-bumps (your `LiveDepth.spec` hooks). No Git required.

