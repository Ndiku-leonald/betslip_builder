# SlipIQ real football model evaluation

Commissioning date: `2026-09-26T08:07:33.505181+00:00`

This report uses real API-Football fixture data only. No candidate was promoted automatically, no synthetic rows were used, and no profitability claim is made.

## Dataset audit

- Fixtures audited: **4358**; completed **2326**, scheduled **2014**, live/halftime **3**.
- Date coverage: `2024-07-09T15:30:00` to `2026-09-27T23:30:00`.
- Competitions represented: **340** canonical competitions. Largest groups: La Liga (380), Serie A (380), Premier League (380), Ligue 1 (308), Bundesliga (308), UEFA Champions League (279).
- Recorded seasons: 2024, 2025, 2026, 2027; fixtures missing season linkage: **0**.
- Duplicate provider identities: **0**; completed rows missing scores: **0**.
- Feature rows: **4358**, with sufficient five-match history **1657**; statistics coverage **0** rows. Quality range: `1.5`–`80.0`.

## Chronological evaluation

Calibration was fit only on the validation partition. The final test partition was not used for fitting or candidate selection.

| Candidate | Train | Validation | Test | Test 1X2 Brier | Test 1X2 log loss | Simple Elo Brier | Simple Elo log loss | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| dixon_coles | 1395 | 466 | 465 | 0.6563 | 1.1054 | 0.6261 | 1.0420 | not qualified |
| poisson | 1395 | 466 | 465 | 0.6563 | 1.1051 | 0.6261 | 1.0420 | not qualified |

### Candidate market metrics

#### dixon_coles (`football_dixon_coles_v1-20260926080403`)

| Market | N | Calibrated Brier | Calibrated log loss | ECE |
|---|---:|---:|---:|---:|
| home_win | 465 | 0.2482 | 0.7159 | 0.0700 |
| draw | 465 | 0.1668 | 0.5158 | 0.0390 |
| away_win | 465 | 0.2414 | 0.6980 | 0.0878 |
| btts_yes | 465 | 0.2490 | 0.6914 | 0.0381 |
| over_1_5 | 465 | 0.1701 | 0.5239 | 0.0581 |
| over_2_5 | 465 | 0.2508 | 0.6967 | 0.0473 |
| over_3_5 | 465 | 0.2346 | 0.6639 | 0.0782 |
| home_handicap_-0.5 | 465 | 0.2481 | 0.7152 | 0.0720 |
| home_handicap_+0.5 | 465 | 0.2418 | 0.7005 | 0.0827 |

Calibration buckets with observations:

```json
{
  "home_win": [
    {
      "lower": 0.5,
      "upper": 0.6,
      "count": 41,
      "mean_predicted": 0.559215724974707,
      "hit_rate": 0.4878048780487805,
      "difference": -0.07141084692592647
    },
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 19,
      "mean_predicted": 0.6355767296316992,
      "hit_rate": 0.5263157894736842,
      "difference": -0.10926094015801502
    },
    {
      "lower": 0.7,
      "upper": 0.8,
      "count": 15,
      "mean_predicted": 0.7531568503149497,
      "hit_rate": 0.6666666666666666,
      "difference": -0.08649018364828309
    },
    {
      "lower": 0.9,
      "upper": 1.00001,
      "count": 7,
      "mean_predicted": 0.9578406366565317,
      "hit_rate": 0.7142857142857143,
      "difference": -0.24355492237081744
    }
  ],
  "draw": [
    {
      "lower": 0.5,
      "upper": 0.6,
      "count": 7,
      "mean_predicted": 0.5309605956520882,
      "hit_rate": 0.42857142857142855,
      "difference": -0.10238916708065965
    }
  ],
  "away_win": [
    {
      "lower": 0.5,
      "upper": 0.6,
      "count": 29,
      "mean_predicted": 0.5431308481338423,
      "hit_rate": 0.3448275862068966,
      "difference": -0.1983032619269457
    },
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 18,
      "mean_predicted": 0.6462656587152582,
      "hit_rate": 0.4444444444444444,
      "difference": -0.2018212142708138
    },
    {
      "lower": 0.7,
      "upper": 0.8,
      "count": 3,
      "mean_predicted": 0.7576428965169489,
      "hit_rate": 0.6666666666666666,
      "difference": -0.09097622985028231
    },
    {
      "lower": 0.8,
      "upper": 0.9,
      "count": 3,
      "mean_predicted": 0.8639994637635949,
      "hit_rate": 1.0,
      "difference": 0.13600053623640507
    },
    {
      "lower": 0.9,
      "upper": 1.00001,
      "count": 9,
      "mean_predicted": 0.9352578474285225,
      "hit_rate": 0.2222222222222222,
      "difference": -0.7130356252063003
    }
  ],
  "btts_yes": [
    {
      "lower": 0.5,
      "upper": 0.6,
      "count": 371,
      "mean_predicted": 0.5414603461106371,
      "hit_rate": 0.555256064690027,
      "difference": 0.013795718579389882
    },
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 13,
      "mean_predicted": 0.6305921935121143,
      "hit_rate": 0.5384615384615384,
      "difference": -0.09213065505057583
    },
    {
      "lower": 0.7,
      "upper": 0.8,
      "count": 1,
      "mean_predicted": 0.7950954646713725,
      "hit_rate": 0.0,
      "difference": -0.7950954646713725
    }
  ],
  "over_1_5": [
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 47,
      "mean_predicted": 0.6746412032583761,
      "hit_rate": 0.7872340425531915,
      "difference": 0.11259283929481545
    },
    {
      "lower": 0.7,
      "upper": 0.8,
      "count": 397,
      "mean_predicted": 0.732821446616982,
      "hit_rate": 0.7858942065491183,
      "difference": 0.05307275993213634
    },
    {
      "lower": 0.8,
      "upper": 0.9,
      "count": 20,
      "mean_predicted": 0.8288463675886885,
      "hit_rate": 0.8,
      "difference": -0.028846367588688415
    },
    {
      "lower": 0.9,
      "upper": 1.00001,
      "count": 1,
      "mean_predicted": 0.9169782784261703,
      "hit_rate": 1.0,
      "difference": 0.0830217215738297
    }
  ],
  "over_2_5": [
    {
      "lower": 0.5,
      "upper": 0.6,
      "count": 295,
      "mean_predicted": 0.5350606622864765,
      "hit_rate": 0.5559322033898305,
      "difference": 0.020871541103353985
    },
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 16,
      "mean_predicted": 0.6288659945671549,
      "hit_rate": 0.625,
      "difference": -0.0038659945671548623
    },
    {
      "lower": 0.7,
      "upper": 0.8,
      "count": 13,
      "mean_predicted": 0.7369559384387329,
      "hit_rate": 0.5384615384615384,
      "difference": -0.19849439997719442
    },
    {
      "lower": 0.8,
      "upper": 0.9,
      "count": 7,
      "mean_predicted": 0.8245045673298387,
      "hit_rate": 0.8571428571428571,
      "difference": 0.03263828981301842
    },
    {
      "lower": 0.9,
      "upper": 1.00001,
      "count": 1,
      "mean_predicted": 0.9427202249115548,
      "hit_rate": 0.0,
      "difference": -0.9427202249115548
    }
  ],
  "over_3_5": [
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 1,
      "mean_predicted": 0.6505300706054468,
      "hit_rate": 0.0,
      "difference": -0.6505300706054468
    }
  ],
  "home_handicap_-0.5": [
    {
      "lower": 0.5,
      "upper": 0.6,
      "count": 41,
      "mean_predicted": 0.5590428092573259,
      "hit_rate": 0.4878048780487805,
      "difference": -0.07123793120854538
    },
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 17,
      "mean_predicted": 0.6320332297275582,
      "hit_rate": 0.5294117647058824,
      "difference": -0.1026214650216758
    },
    {
      "lower": 0.7,
      "upper": 0.8,
      "count": 16,
      "mean_predicted": 0.752879104279144,
      "hit_rate": 0.625,
      "difference": -0.12787910427914395
    },
    {
      "lower": 0.9,
      "upper": 1.00001,
      "count": 7,
      "mean_predicted": 0.950262880587543,
      "hit_rate": 0.7142857142857143,
      "difference": -0.23597716630182874
    }
  ],
  "home_handicap_+0.5": [
    {
      "lower": 0.5,
      "upper": 0.6,
      "count": 36,
      "mean_predicted": 0.563551704126437,
      "hit_rate": 0.4722222222222222,
      "difference": -0.09132948190421475
    },
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 231,
      "mean_predicted": 0.6252254383107501,
      "hit_rate": 0.6406926406926406,
      "difference": 0.015467202381890588
    },
    {
      "lower": 0.7,
      "upper": 0.8,
      "count": 65,
      "mean_predicted": 0.7457723084278646,
      "hit_rate": 0.6461538461538462,
      "difference": -0.09961846227401838
    },
    {
      "lower": 0.8,
      "upper": 0.9,
      "count": 45,
      "mean_predicted": 0.8377700961966369,
      "hit_rate": 0.7333333333333333,
      "difference": -0.10443676286330361
    },
    {
      "lower": 0.9,
      "upper": 1.00001,
      "count": 25,
      "mean_predicted": 0.9509795552970915,
      "hit_rate": 0.8,
      "difference": -0.1509795552970915
    }
  ]
}
```

