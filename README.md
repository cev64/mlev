# mlev — NFL & Premier League prediction models

Well-calibrated prediction models for **NFL** and **Premier League** game lines
and player props, validated by walk-forward backtesting on historical seasons.

Every prediction is a probability or a full distribution, never a point pick.

**On a Mac, double-click `Start mlev.command`.** It sets everything up and opens
a local web app — see [GETTING_STARTED.md](GETTING_STARTED.md) for the
click-by-click version. The rest of this file is the technical detail.

> **No book integration.** Nothing here fetches odds from a sportsbook. What it
> does give you is every side of every market as a probability with a fair price,
> and an EV calculator you paste a price into — so you can compare against a book
> yourself without the project taking a dependency on one.
> `fetch_odds_data.py` still keeps accumulating odds snapshots for a future
> automated phase, and nothing in the pipeline imports it or reads what it writes.

---

## Layout

Sport is a top-level config, not a fork in the code. Both sports implement the
same five-stage interface (`core/pipeline.py`), so the entrypoints never branch
on which sport they are running.

```
core/                 sport-agnostic machinery
  config.py           paths + per-sport config (the SPORTS registry)
  odds.py             odds conversion, de-vigging, EV, Kelly
  markets.py          one fixture -> every bettable side, with fair prices
  elo.py              opponent-adjusted team ratings
  features.py         point-in-time rolling helpers — the anti-leakage layer
  distributions.py    Normal / Poisson / NegBinom / Bernoulli / Categorical / Scoreline
  models.py           estimators that all return distributions
  metrics.py          calibration first, accuracy second
  backtest.py         walk-forward engine + the TabularBundle model shape
  pipeline.py         the ingest -> clean -> feature -> model -> evaluate ABC
sports/nfl/           ingest, clean, features, models, pipeline, teams
sports/epl/           ... same, plus dixon_coles.py
data/<sport>/         raw / clean / features / models / predictions
tests/                leakage guards, distribution algebra, model behaviour
```

```
app/                  the local web UI (Flask + one HTML page)
  server.py           JSON API over the same pipeline the scripts use
  jobs.py             background job runner — a backfill outlives a HTTP request
  static/             the page itself
Start mlev.command    double-click launcher for macOS
Start mlev (phone).command   ...and one that also serves your local network

export_bundle.py      publish predictions the phone can work from, unaided
android/              native Kotlin/Compose app (see PRODUCT_SPEC.md)
  app/src/main/       domain (maths, markets) · data (Room, DataStore) · ui · widget
  tools/make-keystore.sh   creates the one persistent signing key
.github/workflows/    tests, signed release APK, scheduled prediction publishing
```

Entrypoints:

| Script | What it does |
|---|---|
| `Start mlev.command` | **double-click on a Mac** — sets up, launches the web app |
| `Start mlev (phone).command` | the same, also reachable from your phone |
| `export_bundle.py` | export prediction bundles for the Android app |
| `run_backfill.py` | pull raw data, rebuild clean + feature layers |
| `run_backtest.py` | walk-forward evaluation |
| `run_scoring.py` | score the upcoming week / matchday |
| `fetch_game_data.py` | single-purpose nflverse pull (kept from the original scaffold) |
| `fetch_odds_data.py` | odds snapshots — standalone, not wired into the pipeline |

The web app is a thin layer over exactly the same pipeline code. It has no
model logic of its own, so anything you can do in the UI you can do from the
command line and vice versa.

## Install

```bash
pip install -r requirements.txt
cp .env.example .env        # only needed for fetch_odds_data.py
```

Python 3.11+. Added over the original scaffold: `pandas`, `numpy`, `scipy`,
`scikit-learn`, `pyarrow`, `joblib`, `pytest`.

---

## Quick start

