# Personal Android App — Master Agent Instructions

## Project Goal

Build a polished, native Android application intended primarily for my personal use on a **Samsung Galaxy Z Fold 8 Ultra**.

The exact purpose of the application may evolve over time. Build the project so features can be added, removed, and reorganized without requiring major architectural rewrites.

This is NOT intended to be a generic cross-platform app.

Prioritize:

1. Excellent Samsung Galaxy Z Fold 8 Ultra support
2. Native Android functionality
3. Modern UI
4. Performance
5. Reliability
6. Data preservation
7. Maintainable code
8. Easy GitHub-based development
9. Easy APK generation
10. Seamless APK updates without uninstalling the existing app

Do not artificially restrict functionality because something would be inappropriate for a mass-market Play Store application. This is a personal application installed on my own devices.

However, continue to follow Android security best practices and do not unnecessarily request sensitive permissions.

---

# Primary Reference Device

The **Samsung Galaxy Z Fold 8 Ultra** is the primary target and reference device for this project.

The Fold 8 Ultra experience takes priority over optimizing the application for every possible Android device.

Reasonable compatibility with other modern Android devices is desirable, but design compromises should not be made at the expense of the Fold 8 Ultra experience.

The app should specifically be tested and refined for:

- Fold 8 Ultra cover display
- Fold 8 Ultra inner display
- folding and unfolding
- portrait orientation
- landscape orientation
- Android multi-window
- split-screen usage
- resized windows where applicable

Do NOT rely on checking the device model name for normal UI layout decisions.

Use Android adaptive-window APIs and available window dimensions so the architecture remains technically sound.

The Fold 8 Ultra should simply be the primary reference device used when tuning those adaptive layouts.

---

# Technology Stack

Use:

- Kotlin
- Jetpack Compose
- Material 3
- Material 3 Adaptive where appropriate
- AndroidX
- Kotlin Coroutines
- Kotlin Flow / StateFlow
- ViewModel architecture
- Navigation Compose
- Room for structured persistent data when appropriate
- DataStore for preferences and lightweight settings
- WorkManager for reliable background work when appropriate
- Jetpack Glance for Android home-screen widgets
- Gradle Kotlin DSL

Prefer official Android and Jetpack libraries over third-party dependencies whenever practical.

Do not introduce a dependency simply to avoid implementing a small amount of straightforward functionality.

---

# Architecture

Use a clean, modular architecture.

Suggested structure:

app/
    data/
        local/
        remote/
        repository/

    domain/
        model/
        repository/
        usecase/

    ui/
        components/
        navigation/
        screens/
        theme/

    widgets/

    services/

    workers/

    utilities/

Do not over-engineer simple features.

The application should have clear separation between:

- UI
- application state
- business logic
- data persistence
- external APIs
- Android system integrations

UI composables should generally not directly perform networking, database operations, or complex business logic.

---

# Galaxy Z Fold 8 Ultra Design Philosophy

Do NOT simply create a normal phone interface and stretch it when the phone is unfolded.

Treat the Fold 8 Ultra as having multiple useful application environments.

---

# Cover Screen

Use a compact, focused interface.

Prioritize:

- one-column layouts
- quick actions
- glanceable information
- large touch targets
- minimal unnecessary navigation
- easy one-handed operation

Do not overcrowd the cover display.

The cover screen should feel like a complete and deliberate version of the application rather than a compromised tablet interface.

---

# Inner Display

Take advantage of the additional space.

Prefer layouts such as:

- list + detail
- dashboard + detail panel
- navigation rail + content
- two-pane interfaces
- three-column dashboards where useful
- master/detail layouts
- larger charts and data visualizations
- persistent supporting information

Do not simply make buttons, cards, text, and padding dramatically larger.

Use the additional space to display MORE useful information.

---

# Adaptive Layouts

Base layout decisions primarily on available window size rather than checking for a specific device model.

Use Android window size classes and adaptive APIs.

The application should gracefully react to:

- Fold 8 Ultra cover display
- Fold 8 Ultra unfolded inner display
- portrait
- landscape
- split screen
- floating or multi-window environments where applicable
- folding and unfolding while the application is already running

