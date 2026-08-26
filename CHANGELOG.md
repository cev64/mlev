# Changelog

## Unreleased — fix: the text boxes

### Fixed
- **A typed price could not be trusted to stay typed.** Every price field was
  driven directly from the saved value in Room, which arrives back at least one
  suspending hop after the keystroke that caused it. Characters typed at any
  speed raced that write, so they were dropped or reordered and the cursor
  jumped to the end of whatever text arrived. Each field now owns its text
  while it is being edited and adopts the stored value only when it changes for
  some other reason — cleared from Settings, or a different fixture opened.
- **American odds could not be entered at all.** The price field asked for
  `KeyboardType.Number`, which is `TYPE_CLASS_NUMBER` with no sign flag: the
  keyboard it produces has no minus key, and almost every American price is
  negative. American odds now get the phone keypad, which has one; decimal odds
  keep the decimal pad, since decimal prices are never negative.
- **The row being typed into could vanish under a filter.** "Priced" and "+EV"
  re-evaluate on every keystroke, so clearing a box to retype it, or typing a
  price that was not yet positive, deleted the row the cursor was in and took
  the keyboard with it. The row being edited now stays until focus leaves it.
- **The stake box erased decimals as they were typed.** It was re-keyed on the
  saved stake and rendered through `toInt()`, so "12.50" became "12" the moment
  DataStore answered. It also pushed every keystroke through a setter that
  floors at 1, so an empty box saved a stake of 1. It now saves only a usable
  number and marks anything else as an error.
- **"Save and refresh" fetched from the previous address.** Saving and
  refreshing were launched as two independent coroutines; the refresh usually
  won and read the address DataStore had not yet been updated with. It is one
  action now, in that order.
- **A refresh with no screen attached used the default address.** `refresh()`
  read the URL from a `WhileSubscribed` state flow, whose value with no
  collector is still `Settings()` — so the refresh on launch downloaded from
  the default address rather than the user's. It reads from storage now.
- Done on the keyboard closes the keyboard, and the address field no longer
  offers autocorrect or a capital first letter.

- **Back closed the app from anywhere.** Nothing handled the back gesture, so a
  press exited outright — from Settings, from About, and from a fixture detail
  on a phone, where the detail is a page the user navigated to and back is the
  obvious way out of it. Back now returns to the markets from Settings and
  About, and to the fixture list from a detail. At the top of the app, and on
  widths that show the list and the detail together, it still leaves.
- **A sport with nothing published read as a broken setup.** An EPL bundle that
  is not there yet returned the same "no bundle published at that address"
  message as a wrong address, which sends people to change an address that
  works. A missing bundle for one sport now says so in its own words.

### Added
- `TextEntryTest` — types into the fields rather than only rendering them,
  including a store that never answers, which is what the render tests could
  never catch.
- `BackNavigationTest` — presses back on each screen, including the case that
  must keep working: back at the top of the app still closes it.

## 2.0.1 — fix: the app crashed on every launch

### Fixed
- **The app closed immediately on open.** `MainActivity` pinned
  `AndroidViewModelFactory`, which can only construct a ViewModel whose
  constructor is `(Application)` or `()`. `MlevViewModel` takes
  `(Application, SavedStateHandle)`, so creating it threw before the first
  frame — on every launch, every time. It now uses an explicit factory that
  names the constructor outright, so neither the reflective default nor R8 can
  break it.
- **`Application.onCreate` could throw.** Scheduling the background sync called
  `WorkManager.getInstance()`, which assumes the startup ContentProvider has
  already run. WorkManager is now initialised on demand via
  `Configuration.Provider`, and the scheduling call is wrapped — background sync
  is a convenience and must never be able to stop the app opening.
- Removed a `ColumnScope` workaround in the settings screen that prevented
  normal layout modifiers being used inside a settings card.

### Changed
- **Minification is off for this release.** R8's renaming and stripping depends
  on keep rules being exactly right for everything reached reflectively, and
  those failures appear only in the shipped build. The rules look correct and
  the mapping file confirms the serializers survive, but that is not
  verification. Two megabytes are not worth an unverifiable crash; it can be
  re-enabled once a build has been confirmed working on a device.

### Added
- `StartupTest` — launches the real Activity through `onCreate`, the theme, the
  splash handover and the first composition, and recreates it. This is the test
  that would have caught the crash; every existing test checked arithmetic,
  which is worth doing and catches nothing about launching.
- `ScreenRenderTest` — renders every screen, so a crash in Settings or About
  cannot reach a phone unnoticed.

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