```bash
# NFL: ~10 seasons of nflverse data, then backtest
python run_backfill.py --sport nfl
python run_backtest.py --sport nfl --level game
python run_backtest.py --sport nfl --level player

# EPL: results + xG back to 2014/15
python run_backfill.py --sport epl
python run_backtest.py --sport epl --level game

# EPL player props need the opt-in Understat per-match backfill (see below)
python run_backfill.py --sport epl --with-players --player-seasons 2022 2023 2024 2025 2026
python run_backtest.py --sport epl --level player --first-test-season 2023
```

### Retraining

There is no separate "train" step to remember: `run_backtest.py` refits from
scratch on every fold, and `run_scoring.py` refits on all completed data before
predicting. To pick up new results, re-run the backfill (raw files are cached,
so only new seasons are fetched) and run the scoring job again:

```bash
python run_backfill.py --sport nfl          # add --force to refetch cached seasons
python run_scoring.py --sport nfl
```

### Scoring the upcoming week / matchday

```bash
python run_scoring.py --sport nfl                      # next unplayed week
python run_scoring.py --sport nfl --season 2026 --week 1
python run_scoring.py --sport nfl --level player
python run_scoring.py --sport epl
python run_scoring.py --sport epl --fixtures my_fixtures.csv
```

Output lands in `data/<sport>/predictions/<level>_<timestamp>.csv`. Game-line
rows carry win/draw/loss probabilities, an expected margin or supremacy **with
its standard deviation**, decile bounds, and `P(over line)` for the standard
lines. Player rows carry the same shape per stat.

For NFL, `--week` defaults to the single earliest unplayed week rather than the
rest of the season: the features for week 14 do not exist until weeks 1–13 have
been played, so scoring the whole remaining season would be meaningless.

For EPL, upcoming fixtures come from football-data's rolling near-term feed,
which only covers the next few days and is legitimately empty mid-week between
matchdays. Pass `--fixtures` with your own CSV (`Date,HomeTeam,AwayTeam`) to
score a specific matchday.

---

## Data sources

### NFL — nflverse

| Source | Used for |
|---|---|
| `import_schedules` | teams, kickoff, scores, rest days, roof/surface/weather, divisional flag |
| `import_pbp_data` | aggregated to team-week EPA/play and success rate |
| nflverse `stats_player` release | weekly player box scores — the base for prop targets |
| `import_snap_counts` | snap share (94.3% of player-weeks resolve via the gsis↔pfr crosswalk) |
| `import_injuries` | pregame practice report and game-status designation |

Play-by-play is streamed and aggregated rather than persisted — the full frame
is ~50k rows × 380 columns per season, and only the team-week summary is needed.

Weekly player stats are read straight from the nflverse `stats_player` release
rather than through `nfl_data_py.import_weekly_data`, which still points at the
retired `player_stats/` path and 404s on 2025 onward.

### EPL — football-data.co.uk (primary) + Understat (xG)

The spec asked for one primary underlying-performance source, documented.
**Understat**, because:

1. One request per season returns per-match xG for every fixture, via the same
   JSON endpoint the site's own front end calls. FBref needs one request per
   match.
2. FBref (sports-reference) returns HTTP 403 to non-browser clients and asks
   scrapers to throttle heavily; a 12-season backfill there is slow and impolite.
3. StatsBomb's free tier does not cover the Premier League broadly enough for a
   multi-season backtest.

football-data.co.uk carries the results plus shots, shots on target, corners,
fouls and cards — no scraping, no rate limit, uniform schema across seasons.

The two sources share no ID, so they are joined on **canonical club name + date
(±1 day)**. Current coverage: **100% of 4,570 matches** matched an Understat
record, and the clean step cross-checks that both sources report the same
scoreline — a mismatch aborts the run rather than producing a quietly wrong join.

Club names are normalised through an explicit alias map. An unmapped club (a
newly promoted side) **fails the run** rather than silently becoming a second,
history-less team.

---

## How leakage is prevented

This is the part most worth reviewing, because it is the one thing that would
make every number below meaningless.