Changing display state should NOT require restarting the application.

Where useful, account for folding features, display posture, and hinge information.

---

# Fold Continuity

The application must maintain important state when I fold or unfold the Fold 8 Ultra.

For example:

If I am viewing:

Team
→ Player
→ Statistics

and unfold the device, I should still be looking at that player.

The larger interface may reveal additional panels or information, but my navigation state should remain intact.

Likewise, folding the device should intelligently collapse the interface rather than resetting it.

Preserve where appropriate:

- navigation state
- selected item
- text entry
- scroll position
- current filters
- current tab
- active workflow
- unsaved temporary state

---

# Navigation

Adapt navigation to screen size.

Possible behavior:

## Compact Layout

Use:

- bottom navigation
- navigation drawer
- compact top app bar

## Expanded Layout

Prefer:

- navigation rail
- persistent side navigation
- multi-pane layouts

Do not blindly use the same navigation component everywhere.

---

# Visual Design

Target a sleek, modern Samsung/Android aesthetic.

General design characteristics:

- clean
- minimal
- polished
- information-dense when appropriate
- subtle animations
- rounded cards where appropriate
- strong typography hierarchy
- consistent spacing
- modern Material 3 components
- excellent dark mode

Avoid:

- excessive gradients
- excessive shadows
- giant empty areas
- enormous headings
- web-page-looking UI
- unnecessary animations
- clutter
- unnecessary decorative elements

The app should feel like a premium native Android application.

---

# Dynamic Color

Support Android dynamic color where appropriate.

Also provide an application theme that still looks intentional when dynamic color is disabled.

Support:

- System
- Light
- Dark

Store the preference using DataStore.

---

# Android System Integration

Because this is a native personal Android application, take advantage of Android capabilities when they genuinely improve the experience.

Potential integrations include:

- notifications
- notification actions
- home-screen widgets
- Quick Settings tiles
- Android share sheet
- receiving shared content
- Android intents
- deep links
- app shortcuts
- clipboard
- camera
- photo picker
- location
- Bluetooth
- NFC
- biometric authentication
- vibration and haptics
- background work
- foreground services where legitimately required
- local files
- media controls
- picture-in-picture where appropriate

Do NOT add all of these automatically.

Use them when they provide genuine functionality for the application.

---

# Permissions

Use the minimum permissions necessary.

Permissions should be requested contextually.

Bad:

App opens
→ immediately requests several unrelated permissions

Good:

User selects a feature requiring location
→ explain why
→ request location permission

The application should continue functioning as much as possible when optional permissions are denied.

---

# Widgets

Architect the application so Android home-screen widgets can be added easily.

Use Jetpack Glance unless there is a strong technical reason not to.

Widgets should be designed separately from the main application's Compose UI.

Potential widget sizes:

- small
- medium
- large
- responsive/resizable configurations

Widgets should resize gracefully.

Useful widgets may include:

- status cards
- upcoming events
- quick actions
- statistics
- nutrition progress
- battery information
- sports scores
- progress indicators
- recent activity
- favorites
- dashboards

Widget interactions should deep-link into the relevant part of the application whenever appropriate.

Example:

Tapping a nutrition widget's "Add Food" button should open directly to the food-entry interface rather than only opening the application's home screen.

---

# Interactive Widgets

Where Android widget capabilities allow it, widgets should support useful direct interactions.

Examples:

- quick-add food
- increment a value
- mark an item complete
- refresh data
- open a specific detail screen
- toggle a supported app state
- launch a quick action

Do not require the main application to open for actions that can reasonably be completed from the widget itself.

---

# Widget Data Architecture

Widgets and the primary application should use the same underlying persistent data source whenever practical.

Example:

Room Database
    ↓
Repository
    ↓
Main App UI

and

Room Database
    ↓
Repository / Widget State
    ↓
Glance Widget

Do not maintain completely separate copies of important user data solely for widgets.

When underlying data changes, update affected widgets appropriately.

---

# Widget Persistence

Application updates must not intentionally destroy existing widget configuration.

When changing widget data structures or settings:

- preserve existing widget preferences where possible
- migrate old widget configuration when needed
- provide reasonable defaults for new settings
- avoid forcing widgets to be removed and re-added after every app update

If Android itself requires widget reconfiguration for a specific change, document that clearly.

---

# Quick Settings Tiles

If the application eventually contains functionality that would benefit from a quick toggle or action, consider implementing an Android Quick Settings tile.

Examples:

- toggle a mode
- start an activity
- trigger an automation
- refresh information
- enable or disable a feature

Do not add Quick Settings tiles merely for novelty.

---

# Notifications

Build notifications using proper Android notification channels.

Notifications should support useful actions when applicable.

Example:

EVENT STARTING

Chiefs vs Broncos
Starts in 15 minutes

[OPEN] [DISMISS]

Allow notification categories to be independently controlled where useful.

---

# Haptics

Use subtle haptic feedback for meaningful interactions.

Good examples:

- completing an action
- changing an important toggle
- selecting a major option
- drag/drop completion
- quick-add confirmation

Do not vibrate for every ordinary button press.

---

# Local-First Philosophy

Whenever practical, make the application local-first.

Core functionality should not fail just because internet access is unavailable.

Use Room for structured application data.

Use DataStore for preferences and lightweight settings.

The UI should read from local state whenever practical while remote data synchronizes separately.

---

# Offline Support

Where appropriate:

1. Load cached or local data immediately.
2. Fetch new data in the background.
3. Update local storage.
4. Automatically update the UI.
5. Update affected widgets where needed.

Do not make users stare at loading screens unnecessarily when usable cached data exists.

---

# Networking

When external APIs are needed:

- isolate networking from UI
- use typed models
- handle HTTP errors
- handle timeouts
- handle malformed responses
- handle rate limits
- handle offline conditions
- cache appropriate data
- provide useful error states

Never place secrets directly in the GitHub repository.

If an API requires a secret that cannot safely exist inside an APK, recommend an appropriate backend or proxy architecture instead.

---

# State Management

Use unidirectional data flow.

Prefer:

Repository
↓
ViewModel
↓
StateFlow
↓
Compose UI

UI actions should flow back through ViewModels or appropriate controllers.

Avoid large amounts of mutable global state.

---

# Configuration Changes

Preserve important state across:

- rotation
- resizing
- folding
- unfolding
- multi-window changes
- normal Activity recreation

Do not rely on Activity recreation to solve layout changes.

---

# Performance

Prioritize smooth performance.

Avoid:

- unnecessary recompositions
- blocking the main thread
- excessive network calls
- excessively large images
- repeatedly recalculating expensive values
- excessive polling
- unnecessary background services

Use coroutines appropriately.

Heavy work should not run on the main UI thread.

---

# Battery Usage

Because this is an always-installed personal application, avoid unnecessary battery drain.

Prefer:

- event-driven updates
- WorkManager
- sensible refresh intervals
- push/event mechanisms when available

over constant polling.

Widgets should not continuously wake the device merely to keep visually unimportant information perfectly current.

---

# Animations

Use animations primarily when they communicate spatial or state changes.

Example:

Cover screen:
single pane

↓

Unfold device

↓

detail panel appears beside existing content

Animations should generally be subtle and fast.

Do not make the app feel like a demo reel.

---

# Accessibility

Even though this is a personal application, follow good accessibility practices.

Include:

- meaningful content descriptions
- appropriate touch target sizes
- readable contrast
- support for font scaling where practical

---

# Orientation

Do not unnecessarily lock orientation.

Design the application to handle portrait and landscape intelligently.

If a specific feature genuinely benefits from locking orientation, document why.

---

# App Icon

Include proper adaptive Android launcher icons.

Provide:

- foreground layer
- background layer
- monochrome icon where supported

Make sure the icon works with themed Android icons.

---

# Splash Screen

Use Android's native splash screen system.

Keep it simple.

Do not create an artificial multi-second splash animation.

---

# Stable Application Identity

The application's `applicationId` is permanent once the first meaningful build is installed.

Example:

com.personal.nutrition

Do NOT change the application ID after normal usage begins unless I explicitly request the creation of a separate application.

