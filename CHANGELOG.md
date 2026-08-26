# Changelog

## 2.0.0 — native Android app

### Added
- **Native Kotlin/Compose app**, replacing the WebView shell. Material 3 with
  dynamic colour, system/light/dark themes, and an adaptive layout driven by
  window size rather than device model: bottom navigation and one pane when
  compact, navigation rail with list and detail side by side when expanded.
- **Runs without a computer.** The app downloads a published prediction bundle
  and computes every market on-device. See "Independence" in the README.
- `export_bundle.py` and `core/bundle.py` — export each fixture's predictive
  *distribution* rather than a fixed list of probabilities, so the phone can
  price a line nobody precomputed.
- Native ports of the distribution, scoreline and expected-value maths, checked
  against the Python model's own numbers (39 Kotlin tests).
- Room database for saved prices and notes; DataStore for settings.
- WorkManager periodic sync, and a Glance home-screen widget showing the best
  current edges, reading the same database as the app.
- GitHub Actions: Android build and test, tag-triggered signed release, and a
  scheduled job that runs the pipeline and publishes bundles to GitHub Pages.
- Persistent release signing via `android/tools/make-keystore.sh`, plus a
  monotonic versionCode derived from the CI run number.

### Changed
- The Android app no longer needs a computer on the same Wi-Fi. The Flask app
  and both `Start mlev.command` launchers are unchanged and still the way to run
  the pipeline, backtests and scoring on a Mac.
- Permissions reduced to `INTERNET` and `ACCESS_NETWORK_STATE`; the extra
  permissions WorkManager declares are removed in the manifest because this app
  uses none of the features that need them.

### Notes
- `applicationId` stays `com.mlev.app` and versionCode moves 1 → 2, so this
  installs as an update over the previous WebView build.
- **The WebView build's typed prices do not carry over.** They lived in the
  WebView's own browser storage, which a native app cannot read. Prices typed
  from 2.0.0 onward are in Room and survive every future update.

## 1.x — Python pipeline and local web app
- NFL and Premier League models with walk-forward backtesting.
- Local Flask UI, macOS launchers, and a WebView Android client.
- Expected-value tooling: fair odds, de-vigging, push-aware EV, Kelly.