1. **One rolling implementation.** Every "what has this team/player done
   recently?" feature goes through `core/features.py`, where each helper is
   `.shift(1)` *then* `.rolling()`. A row's features can only see rows strictly
   before it within its group. Tests assert that changing a row's own outcome
   never changes that row's own features.
2. **Walk-forward only.** `core/backtest.py` trains on seasons `< N`, tests on
   `N`, and rolls forward — and *asserts* the training fold's maximum season is
   below the test season on every fold, raising `LeakageError` if not.
3. **Hyperparameters tuned inside the training fold.** Regularisation strength
   is chosen by forward-chaining cross-validation on training data only
   (`LogisticRegressionCV`/`RidgeCV`), and Dixon-Coles's decay and xG blend by
   holding out the most recent *training* season. Picking these by looking at
   walk-forward scores would be fitting the backtest.
4. **A tripwire on the feature matrix.** `assert_no_lookahead` runs every time a
   feature table is built, rejecting an outcome column left in the model matrix
   or a feature near-perfectly collinear with an outcome.
5. **Thin history is dropped, not imputed.** A team's or player's first few
   games have no prior form; those rows are removed rather than filled in.

---

## Results

All figures are **out-of-sample**, from walk-forward validation. There is no ROI
here by design — no market data is wired in.

### NFL game lines — test seasons 2019–2025, n = 1,954 games

| Target | Metric | Model | Baseline |
|---|---|---|---|
| Home win | Brier | **0.2225** | 0.2486 (base rate) |
| Home win | Log loss | **0.6360** | — |
| Home win | Accuracy | **64.2%** | 55.0% (always home) |
| Home win | Calibration error (ECE) | **0.032** | — |
| Home margin | MAE / RMSE | **10.16** / 13.12 | — |
| Home margin | Bias | +0.03 | — |
| Total points | MAE / RMSE | **10.65** / 13.39 | — |

Derived spread markets, from the same margin distribution:

| Line | n | Brier | Base rate | Accuracy |
|---|---|---|---|---|
| Home −3 | 1,818 | **0.2154** | 0.2470 | 65.9% |
| Home −7 | 1,880 | **0.1895** | 0.2135 | 71.8% |
| Pick'em | 1,954 | **0.2223** | 0.2486 | 63.8% |
| Home +3 | 1,817 | **0.2119** | 0.2332 | 66.7% |

Every test season beats the base-rate Brier. Margin MAE around 10.2 points is in
the range a sharp market achieves, which is the sanity check that matters: a
model reporting MAE of 6 would be a leak, not a breakthrough.

### NFL player props — test seasons 2022–2025

| Prop | n | MAE | 80% interval coverage |
|---|---|---|---|
| Passing yards | 2,367 | 67.51 | 0.82 |
| Rushing yards | 4,856 | 23.51 | 0.85 |
| Receiving yards | 13,168 | 21.13 | 0.87 |
| Receptions | 13,168 | 1.58 | 0.85 |
| Scrimmage yards | 18,399 | 22.58 | 0.86 |
| Passing TDs | 2,367 | 0.88 | 0.87 |
| Scrimmage TDs | 18,399 | 0.36 | 0.87 |

Anytime touchdown: Brier **0.1520** vs 0.1672 base rate, accuracy 79.0%,
ECE **0.014**.

### EPL game lines — test seasons 2017/18–2026/27, n = 3,374 matches

| Target | Metric | Model | Baseline |
|---|---|---|---|
| 1X2 | Log loss | **0.990** | 1.065 (base rate) |
| 1X2 | Multi-class Brier | **0.589** | — |
| 1X2 | Accuracy | **52.1%** | 44.5% (always home) |
| Home / draw / away legs | ECE | **0.018 / 0.011 / 0.014** | — |
| Total goals | MAE | **1.31** | — |
| Supremacy | MAE | **1.35** | — |

Calibration is the strongest result here: across every probability bucket the
gap between predicted and observed never exceeds 0.03. The model beats the base
rate in all ten test seasons.