Changing the application ID causes Android to treat the build as a different application instead of an update.

This could prevent seamless upgrades and separate the new application from existing data.

---

# Package Naming

Use a consistent namespace such as:

com.personal.[appname]

or another namespace specified later.

Choose the application ID carefully before the first real release.

Do not casually rename it later.

---

# Upgrade-in-Place Installation Requirement

A critical project requirement is that new APK builds must install as UPDATES to the existing application.

I should NOT normally need to uninstall the previous version before installing a new APK.

Updating the APK must preserve existing application data, including where applicable:

- Room databases
- DataStore preferences
- nutrition history
- saved foods
- saved meals
- user-created records
- saved settings
- application preferences
- widget configuration
- other persistent user data

The development and release process must be designed around this requirement from the beginning.

---

# Core APK Update Rules

Every APK intended to update the primary installed application must preserve three core properties:

1. Same application ID
2. Same compatible signing identity
3. Higher versionCode

Treat these requirements as critical.

If one of these is unintentionally changed, the update workflow may fail.

---

# Persistent Signing Identity

Every APK intended to update the installed application must use the SAME release signing identity.

The signing identity is part of the application's permanent update chain.

Do NOT:

- generate a new release signing key for every build
- casually replace the keystore
- sign normal releases using different certificates
- use unrelated signing keys between machines
- lose the signing key
- commit the private signing key to the public repository

Treat preservation of the release signing key as CRITICAL.

---

# Release Keystore

Create one persistent release keystore for this application.

Use the same signing identity for all normal future releases.

Store the keystore securely outside the normal Git repository.

Create at least one secure backup.

Document:

- keystore filename
- key alias
- how Gradle uses it
- which GitHub Actions secrets are required
- how to restore the signing setup if the development environment changes

Do NOT place passwords in source code.

Do NOT commit the release keystore to a public repository.

---

# GitHub Actions Signing

GitHub Actions release builds must use the persistent release signing identity.

Store sensitive signing information using GitHub Actions secrets.

Possible secrets may include:

ANDROID_KEYSTORE_BASE64
ANDROID_KEYSTORE_PASSWORD
ANDROID_KEY_ALIAS
ANDROID_KEY_PASSWORD

The workflow may reconstruct a temporary keystore during the build process from the secure secret.

The reconstructed keystore should only exist for the duration of the workflow.

Never print:

- keystore contents
- passwords
- signing keys
- secret values

to build logs.

---

# Versioning

Use understandable release version names.

Example:

1.0.0
1.1.0
1.1.1

Every build intended to update the installed application must also use a `versionCode` higher than the previously installed build.

Example:

versionCode = 1
versionName = "1.0.0"

Next:

versionCode = 2
versionName = "1.1.0"

Next:

versionCode = 3
versionName = "1.1.1"

Never reuse an old `versionCode` for a newer normal release.

Never reduce the normal release versionCode.

---

# Automatic Version Code Management

Prefer a release process that minimizes the chance of accidentally reusing a versionCode.

Acceptable approaches include:

- explicitly incrementing versionCode
- deriving versionCode from a controlled CI build number
- using another monotonically increasing release value

Whatever strategy is selected must guarantee that normal release version codes continue increasing.

Document the strategy in README.md.

---

# Debug vs Release Builds

Be careful when mixing debug and release builds.

Debug builds may use a different signing certificate from release builds.

That can interfere with upgrade-in-place behavior.

For builds I actually use day-to-day, prefer consistently signed personal release builds.

If rapid test builds should update the same installed application, configure a consistent signing strategy intentionally.

Do not casually switch between incompatible signing identities after meaningful data has accumulated.

---

# Experimental Builds

If an experimental version needs to coexist with the primary application, use a separate application ID suffix.

Example:

Primary:

com.personal.nutrition

Experimental:

com.personal.nutrition.experimental

This allows both builds to exist simultaneously without interfering with the primary application's data or update chain.

Experimental builds should not replace the normal installed application unless intentionally configured to do so.

---

# Data Preservation

Normal APK updates must preserve important application data.

Do NOT intentionally clear application storage during:

- startup
- application upgrade
- version changes
- database migration
- schema updates
- normal feature releases

