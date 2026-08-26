# Getting started on a Mac

Everything below is the app. You do not need to open a terminal, and you do not
need to know any Python.

---

## 1. Get the code onto your Mac

If you have the GitHub app or `git`:

```bash
git clone https://github.com/cev64/mlev.git
cd mlev
```

If you would rather not use git: open the repository page on GitHub, click the
green **Code** button → **Download ZIP**, then double-click the ZIP in your
Downloads folder to unpack it.

## 2. Double-click `Start mlev.command`

Open the `mlev` folder in Finder and double-click **`Start mlev.command`**.

A Terminal window opens and the app takes it from there:

- finds Python (and tells you exactly what to install if you don't have it)
- builds an isolated environment inside the folder, so nothing else on your Mac
  is touched
- installs what it needs
- starts the app and opens `http://127.0.0.1:8733` in your browser

The first run takes a few minutes because it is installing packages. Every run
after that takes a couple of seconds.

**Leave the Terminal window open while you use the app.** Closing it stops the
app. To stop it deliberately, click the Terminal window and press `Ctrl+C`.

### If macOS refuses to open it

macOS blocks files downloaded from the internet. You will see
*"cannot be opened because it is from an unidentified developer."*

Fix it once, either way:

- **Right-click** `Start mlev.command` → **Open** → **Open** in the dialog. macOS
  remembers the choice.
- Or in Terminal, from inside the folder: `chmod +x "Start mlev.command"`

Nothing here phones home. The only network traffic is downloading NFL and
Premier League data from nflverse, football-data.co.uk and Understat.

---

## 3. Use it — four tabs, in order

### Tab 1 · Data

Press **Download & prepare data**. This pulls every season the models train on,
cleans it, joins the sources together, and builds the features.

- NFL: ~100 MB, a few minutes
- Premier League: ~15 MB, about a minute
- Tick **also fetch player-level data** for Premier League player props. It takes
  about ten minutes because it needs one request per match, and you only ever
  need to do it once.

You will see each file turn green as it lands. Run this again whenever you want
to pick up newly played fixtures — it only fetches what is new.

### Tab 2 · Backtest

Press **Run backtest**. This is the part that tells you whether any of this is
worth trusting.

It trains on every season before season N, predicts season N, then rolls
forward — so the numbers you see are what the model *would have done*, never
what it can do with hindsight.

Read it in this order:

1. **Brier score** — lower is better. The card tells you whether it beats simply
   guessing the base rate. If it does not, the model is worthless for that market.
2. **Calibration error** and the **calibration plot** — this is the one that
   matters most. A model can be accurate and still lie about its own confidence.
   On the dashed line, "70%" means it happened 70% of the time. Dots above the
   line mean the model was too cautious; below, too confident.
3. **80% interval hit rate** — should sit near 0.80. Much below and the model is
   overconfident about margins and yardage.

### Tab 3 · Predict

Press **Predict**. It trains on everything played so far, then predicts what has
not been played.

- **NFL** defaults to the next unplayed week. You can name a season and week.
- **Premier League** pulls upcoming fixtures automatically. That feed only covers
  the next few days, so mid-week it is often empty — just type the fixtures you
  want, one per line, as `DD/MM/YYYY, Home team, Away team`.

Every row is a probability or a distribution. There is no single "pick" anywhere,
by design.

Predictions are also written to `data/<sport>/predictions/` as CSV, so you can
open them in Excel or Numbers.

### Tab 4 · Edge

Both sides of every market as a percentage, with the fair price the model
implies. Type a book's price next to any side and you get the edge, the expected
value, and the Kelly stake.

Four numbers appear once you enter a price:

| | What it means |
|---|---|
| **Model %** | the chance the model gives that side. Where a push is possible this is the chance it wins *outright*, with the push listed separately |
| **Fair** | the price a book taking zero margin would post. Any real price is worse; the question is by how much |
| **Edge** | model minus the price you typed, after removing the push |
| **EV** | expected profit on your stake — the number that actually decides whether a price is worth taking |

Type **both** sides of a market and you also get a **no-vig** number. That is
the honest one: a book's two prices sum to more than 100%, and the excess is its
margin. Comparing against the raw implied number means comparing against a
figure that already has the house edge baked in.

Two things worth knowing:

- **A push is not a loss.** An NFL −3 spread lands on exactly 3 about 15% of the
  time and returns your stake. Treating those as losses would misprice the bet by
  roughly three to one — the app handles it, but it is why the "Model %" and the
  book's implied number are not directly comparable without the adjustment.
- **Kelly is an upper bound**, not a recommendation. It assumes the model's
  probability is exactly right, which it never is.

Prices you type are saved in the browser, so a half-finished session survives a
reload or the phone locking.

---

## Using it on your phone

The models need Python, pandas and about 100 MB of data, so they cannot run on a
phone. The phone is a client; your Mac does the work. Both need to be on the same
Wi-Fi.

### Start the Mac with phone access

Double-click **`Start mlev (phone).command`** instead of the usual one. It prints
an address and a QR code:

```
  On your phone, on the same Wi-Fi, open:
      http://192.168.1.42:8733
```

While it is running, anyone on your network can reach it. Use the plain
`Start mlev.command` when you only want it on the Mac.

### Install the Android app

`android/mlev.apk` in the repo is a ready-to-install app. Copy it to your phone
(AirDrop-equivalent, USB, Google Drive, or email it to yourself) and tap it.

Android will warn you about installing from an unknown source — that is expected
for any app not from the Play Store. Allow it for whichever app you are
installing from, then tap the file again.

On first launch it asks for your Mac's address. Type what the Terminal printed —
`192.168.1.42:8733`, or just `192.168.1.42` and it fills in the port. It
remembers it. **Long-press volume-down** to change it later, which you will need
if your Mac's address changes after rejoining the network.

### Why an app and not just a bookmark

A web app can normally be installed to the home screen and run full screen. That
needs a secure context — HTTPS — and your Mac serves plain HTTP on your Wi-Fi. So
"Add to Home Screen" would give you a browser tab with a nice icon, not a real
app. The APK has no such restriction: real icon, full screen, no browser chrome.

### When your Mac is asleep

The app keeps the last numbers you loaded and shows them with a note saying how
old they are. The EV calculator keeps working offline too — it does the same
arithmetic in the browser. What you cannot do offline is generate *new*
predictions, because that needs the models.

### On a foldable

The layout is built for it. Folded, each market side is three short lines and
nothing is truncated. Unfolded, fixtures go two columns. It reflows when you open
or close the phone, no restart needed.

---

## Reading the predictions

### NFL game lines

| Column | Meaning |
|---|---|
| `home_win_prob` | chance the home team wins |
| `tie_prob` | chance of a tie (rare, but not zero) |
| `home_margin_mean` / `_sd` | expected winning margin and how uncertain that is |
| `home_margin_p10` / `_p90` | 80% of the time, the margin lands between these |
| `home_cover_m3` | chance the home team wins by more than 3 |
| `home_push_m3` | chance the game lands on exactly 3 — the push |
| `total_points_mean` | expected combined score |
| `total_over_p47_5` | chance the combined score beats 47.5 |
| `exp_home_score` / `exp_away_score` | expected score for each side |

The `m` and `p` in a column name are minus and plus: `home_cover_m3` is the
−3 line, `total_over_p47_5` is over 47.5.

**The sd matters as much as the mean.** A predicted margin of +3 means something
very different when the sd is 9 versus 14.

### Premier League

| Column | Meaning |
|---|---|
| `p_home` / `p_draw` / `p_away` | the three-way result |
| `exp_home_goals` / `exp_away_goals` | expected goals for each side |
| `p_over_2_5` | chance of three or more goals |
| `p_btts` | chance both teams score |
| `p_ah_home_m1` | chance the home side covers a −1 handicap |
| `p_ah_push_m1` | chance it lands exactly on that handicap and stakes are returned |
| `likely_score` | the single most likely scoreline, and how likely |
| `uses_replacement_rating` | **1 means a newly promoted club with no history** — treat that row with more caution |

Every Premier League market comes from one underlying scoreline distribution, so
they can never contradict each other.

---

## What this does *not* do

It does not read sportsbook odds and it does not compute expected value. That is
deliberate — those come later, once the models are proven. What you are looking
at is the model's own opinion, with nothing to compare it against yet.

Two markets are honestly weak, and the app will show you this:

- **Premier League totals and both-teams-to-score** barely beat guessing. Total
  goals is close to unpredictable from pregame form.
- **NFL totals** are much weaker than NFL margins.

The 1X2 and moneyline markets are where the models actually earn their keep.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| "cannot be opened because it is from an unidentified developer" | Right-click the file → Open → Open |
| "Python 3.10 or newer is required" | Install Python from python.org, then double-click again |
| A red box in the app saying a download failed | Almost always the internet. Press the button again. |
| "no unplayed fixtures match that filter" | Re-run **Download & prepare data** to pick up a newly published schedule |
| Club name not recognised (Premier League) | A newly promoted club. Add it to `sports/epl/teams.py` |
| Port already in use | The launcher finds the next free port automatically |

The app deliberately fails loudly rather than guessing. If a data source is
unreachable, it stops and says so instead of filling the gap with something made
up.

---

## Using it from the command line instead

Everything the app does is also available as a script:

```bash
source .venv/bin/activate

python run_backfill.py --sport nfl
python run_backtest.py  --sport nfl --level game
python run_scoring.py   --sport nfl --season 2026 --week 1

python run_backfill.py --sport epl --with-players
python run_backtest.py  --sport epl --level game
python run_scoring.py   --sport epl --fixtures my_fixtures.csv

python -m pytest tests/ -q          # 101 tests
python -m app.launch                # the web app, without the launcher
python -m app.launch --lan          # ...also reachable from your phone
```

Rebuilding the Android app (needs the Android SDK, which the repo does not
include — `android/mlev.apk` is prebuilt, so you only need this if you change the
app):

```bash
ANDROID_HOME=~/Library/Android/sdk ./android/build-apk.sh
./android/run-tests.sh
```