**Over/under and BTTS barely beat the base rate** (over 2.5: Brier 0.2465 vs
0.2477; BTTS 0.2493 vs 0.2490 — i.e. no better than the base rate). Totals are
genuinely hard, and the Poisson independence assumption limits how well BTTS can
be derived. Reported as-is rather than quietly omitted.

### EPL player props — test seasons 2024/25–2026/27

| Prop | n | MAE / Brier | Baseline |
|---|---|---|---|
| Goals | 11,837 | MAE 0.230 | — |
| Anytime scorer | 11,837 | Brier **0.1032** | 0.1095 |
| Assists | 19,328 | MAE 0.126 | — |
| Shots | 11,837 | MAE 0.952 | — |
| Carded | 19,328 | Brier **0.1194** | 0.1206 |

Anytime-scorer ECE 0.016; carded ECE 0.002.

---

## Expected value

`core/odds.py` and `core/markets.py` turn the model's probabilities into
something comparable to a posted price. Two traps this is built around:

1. **A book's prices do not sum to 100%.** The excess is its margin, so comparing
   your 55% against an implied 55% is comparing against a number that already has
   the house edge in it. `remove_vig` strips it. (The proportional method is used;
   it slightly over-taxes longshots, which is still far closer than not
   de-vigging.)
2. **A push is not a loss.** An NFL −3 spread lands on exactly 3 about 15% of the
   time and returns the stake. On a −110 price, treating those as losses reports
   −$12.18 per $100 where the truth is −$4.18. So `MarketSide` carries a push
   probability, and the number compared against the book is P(win | the bet
   resolves), not the raw win probability.

Every market emits **both sides**, and they are guaranteed to be complements —
the away price is one minus the home price and the push, not a separately fitted
number that can drift out of agreement.

`POST /api/ev` does the arithmetic server-side; the browser has a small mirror of
it so the calculator still works when the Mac is asleep.

## Models

### NFL
- **Game lines**: one `JointGameModel`. A margin model and a total model are
  fitted (ridge, with a *feature-dependent* standard deviation), and every
  market is read off them — moneyline is `P(margin > 0)`, each spread is
  `P(margin > line)` plus its push, each total the same. Fitting the three
  markets independently let them contradict each other: the previous version
  quoted a 0.679 moneyline beside a 0.662 `P(margin > 0)` for the same game.

  The predictive distribution is a **`LatticeDistribution`, not a Normal**, and
  that is what makes the push probabilities real. NFL margins are not smooth:
  14.7% of games are decided by exactly 3 points and 8.5% by exactly 7, because
  scores are built out of 3s and 7s. A Normal puts about 3% on each and *zero*
  on any exact value, so it cannot price a −3 line at all, where the push is the
  single biggest term. A `LatticeShape` learned from the training fold separates
  the two things a Normal conflates — where the mass sits (the regression's job,
  and it moves every game) from which values are intrinsically common (a
  property of football scoring, which barely moves). Measured against a Normal
  on the same fitted means, it halves calibration error on a −7 line
  (0.021 vs 0.044), and prices ties at 0.35% instead of 3%.

  `nfl_models.game_targets()` still exists and still works with `TabularBundle`
  if you want the three-independent-models behaviour back for a comparison run.
- **Player props**: Gaussian regression for yardage, Negative Binomial for
  receptions (reception counts are reliably overdispersed relative to Poisson),
  Poisson for touchdowns — so `prob_at_least(1)` gives the anytime-TD
  probability directly rather than needing a separate classifier that could
  disagree with it.

Swapping in gradient boosting is a constructor argument (`estimator="gbm"`),
wrapped in `CalibratedClassifierCV` because raw boosted trees are reliably
overconfident.

### EPL
A **Dixon-Coles bivariate Poisson** goal model:

```
home goals ~ Poisson(exp(base + attack_h + defence_a + gamma))
away goals ~ Poisson(exp(base + attack_a + defence_h))
```