Do NOT solve compatibility problems by deleting existing user data merely because that is easier.

Assume existing user-generated data is valuable.

---

# Room Database Migration Policy

If Room is used and the database schema changes, create proper migrations.

Example:

Database v1
↓
Install app update
↓
Migration 1 → 2
↓
Database v2

Do NOT use destructive migrations for meaningful user data unless I explicitly approve losing that data.

Do not default to destructive migration simply because migration code takes additional work.

Whenever the Room schema changes:

1. identify the old schema version
2. define the new schema version
3. create the necessary migration
4. test upgrading from the old schema
5. verify existing records remain intact
6. verify the application still launches correctly

---

# Database Migration History

Keep migration history organized.

Do not assume users will always update directly from the immediately previous release.

Where practical, support upgrade paths from older supported versions.

Example:

1 → 2
2 → 3
3 → 4

so a user on version 1 can ultimately reach version 4 without losing data.

---

# DataStore Compatibility

When modifying DataStore preferences:

- preserve existing keys where practical
- migrate renamed settings when necessary
- provide defaults for newly added settings
- do not clear the entire DataStore because one setting changed

Settings from previous app versions should continue functioning after updates.

---

# Saved User Data Compatibility

When persistent models change, explicitly consider backward compatibility.

Examples:

If a nutrition record previously contained:

- calories
- protein

and a later version adds:

- fiber

old records should remain valid.

The application should provide a safe default or migration path rather than deleting older entries.

---

# App Upgrade Testing

A release should NOT only be tested as a fresh installation.

It must also be tested as an update.

Important releases should test:

OLD INSTALLED APK
↓
existing user data
↓
install NEW APK over it
↓
launch application
↓
verify data remains intact

Verify:

- app opens normally
- Room database survives
- DataStore preferences survive
- logged data remains available
- saved items remain available
- widgets continue functioning
- widget configuration remains valid where possible
- theme selection survives
- settings survive
- migrations succeed
- new features initialize correctly

---

# Upgrade Test Data

Maintain representative test data for upgrade testing.

For a nutrition application, this might include:

- several days of nutrition logs
- calorie goals
- protein goals
- fiber goals
- saved foods
- saved meals
- widget preferences
- theme selection
- user settings

Install an older build containing representative data and verify that a new build updates it without losing anything.

---

# Fresh Install vs Update Testing

For meaningful releases, test BOTH workflows.

## Fresh Install

No existing application data.

Verify:

- app initializes correctly
- database is created correctly
- default settings are correct
- first-run experience works

## Upgrade Install

Existing previous-version installation containing data.

Verify:

- new APK installs over the old APK
- existing data survives
- migrations run successfully
- settings remain intact
- widgets remain functional
- application launches normally

Both scenarios must work.

---

# Critical Agent Rule — Never Solve Update Problems by Uninstalling

If a new APK refuses to install over the existing version, DO NOT immediately recommend uninstalling the existing application.

First investigate:

1. applicationId mismatch
2. signing certificate mismatch
3. versionCode problem
4. build variant mismatch
5. manifest changes
6. incompatible database migration
7. corrupted build artifact
8. accidental signing configuration changes

Uninstalling the existing application may destroy local user data.

Treat uninstalling as a LAST RESORT.

Never instruct me to uninstall an installed personal-data application without clearly warning that local data may be lost.

---

# First Upgrade Pipeline Test

Before I rely on the application for important personal data:

1. Create the permanent release signing identity.
2. Securely back up the signing key.
3. Configure GitHub Actions signing.
4. Build version 1.
5. Install version 1 on the Fold 8 Ultra.
6. Enter representative dummy data.
7. Build version 2 with a higher versionCode.
8. Install version 2 directly over version 1.
9. Confirm Android recognizes it as an update.
10. Confirm all dummy data remains intact.
11. Confirm widgets remain functional where applicable.

Do this BEFORE the application becomes important.

This validates the full upgrade path.

---

# Backup and Restore

Persistent user data should be designed with backups in mind.

Where appropriate, support Android's standard backup mechanisms.

For meaningful long-term data, also provide an explicit application-level backup system.

