# mlev — product spec

## Purpose

Give one person a well-calibrated probability for every side of every NFL and
Premier League market, and let them compare it against a book's price on their
phone, wherever they are.

The modelling is settled (see README). This document covers the application.

## Primary workflow

1. A scheduled job trains the models and publishes a prediction bundle.
2. The phone downloads it, in the background, and stores it.
3. Standing in front of a betting slip, the user opens the app, finds the
   fixture, types the price a book is offering, and sees the edge and expected
   value.

Step 3 must work with no connection at all. That constraint drives the whole
architecture.

## Independence from any one computer

The models need Python, pandas and ~100 MB of historical data, so they cannot
run on a phone. They do not have to.

What the phone needs is the *shape* of each fixture's predictive distribution,
which is small:

- **NFL** — the fitted mean and standard deviation for margin and total, plus
  the lattice shape describing how football scores clump onto key numbers. That
  shape is a property of the sport, so it ships once per bundle rather than per
  fixture.
- **EPL** — the full scoreline grid. Every soccer market is a projection of it.

From those the app derives any market at any line, including lines the exporter
never precomputed. A full NFL week is about 5 KB.

## Major screens

| Screen | Compact (cover display) | Expanded (inner display) |
|---|---|---|
| **Markets** | Fixture list; tapping opens the detail as a page | List and detail side by side, so unfolding reveals more rather than the same thing stretched |
| **Settings** | Single column | Same, beside the navigation rail |
| **About** | The model's out-of-sample record | Same |

The fixture list leads with the best expected value found on any side of that
fixture, so it points at where the value is instead of requiring every game to
be opened.

### Transition

Folding and unfolding is a resize, not a restart. Selection, filter, scroll
position and half-typed prices live in the ViewModel and `rememberSaveable`, and
`configChanges` keeps the activity alive across the fold. State is correct even
when Android does recreate the activity.

## Data

| What | Where | Survives update | Backed up |
|---|---|---|---|
| Typed prices | Room (`prices`) | Yes | Yes |
| Fixture notes | Room (`notes`) | Yes | Yes |
| Cached bundle | Room (`bundles`) | Yes | Yes (re-downloadable anyway) |
| Settings | DataStore | Yes | Yes |

Typed prices are the only genuinely user-created data, so they are what
migrations must never lose. Room migrations are non-destructive by policy;
`fallbackToDestructiveMigration` is deliberately absent so a missing migration
fails in testing rather than wiping a phone.

## Android integration

| Used | Why |
|---|---|
| Glance widget | Best current edges at a glance; reads the same Room database |
| WorkManager | Periodic bundle refresh, network-constrained, never polling |
| Deep links (`mlev://`) | Widget taps open the relevant screen |
| Dynamic colour | Matches the system palette where available |
| Native splash screen | No artificial delay |
| Adaptive icon + monochrome | Works with themed icons |

Not used, because nothing here needs them: location, camera, Bluetooth, NFC,
biometrics, foreground services, notifications. Notifications are the most
plausible future addition — "a fixture you priced kicks off in 15 minutes" — and
would need a channel and a contextual permission request on Android 13+.

## Permissions

`INTERNET` and `ACCESS_NETWORK_STATE`. Nothing else, and nothing sensitive.

## Privacy

The app sends nothing anywhere. It makes one outbound request, a GET for a
public JSON file. Typed prices never leave the device.

## Known limitations

- Predictions are only as fresh as the last published bundle. Between
  publishes the numbers are static, which is correct — they only change when
  the models are retrained.
- The app cannot retrain or backtest. That is the pipeline's job.
- Premier League totals and both-teams-to-score do not beat the base rate. The
  About screen says so rather than hiding it.

## Planned

- Notifications for fixtures with a saved price.
- Fixture notes surfaced in the UI (the table exists; no screen yet).
- Export and import of saved prices as JSON.