plus the low-score correction `rho` and exponential time decay on match age.
1X2, Asian handicap (including quarter lines), over/under, BTTS and correct
score are all **derived from the same scoreline distribution**, so they cannot
contradict each other. Ratings are fitted on goals and on xG, and the two rate
predictions are blended.

Two things worth knowing about the implementation:

- `base` is a separate global scoring level. Without it, the only way to express
  "teams score about 1.4 goals a game" is through the attack and defence
  ratings, and the ridge penalty then deflates the whole league's scoring rate
  rather than just shrinking clubs toward each other.
- **`rho` fits to approximately zero on modern Premier League data.** The
  implementation is correct (unit-tested against the closed form); the data just
  does not support a large correction. Independent Poisson under-predicts 0-0 by
  about 8%, but it also under-predicts 1-0, and those two pull `rho` in opposite
  directions. Dixon & Coles fitted 1992–95 English league data, where scoring
  patterns differed.

---

## Known limitations

- **Opponent adjustment is only partial.** Elo ratings (`core/elo.py`) carry
  most of it — a rolling EPA average cannot tell good numbers against a weak
  schedule from the same numbers against a hard one, and every Elo update is
  scaled by who the opponent was. Adding Elo improved Brier (0.2230 → 0.2225),
  accuracy (63.7% → 64.2%) and margin MAE (10.18 → 10.16), though home-win
  calibration error ticked up slightly (0.026 → 0.032). The rolling EPA and
  points features around it are still schedule-blind.
- **League drift.** NFL passing yards per quarterback game fell from ~245 (2016)
  to ~201 (2025), so a model trained on older seasons over-predicts. Training
  rows are down-weighted by `0.5 ** (seasons_ago / 4)`; four seasons is roughly
  how long a roster, staff and scheme stay recognisable. A sensitivity check
  across half-lives of {none, 4, 2} moved passing-yards bias 8.30 → 7.21 → 6.36
  with MAE unchanged and coverage slowly eroding, so the default is a
  domain-reasoned choice that the check confirms is not harmful — not a value
  tuned against test scores.
- **NFL weather is recorded, not forecast.** nflverse fills `temp` and `wind`
  from what actually happened. Pregame you would have a forecast. The difference
  is small but real, and it makes weather-sensitive totals look slightly better
  in backtest than they would live.
- **NFL 80% intervals run about 77–80% on game lines** — very slightly
  overconfident. Player-prop intervals run 82–87%, i.e. conservative.
- **The NFL injury feature is weak by construction.** The weekly stats frame
  only contains players who actually played, so "ruled out" is almost never
  observed (0.01% of rows). The designation is informative about *whether*
  someone plays; this table is already conditioned on their having played.
- **EPL fixture congestion undercounts.** football-data covers league matches
  only, so a club playing midweek in Europe shows up as having *fewer* recent
  matches, not more. A cup/European fixture feed would fix this.
- **EPL shots on target is unavailable at player level.** Understat's match
  rosters carry total shots and xG but not the on-target split, and
  football-data only has it per team. Total shots is modelled instead — inventing
  a conversion rate would be worse.
- **EPL player props cover 2022/23 onward only.** The per-match backfill costs
  one Understat request per match; extending it further back is a matter of
  running `--with-players --player-seasons ...` for more seasons.
- **Newly promoted EPL clubs have no rating** and are predicted from a
  replacement-level prior (the weakest quartile of known clubs). Affected rows
  are flagged with `uses_replacement_rating` in the prediction output.
- **Over/under and BTTS do not beat the base rate**, and this is not a fixable
  modelling gap — the signal is not there. The best pregame feature (combined
  rolling xG form) correlates **0.13** with total goals, about 1.7% of the
  variance. Predicting a flat constant scores MAE 1.307 against the model's
  1.311, so the model is fractionally *worse* than a constant on totals. The
  1X2 market is where the EPL model actually earns its keep.