Possible interface:

Settings
→ Data
→ Export Backup

Support an appropriate portable format.

Examples:

- JSON for complete application backups
- CSV for user-readable tables

---

# Manual Data Export

If the application stores important long-term personal data, eventually provide:

- Export Data
- Import Data

For a nutrition tracker this could include:

- food history
- meals
- calorie records
- protein records
- fiber records
- daily goals
- saved foods
- preferences

Backups are an additional safety mechanism.

They do NOT replace proper upgrade behavior.

A normal APK update should preserve data automatically.

---

# Optional Automatic Backup Safety

Where technically appropriate and privacy-safe, consider Android-supported backup mechanisms as an additional protection layer.

Do not assume cloud backup will always be available.

Important local data should still have a manual export option when reasonable.

---

# APK Installation Workflow

The normal personal deployment workflow should be:

Coding agent modifies application
↓
changes pushed to GitHub
↓
GitHub Actions validates project
↓
APK built
↓
APK signed with persistent signing identity
↓
versionCode is higher than previous build
↓
download APK on Galaxy Z Fold 8 Ultra
↓
open APK
↓
Android recognizes existing application
↓
install update
↓
new version replaces old version
↓
existing application data remains intact

I should NOT normally have to:

Uninstall old application
↓
lose data
↓
install new application
↓
reconfigure everything

That is considered a broken deployment workflow.

---

# Release Validation Checklist

Before publishing a release APK, verify:

1. applicationId matches the existing primary app
2. signing identity matches previous normal releases
3. versionCode is greater than previous normal release
4. database migrations are valid
5. persistent data is not intentionally cleared
6. application builds successfully
7. tests pass
8. release APK is correctly signed
9. upgrade behavior has been considered
10. documentation has been updated where necessary

If these checks fail, do not describe the APK as a normal upgrade build.

---

# GitHub Repository

GitHub should be the source of truth for this project.

Maintain:

README.md
AGENT_INSTRUCTIONS.md
CHANGELOG.md

Potential additional documents:

PRODUCT_SPEC.md
ARCHITECTURE.md

Use meaningful commits.

Avoid committing:

- API secrets
- passwords
- signing passwords
- private signing keys
- release keystores intended to remain private
- unnecessary generated files
- IDE-specific junk

Configure `.gitignore` correctly for Android Studio and Gradle.

---

# GitHub Actions

Create a GitHub Actions workflow that validates and builds the Android project.

For normal commits or pull requests:

1. checkout repository
2. configure Java
3. configure Gradle
4. restore/cache dependencies where appropriate
5. run tests
6. run appropriate lint/build checks
7. compile application
8. build test APK as appropriate
9. upload the resulting APK as a GitHub Actions artifact

The workflow should fail when:

- compilation fails
- required tests fail
- critical lint/build checks fail

---

# Personal Testing APK Builds

Once meaningful personal data is stored in the app, APKs intended for installation over the primary app should use the established compatible signing identity.

Do not produce install instructions that accidentally require replacing the normal app with an incompatibly signed build.

If a build cannot update the primary application, clearly label it as such.

---

# Release APK Workflow

Create a workflow for normal release builds.

Preferred trigger:

GitHub Release or version tag.

Example:

v1.2.0

Workflow:

Git tag
↓
GitHub Actions
↓
Build release APK
↓
Sign APK with persistent signing identity
↓
Verify APK
↓
Run relevant checks
↓
Attach APK to GitHub Release

Target output:

app-v1.2.0.apk

---

# APK Signing

Release builds must use the persistent signing identity.

Never generate a new release key simply because GitHub Actions is running on a new environment.

The signing material must persist independently of an individual CI runner.

Back up the signing key securely.

---

# Installation Identity Validation

The agent should understand that Android application identity depends on more than the visible app name.

Do not change the update identity merely because:

- app display name changes
- icon changes
- branding changes
- package directories are reorganized

Preserve the actual installed app identity unless explicitly instructed otherwise.

---

# Development Documentation

README.md should explain:

## What the app does

## Current features

## Primary target device

Samsung Galaxy Z Fold 8 Ultra

## Project architecture

## How to build locally