#### poisson (`football_poisson_v1-20260926080358`)

| Market | N | Calibrated Brier | Calibrated log loss | ECE |
|---|---:|---:|---:|---:|
| home_win | 465 | 0.2482 | 0.7154 | 0.0745 |
| draw | 465 | 0.1668 | 0.5158 | 0.0399 |
| away_win | 465 | 0.2413 | 0.6976 | 0.0863 |
| btts_yes | 465 | 0.2490 | 0.6914 | 0.0381 |
| over_1_5 | 465 | 0.1701 | 0.5239 | 0.0580 |
| over_2_5 | 465 | 0.2508 | 0.6967 | 0.0468 |
| over_3_5 | 465 | 0.2346 | 0.6638 | 0.0781 |
| home_handicap_-0.5 | 465 | 0.2482 | 0.7148 | 0.0726 |
| home_handicap_+0.5 | 465 | 0.2417 | 0.6996 | 0.0858 |

Calibration buckets with observations:

```json
{
  "home_win": [
    {
      "lower": 0.5,
      "upper": 0.6,
      "count": 44,
      "mean_predicted": 0.5573527413337801,
      "hit_rate": 0.4772727272727273,
      "difference": -0.0800800140610528
    },
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 17,
      "mean_predicted": 0.6340175207454808,
      "hit_rate": 0.5294117647058824,
      "difference": -0.10460575603959843
    },
    {
      "lower": 0.7,
      "upper": 0.8,
      "count": 16,
      "mean_predicted": 0.7502889335971885,
      "hit_rate": 0.625,
      "difference": -0.1252889335971885
    },
    {
      "lower": 0.9,
      "upper": 1.00001,
      "count": 7,
      "mean_predicted": 0.9557248939366121,
      "hit_rate": 0.7142857142857143,
      "difference": -0.24143917965089778
    }
  ],
  "draw": [
    {
      "lower": 0.5,
      "upper": 0.6,
      "count": 7,
      "mean_predicted": 0.5356840349550328,
      "hit_rate": 0.42857142857142855,
      "difference": -0.10711260638360426
    }
  ],
  "away_win": [
    {
      "lower": 0.5,
      "upper": 0.6,
      "count": 29,
      "mean_predicted": 0.5433572616558686,
      "hit_rate": 0.3448275862068966,
      "difference": -0.19852967544897204
    },
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 18,
      "mean_predicted": 0.6444219178230483,
      "hit_rate": 0.4444444444444444,
      "difference": -0.19997747337860383
    },
    {
      "lower": 0.7,
      "upper": 0.8,
      "count": 3,
      "mean_predicted": 0.7571399534735,
      "hit_rate": 0.6666666666666666,
      "difference": -0.09047328680683342
    },
    {
      "lower": 0.8,
      "upper": 0.9,
      "count": 5,
      "mean_predicted": 0.8768783032873234,
      "hit_rate": 0.8,
      "difference": -0.07687830328732337
    },
    {
      "lower": 0.9,
      "upper": 1.00001,
      "count": 7,
      "mean_predicted": 0.9432230282629492,
      "hit_rate": 0.14285714285714285,
      "difference": -0.8003658854058064
    }
  ],
  "btts_yes": [
    {
      "lower": 0.5,
      "upper": 0.6,
      "count": 371,
      "mean_predicted": 0.5415335642955152,
      "hit_rate": 0.555256064690027,
      "difference": 0.013722500394511727
    },
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 13,
      "mean_predicted": 0.631261718323378,
      "hit_rate": 0.5384615384615384,
      "difference": -0.09280017986183953
    },
    {
      "lower": 0.7,
      "upper": 0.8,
      "count": 1,
      "mean_predicted": 0.7949907320843266,
      "hit_rate": 0.0,
      "difference": -0.7949907320843266
    }
  ],
  "over_1_5": [
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 48,
      "mean_predicted": 0.6739683124108882,
      "hit_rate": 0.7916666666666666,
      "difference": 0.11769835425577846
    },
    {
      "lower": 0.7,
      "upper": 0.8,
      "count": 396,
      "mean_predicted": 0.7330808406094435,
      "hit_rate": 0.7853535353535354,
      "difference": 0.05227269474409191
    },
    {
      "lower": 0.8,
      "upper": 0.9,
      "count": 20,
      "mean_predicted": 0.8272259688273683,
      "hit_rate": 0.8,
      "difference": -0.027225968827368274
    },
    {
      "lower": 0.9,
      "upper": 1.00001,
      "count": 1,
      "mean_predicted": 0.918326352273515,
      "hit_rate": 1.0,
      "difference": 0.081673647726485
    }
  ],
  "over_2_5": [
    {
      "lower": 0.5,
      "upper": 0.6,
      "count": 297,
      "mean_predicted": 0.5359808479606647,
      "hit_rate": 0.5521885521885522,
      "difference": 0.01620770422788753
    },
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 14,
      "mean_predicted": 0.6320506612695499,
      "hit_rate": 0.7142857142857143,
      "difference": 0.0822350530161644
    },
    {
      "lower": 0.7,
      "upper": 0.8,
      "count": 13,
      "mean_predicted": 0.7349456834626484,
      "hit_rate": 0.5384615384615384,
      "difference": -0.19648414500111
    },
    {
      "lower": 0.8,
      "upper": 0.9,
      "count": 7,
      "mean_predicted": 0.8244071455221225,
      "hit_rate": 0.8571428571428571,
      "difference": 0.03273571162073463
    },
    {
      "lower": 0.9,
      "upper": 1.00001,
      "count": 1,
      "mean_predicted": 0.9436319663375167,
      "hit_rate": 0.0,
      "difference": -0.9436319663375167
    }
  ],
  "over_3_5": [
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 1,
      "mean_predicted": 0.6490019379603623,
      "hit_rate": 0.0,
      "difference": -0.6490019379603623
    }
  ],
  "home_handicap_-0.5": [
    {
      "lower": 0.5,
      "upper": 0.6,
      "count": 44,
      "mean_predicted": 0.5568213338009701,
      "hit_rate": 0.4772727272727273,
      "difference": -0.0795486065282428
    },
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 17,
      "mean_predicted": 0.6375917422252213,
      "hit_rate": 0.5882352941176471,
      "difference": -0.049356448107574225
    },
    {
      "lower": 0.7,
      "upper": 0.8,
      "count": 15,
      "mean_predicted": 0.7578419478118267,
      "hit_rate": 0.6,
      "difference": -0.1578419478118267
    },
    {
      "lower": 0.8,
      "upper": 0.9,
      "count": 1,
      "mean_predicted": 0.897969200184188,
      "hit_rate": 1.0,
      "difference": 0.10203079981581198
    },
    {
      "lower": 0.9,
      "upper": 1.00001,
      "count": 6,
      "mean_predicted": 0.9546558107299359,
      "hit_rate": 0.6666666666666666,
      "difference": -0.28798914406326925
    }
  ],
  "home_handicap_+0.5": [
    {
      "lower": 0.5,
      "upper": 0.6,
      "count": 35,
      "mean_predicted": 0.5626717450669946,
      "hit_rate": 0.45714285714285713,
      "difference": -0.10552888792413745
    },
    {
      "lower": 0.6,
      "upper": 0.7,
      "count": 230,
      "mean_predicted": 0.6250142927039206,
      "hit_rate": 0.6434782608695652,
      "difference": 0.01846396816564455
    },
    {
      "lower": 0.7,
      "upper": 0.8,
      "count": 67,
      "mean_predicted": 0.7448266563016506,
      "hit_rate": 0.6417910447761194,
      "difference": -0.1030356115255312
    },
    {
      "lower": 0.8,
      "upper": 0.9,
      "count": 45,
      "mean_predicted": 0.8378616916350065,
      "hit_rate": 0.7333333333333333,
      "difference": -0.10452835830167317
    },
    {
      "lower": 0.9,
      "upper": 1.00001,
      "count": 25,
      "mean_predicted": 0.9510504584919884,
      "hit_rate": 0.8,
      "difference": -0.1510504584919884
    }
  ]
}
```