- **NFL team scores are point estimates only.** `exp_home_score` and
  `exp_away_score` come from the expected margin and total; there is no joint
  distribution over the two scores, so team-total markets are not priced. The
  margin and total distributions themselves are full distributions.

## Failure behaviour

Every data source raises `DataSourceError` rather than degrading to partial or
imputed data. An unreachable source, an empty response, a changed upstream
schema, an unmapped club name, a scoreline disagreement between sources, or an
xG join below 80% coverage all abort the run with an explanation of what to fix.

The one imputation in the project is the median-fill inside each fitted sklearn
pipeline, for the residual missing values that survive the thin-history filter.
That statistic is learned from the training fold only, so it cannot carry
information backwards from the test fold.

---

## The Android app

Native Kotlin / Jetpack Compose / Material 3. `PRODUCT_SPEC.md` covers the
screens and data model; this is the build and release side.

### Independence

The app needs no computer. The pipeline publishes a **prediction bundle** — each
fixture's predictive *distribution*, not a fixed list of probabilities — and the
phone derives every market from it on-device, including lines nobody
precomputed. A full NFL week is about 5 KB.

That is the whole reason `core/bundle.py` exports parameters rather than
answers, and the reason the distribution and odds maths are ported to Kotlin
(39 unit tests, checked against the Python model's own numbers).

### Building

```bash
cd android
./gradlew testDebugUnitTest      # unit tests
./gradlew assembleDebug          # installable, debug-signed
./gradlew assembleRelease        # release build
```

Requires the Android SDK and JDK 17. `local.properties` or `ANDROID_HOME` must
point at the SDK.

### Release signing

Android identifies an app by its **application id and its signing certificate**.
An APK signed with a different key cannot install over an existing one, and the
only way past that is uninstalling — which destroys the app's data. So there is
exactly one signing key, created once:

```bash
./android/tools/make-keystore.sh
```

It writes the keystore to `~/.mlev-signing/` (outside the repo, gitignored),
creates `android/keystore.properties` for local builds, and prints the four
GitHub secrets to add:

`ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`,
`ANDROID_KEY_PASSWORD`.

**Back the keystore up.** Losing it means losing the ability to update the
installed app, permanently. The release workflow refuses to build if the secret
is missing, rather than quietly producing a debug-signed APK that looks fine
until it will not install.

### Versioning

`versionName` is set by hand (`2.0.0`). `versionCode` is `2 + CI run number`, so
it only ever increases — Android rejects an install whose versionCode is not
higher than what is installed. A local build uses the base, so it can never
overtake a CI build and block a later update.

Release by tag:

```bash
git tag v2.1.0 && git push origin v2.1.0
```

which runs tests, builds, verifies the APK is not debug-signed, and attaches it
to the GitHub release.

### Upgrade in place

Three things must hold for a new APK to update the installed app rather than be
rejected:

1. same `applicationId` (`com.mlev.app` — permanent)
2. same signing certificate
3. higher `versionCode`

If an install is refused, that ordering is the checklist. **Uninstalling is a
last resort**, not a first fix: it deletes saved prices and settings.

Room migrations are non-destructive by policy, and
`fallbackToDestructiveMigration` is deliberately absent — a missing migration
should fail in testing rather than wipe a phone.

### Before trusting it with anything

Worth doing once, per `AGENT_INSTRUCTIONS.md`: install a build, type some
prices, add the widget, then build with a higher versionCode and install it
directly over the top. Confirm Android treats it as an update, the prices are
still there, and the widget still works.

---

## Tests

```bash
python -m pytest tests/ -q       # Python: pipeline, models, bundle contract
cd android && ./gradlew test     # Kotlin: distributions, scoreline, odds
```

101 tests. The leakage guards in `tests/test_point_in_time.py` and
`tests/test_elo.py` are the important ones — everything else measures how good
the models are; those check that the measurement is honest. Elo in particular is
the easiest feature here to leak with, because the natural way to write it uses
the result of the game being predicted.