## How to generate an APK

## How GitHub Actions works

## How release signing works

## How upgrade-in-place installation works

## Versioning strategy

## Data migration strategy

## Backup/export options

## Required permissions

## External APIs

## Known limitations

## Planned features

---

# Agent Change Log

Maintain CHANGELOG.md.

Use categories such as:

Added
Changed
Fixed
Removed

Example:

## 1.3.0

### Added
- Home-screen nutrition widget
- Expanded Fold dashboard

### Changed
- Redesigned cover-screen navigation

### Fixed
- Saved meals disappearing after database migration
- Selected screen resetting after unfolding device

---

# Feature Development Process

When implementing a significant new feature:

1. Understand the feature.
2. Determine whether native Android functionality is useful.
3. Determine how it should behave on the Fold 8 Ultra cover screen.
4. Determine how it should behave on the Fold 8 Ultra inner screen.
5. Determine what happens while folding/unfolding.
6. Determine whether it should have a widget.
7. Determine whether background work is necessary.
8. Determine required permissions.
9. Determine persistent-data requirements.
10. Determine whether database changes require migrations.
11. Design data/state architecture.
12. Implement feature.
13. Test compact layout.
14. Test expanded layout.
15. Test folding/unfolding.
16. Test fresh installation when relevant.
17. Test upgrade installation when persistent data changed.
18. Run tests/build.
19. Update CHANGELOG.md.
20. Update README.md where functionality or architecture changed.

---

# UI Feature Rule

For every major new screen, explicitly consider THREE layouts/states.

## Compact

What should this look like on the Fold 8 Ultra cover screen?

## Expanded

What additional information or controls should appear on the Fold 8 Ultra inner display?

## Transition

What happens if the user unfolds or folds the phone while this screen is open?

Do not consider a major screen complete until all three have been addressed.

---

# Persistent Data Feature Rule

Whenever a new feature stores user data, explicitly consider:

1. Where is the data stored?
2. Does it survive application restarts?
3. Does it survive APK updates?
4. What happens if the schema changes later?
5. Does it need backup/export support?
6. Do widgets depend on it?
7. How will older versions of the data migrate?

Do not treat persistence as an afterthought.

---

# Feature Scope Rule

Do not implement massive speculative systems just because they may eventually be useful.

Build features incrementally.

Prefer:

working simple version
↓
test
↓
improve

over:

large unfinished architecture

---

# Refactoring Rule

Agents may refactor code when there is a clear architectural or maintenance benefit.

However:

Do not rewrite functioning sections of the application merely because another approach is stylistically preferable.

Preserve working behavior unless the refactor intentionally changes it.

Before refactoring persistent-data code, consider migration and backward-compatibility consequences.

---

# Dependency Rule

Before adding a dependency:

1. Determine whether Android or Jetpack already provides the functionality.
2. Verify the dependency is actively maintained.
3. Ensure it provides meaningful benefit.
4. Avoid libraries with excessive transitive dependencies for trivial functionality.

---

# Security Rule

Never:

- commit API keys
- commit passwords
- commit private signing keys
- commit release signing passwords
- disable certificate validation
- expose sensitive local information unnecessarily
- create insecure WebView JavaScript bridges
- request powerful Android permissions without a reason
- print secrets to CI logs

This remains true even though the application is only for personal use.

---

# WebView Rule

Prefer native Compose interfaces.

A WebView may be used when:

- integrating existing web content
- migrating an existing PWA
- embedding something specifically designed for the web
- a web-based component provides substantial development benefit

Do NOT use a WebView merely because HTML is easier.

If a WebView communicates with native Android code:

- expose the minimum bridge surface necessary
- validate incoming values
- do not expose powerful unrestricted native methods
- treat web content as untrusted unless fully controlled

The application should remain fundamentally native Android unless specified otherwise.

---

# Existing PWA Migration Rule

If this project is created from an existing PWA:

Do not assume browser `localStorage` or IndexedDB can automatically become the native app's long-term data layer.

Plan an explicit migration strategy if existing user data needs to move into native storage.

Once migrated, prefer a shared persistent data layer that can support:

- native application UI
- widgets
- notifications
- background jobs

without duplicating important user records.

---

# Future AI-Agent Instructions

Before making significant changes:

Read:

1. README.md
2. AGENT_INSTRUCTIONS.md
3. PRODUCT_SPEC.md if it exists
4. CHANGELOG.md
5. relevant source files
6. database migration history if persistence is involved

Do not assume architecture from filenames alone.

Inspect the existing implementation before modifying it.

When finished:

1. ensure the project compiles
2. run relevant tests
3. fix errors introduced by the changes
4. verify persistent-data compatibility where relevant
5. update CHANGELOG.md
6. update README.md when functionality changes
7. summarize files changed
8. explain important architectural decisions
9. mention any remaining issues
10. explicitly mention if an update may require special installation steps

---

# Do Not Leave Fake Implementations

Do not claim functionality exists when it is:

- hardcoded
- mocked
- placeholder-only
- visually represented but nonfunctional

If something is unfinished, clearly label it unfinished.

---

# No Silent Feature Removal

Do not remove existing functionality to make a new feature easier to implement unless specifically instructed.

If two systems conflict, preserve the existing functionality where possible and explain the conflict.

---

# No Silent Data Loss

Never intentionally discard existing user data without explicitly calling attention to it.

If a requested architectural change would require destructive migration:

1. explain why
2. investigate a non-destructive migration
3. prefer preserving data
4. only use destructive migration if explicitly approved

---

# Personal App Philosophy

This application is being built for one primary user.

Therefore optimize for:

- my workflows
- my preferences
- my Samsung Galaxy Z Fold 8 Ultra
- speed of iteration
- useful Android integration
- reliable persistent data
- seamless APK updates

Compatibility with every Android device is not a primary goal.

However, still use good adaptive Android architecture rather than hardcoding every UI measurement to one exact device resolution.

The Fold 8 Ultra should receive the best experience while the architecture remains technically sound.

---

# Current Application Idea

TBD

Do not invent the core purpose of the application.

When an application concept is chosen, create or update `PRODUCT_SPEC.md` describing:

- purpose
- primary user workflow
- major screens
- data sources
- stored data
- Android integrations
- widgets
- notifications
- background tasks
- Fold-specific behavior
- backup requirements
- migration requirements
- privacy considerations

---

# Initial Project Milestone

Until an application concept is chosen, establish a clean foundation capable of supporting future features.

The starter project should include:

- working Android application
- Kotlin
- Jetpack Compose
- Material 3
- adaptive application structure
- Fold 8 Ultra compact/expanded layout demonstration
- navigation foundation
- theme system
- dark/light/system themes
- DataStore preferences
- Room-ready architecture
- placeholder dashboard
- Settings screen
- About screen
- launcher icon structure
- native splash screen
- basic test infrastructure
- GitHub Actions build workflow
- APK artifact generation
- persistent release signing strategy
- versionCode strategy
- upgrade-in-place documentation
- basic data backup/export architecture planning
- documentation

Avoid building unnecessary domain-specific functionality until the actual application idea has been chosen.

The starter app should prove that:

- it builds
- it installs
- it runs correctly on the Galaxy Z Fold 8 Ultra
- it adapts between compact and expanded Fold layouts
- folding/unfolding does not reset important state
- GitHub Actions can generate an APK
- release signing is stable
- version codes can advance correctly
- a newer APK can install over an older APK
- existing test data survives an APK update

That becomes the foundation for everything built afterward.

---

# Mandatory Pre-Use Validation

Before using the application for meaningful long-term personal data, perform this test:

## Build 1

Install version 1 on the Samsung Galaxy Z Fold 8 Ultra.

Add representative dummy data.

Configure settings.

Add any available widget.

## Build 2

Increase versionCode.

Build using the same application ID.

Build using the same release signing identity.

Install the new APK directly over Build 1.

## Validate

Confirm:

- Android treats it as an update
- no uninstall is required
- application opens normally
- dummy data remains
- settings remain
- database remains intact
- migrations succeed
- widgets still work where applicable
- the Fold UI still behaves correctly

Do not begin relying on the application for valuable personal data until this update test succeeds.