## Promotion decision

**NO MODEL QUALIFIED FOR CHAMPION PROMOTION**

Both candidates were evaluated on the same final held-out fixtures, but neither met the safe non-regression gate against the simple Elo baseline while retaining acceptable calibration.

No champion model/version exists. Candidate artifacts remain local runtime artifacts and were not promoted or committed.

## Real upcoming/odds smoke

- Research-only upcoming predictions computed: **0**; persisted production predictions: **0**.
- Scheduled fixtures with any real odds: **0**; with usable fresh/open odds: **0**.
- Stage Three research market evaluation: `None`.

| Profile | Target | Result | Safe target | Eligible candidates |
|---|---:|---|---|---:|
| Conservative | 3.00 | NO_SAFE_TARGET | False | 606 |
| Balanced | 5.00 | NO_SAFE_TARGET | False | 606 |
| Aggressive | 10.00 | NO_SAFE_TARGET | False | 606 |

The optimizer remained fail-closed because no champion-backed production predictions were persisted. `NO_SAFE_TARGET` is the expected result here.

## Leakage and limitations

- Features are generated in kickoff order; same-kickoff fixtures are staged before any result updates, and the target fixture's score is not available to its own features.
- Train, validation, and test partitions are atomic by exact feature cutoff timestamp; no random shuffle is used.
- The backfill contains fixture results but no match-statistics rows, so statistics-derived features were unavailable rather than fabricated.
- The API-Football free entitlement allowed historical seasons through 2024 but rejected the requested 2025 season; deeper history should wait for an entitled plan or another verified source.
- This evaluation is evidence about the current sample and architecture, not evidence of profitability or future betting performance.

## Commissioning rerun — 2026-09-26

- The sanitized smoke revalidated API-Football authentication and the real Africa/Kampala date window. Three date feeds returned real observations and canonical ingestion remained idempotent; the local real fixture count reached **4,360**.
- Feature generation completed for **4,360** rows. The prediction gate correctly returned `PredictionUnavailable` because no champion model exists.
- No bookmaker prices were available for scheduled fixtures, so the smoke reported `REAL ODDS PROVIDER REQUIRED`. Conservative **3.00**, balanced **5.00**, and aggressive **10.00** all returned `NO_SAFE_TARGET`.
- football-data.org was correctly stopped by its configured daily quota. The initial rerun had The Odds API disabled; it was subsequently enabled and authenticated successfully. The live probe was quota-limited before a live response could be requested; no live capability is claimed from this rerun.
- API-Football outbound accounting increased from **80** to **85** attempts during the bounded smoke runs. No credential values were printed or persisted.
- Browser verification passed for `/`, `/fixtures`, fixture detail, `/models`, `/value`, `/builder`, `/live`, and `/sources`; no browser console errors were observed.

## The Odds API activation — 2026-09-26

- `THE_ODDS_API_KEY` was validated without exposing its value, `ENABLE_ODDS_API=true` was enabled locally, and a real `soccer_epl` request returned HTTP 200 with **20 events**.
- The returned event window was **2026-10-10 through 2026-10-19**. The stored API-Football canonical window currently ends **2026-09-27**, so conservative reconciliation matched **0** events and stored **0** odds snapshots. No unmatched event was promoted into the canonical database.
- Because no bookmaker snapshot matched a canonical fixture and no champion-backed prediction exists, Stage Three valuation and Betslip Builder remained fail-closed; no real value or slip recommendation was generated.
- The provider is ready for matched future fixtures after a controlled fixture refresh or a new canonical ingestion window becomes available.
