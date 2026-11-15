# CPI Win Probability v2 — Evaluation Report

Generated 2026-11-14 10:34:30 · data fingerprint `d8bd69bebd83` · partitions (by match date): train 60%, validation 15%, calibration 10%, test 15%

All numbers are on the **held-out test partition** (the most recent 15% of labelled matches), which was not used for feature construction, model selection or calibration. Metrics weight every match-innings equally (limited overs) or every match equally (multi-day). CIs are 95% match-level bootstrap intervals. Skill = 1 − model log loss / baseline log loss.

## Summary

| Group | Test matches | v2 log loss | Legacy v1 | Elo-only | Venue-par | Prior | Skill vs prior | v2 Brier |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| T20 | 2,145 | 0.4285 | 0.6298 | 0.6403 | 0.5749 | 0.6923 | +0.381 | 0.1428 |
| ODI | 462 | 0.4615 | 0.6948 | 0.6464 | 0.6028 | 0.6936 | +0.335 | 0.1534 |
| ODM | 291 | 0.5283 | 0.6843 | 0.6556 | 0.6277 | 0.6903 | +0.235 | 0.1764 |
| Test | 138 | 0.7266 | 0.9848 | 0.9242 | 0.8831 | 0.9918 | +0.267 | 0.4340 |
| MDM | 336 | 0.8851 | 1.0761 | 1.0983 | 1.0498 | 1.0886 | +0.187 | 0.5331 |

## T20 (T20, T20I)

| Partition | From | To | Matches |
|---|---|---|---:|
| train | 2005-02-17 | 2023-07-21 | 8,583 |
| validation | 2023-07-22 | 2024-11-20 | 2,146 |
| calibration | 2024-11-21 | 2025-08-29 | 1,429 |
| test | 2025-08-30 | 2026-11-03 | 2,145 |

Unlabelled (excluded from training/evaluation): 442 matches (no result, abandoned, or tie without recorded winner).

State audit: pre delivery states 3,214,372, invalid states excluded 3, terminal pre delivery states excluded 905, unlabelled states excluded 58,871, second innings target derived from first innings 91,817, chase states beyond rounded dls allotment 241

### Test partition, both innings

| Model | Log loss [95% CI] | Brier [95% CI] | ECE | Skill vs prior [95% CI] | Skill vs Elo | Skill vs venue-par |
|---|---|---|---|---|---|---|
| **v2 model (calibrated, deployed)** | 0.4285 [0.416, 0.442] | 0.1428 [0.138, 0.148] | 0.0127 | +0.381 [0.362, 0.400] | +0.331 | +0.255 |
| v2 model, uncalibrated | 0.4285 [0.416, 0.442] | 0.1428 [0.138, 0.148] | 0.0127 | +0.381 [0.362, 0.400] | +0.331 | +0.255 |
| best logistic regression (new features) | 0.4299 [0.416, 0.442] | 0.1426 [0.137, 0.147] | 0.0114 | +0.379 [0.360, 0.400] | +0.329 | +0.252 |
| legacy v1 logistic (C=1e-4, team1 features) | 0.6298 [0.627, 0.633] | 0.2190 [0.218, 0.221] | 0.1632 | +0.090 [0.086, 0.095] | +0.016 | -0.096 |
| venue-par baseline | 0.5749 [0.562, 0.587] | 0.1951 [0.190, 0.200] | 0.0324 | +0.170 [0.153, 0.188] | +0.102 | — |
| Elo-only baseline | 0.6403 [0.630, 0.651] | 0.2250 [0.220, 0.230] | 0.0236 | +0.075 [0.060, 0.089] | — | -0.114 |
| constant prior | 0.6923 [0.691, 0.694] | 0.2496 [0.249, 0.250] | 0.0018 | — | -0.081 | -0.204 |

### Innings 1

Calibration plot: [plots/t20_innings1.svg](plots/t20_innings1.svg)

| Model | Log loss [95% CI] | Brier [95% CI] | ECE | Skill vs prior [95% CI] | Skill vs Elo | Skill vs venue-par |
|---|---|---|---|---|---|---|
| **v2 model (calibrated, deployed)** | 0.5484 [0.533, 0.562] | 0.1866 [0.180, 0.192] | 0.0331 | +0.208 [0.188, 0.231] | +0.143 | +0.125 |
| v2 model, uncalibrated | 0.5484 [0.533, 0.562] | 0.1866 [0.180, 0.192] | 0.0331 | +0.208 [0.188, 0.231] | +0.143 | +0.125 |
| v2 + Platt/sigmoid | 0.5470 [0.531, 0.561] | 0.1860 [0.179, 0.192] | 0.0245 | +0.210 [0.190, 0.233] | +0.146 | +0.127 |
| v2 + isotonic | 0.5504 [0.533, 0.566] | 0.1862 [0.179, 0.192] | 0.0237 | +0.205 [0.182, 0.231] | +0.140 | +0.122 |
| best logistic regression (new features) | 0.5498 [0.533, 0.564] | 0.1864 [0.180, 0.192] | 0.0288 | +0.206 [0.185, 0.230] | +0.141 | +0.123 |
| legacy v1 logistic (C=1e-4, team1 features) | 0.6672 [0.665, 0.670] | 0.2371 [0.236, 0.238] | 0.1094 | +0.036 [0.033, 0.039] | -0.042 | -0.065 |
| venue-par baseline | 0.6266 [0.617, 0.635] | 0.2159 [0.212, 0.220] | 0.0613 | +0.095 [0.082, 0.109] | +0.021 | — |
| Elo-only baseline | 0.6402 [0.630, 0.651] | 0.2250 [0.220, 0.230] | 0.0237 | +0.075 [0.060, 0.089] | — | -0.022 |
| constant prior | 0.6923 [0.691, 0.694] | 0.2496 [0.249, 0.250] | 0.0019 | — | -0.081 | -0.105 |

By source format:

| Format | States | v2 LL | Legacy v1 LL | Prior LL | Skill vs prior |
|---|---:|---:|---:|---:|---:|
| T20 | 102,092 | 0.6178 | 0.6707 | 0.6880 | +0.102 |
| T20I | 146,348 | 0.5002 | 0.6647 | 0.6953 | +0.281 |

#### Segments

*phase*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| powerplay (1-6) | 77,190 | 0.6006 | 0.2077 | 0.6915 | 0.6392 | 0.6885 | 0.6762 | +0.131 | +0.060 | +0.128 |
| middle (7-15) | 113,749 | 0.5316 | 0.1795 | 0.6918 | 0.6394 | 0.6017 | 0.6633 | +0.232 | +0.169 | +0.116 |
| death (16-20) | 57,495 | 0.5090 | 0.1714 | 0.6945 | 0.6435 | 0.5901 | 0.6622 | +0.267 | +0.209 | +0.137 |

*wickets remaining*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1-2 | 9,048 | 0.3298 | 0.1045 | 0.6650 | 0.5912 | 0.5227 | 0.5870 | +0.504 | +0.442 | +0.369 |
| 3-4 | 23,093 | 0.4790 | 0.1590 | 0.6773 | 0.6258 | 0.5862 | 0.6403 | +0.293 | +0.235 | +0.183 |
| 5-7 | 85,143 | 0.5481 | 0.1860 | 0.6892 | 0.6435 | 0.6089 | 0.6677 | +0.205 | +0.148 | +0.100 |
| 8-10 | 131,156 | 0.5766 | 0.1978 | 0.6990 | 0.6442 | 0.6527 | 0.6773 | +0.175 | +0.105 | +0.117 |

*situation*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| below par | 60,154 | 0.4204 | 0.1341 | 0.6661 | 0.6003 | 0.5394 | 0.6177 | +0.369 | +0.300 | +0.221 |
| near par | 105,492 | 0.6418 | 0.2256 | 0.6902 | 0.6524 | 0.7108 | 0.6877 | +0.070 | +0.016 | +0.097 |
| above par | 82,794 | 0.5244 | 0.1759 | 0.7149 | 0.6547 | 0.5837 | 0.6779 | +0.266 | +0.199 | +0.102 |

#### Model selection (validation partition)

| Candidate | Validation log loss | Validation Brier |
|---|---:|---:|
| logistic_C=0.01 | 0.5614 | 0.1911 |
| logistic_C=0.1 | 0.5608 | 0.1910 |
| logistic_C=1.0 | 0.5608 | 0.1910 |
| logistic_C=10.0 | 0.5608 | 0.1910 |
| hgb_depth=2_iter=50 | 0.5785 | 0.1969 |
| hgb_depth=2_iter=100 | 0.5647 | 0.1922 |
| hgb_depth=2_iter=300 ✅ | 0.5585 | 0.1906 |
| hgb_depth=2_iter=600 | 0.5607 | 0.1917 |
| hgb_depth=3_iter=50 | 0.5697 | 0.1938 |
| hgb_depth=3_iter=100 | 0.5603 | 0.1909 |
| hgb_depth=3_iter=300 | 0.5612 | 0.1917 |
| hgb_depth=3_iter=600 | 0.5688 | 0.1948 |
| hgb_depth=4_iter=50 | 0.5653 | 0.1922 |
| hgb_depth=4_iter=100 | 0.5607 | 0.1911 |
| hgb_depth=4_iter=300 | 0.5675 | 0.1937 |
| hgb_depth=4_iter=600 | 0.5828 | 0.1992 |
| hgb_depth=6_iter=50 | 0.5633 | 0.1914 |
| hgb_depth=6_iter=100 | 0.5615 | 0.1913 |
| hgb_depth=6_iter=300 | 0.5755 | 0.1965 |
| hgb_depth=6_iter=600 | 0.6003 | 0.2040 |
| hgb_depth=2_iter=300_monotone | 0.5587 | 0.1907 |

Calibration chosen by match-grouped 4-fold CV inside the calibration partition: **none** (none 0.5722, sigmoid 0.5736, isotonic 0.5751).

### Innings 2

Calibration plot: [plots/t20_innings2.svg](plots/t20_innings2.svg)

| Model | Log loss [95% CI] | Brier [95% CI] | ECE | Skill vs prior [95% CI] | Skill vs Elo | Skill vs venue-par |
|---|---|---|---|---|---|---|
| **v2 model (calibrated, deployed)** | 0.3086 [0.294, 0.327] | 0.0989 [0.094, 0.106] | 0.0153 | +0.554 [0.528, 0.576] | +0.518 | +0.410 |
| v2 model, uncalibrated | 0.3086 [0.294, 0.327] | 0.0989 [0.094, 0.106] | 0.0153 | +0.554 [0.528, 0.576] | +0.518 | +0.410 |
| v2 + Platt/sigmoid | 0.3084 [0.294, 0.326] | 0.0988 [0.094, 0.105] | 0.0136 | +0.554 [0.529, 0.575] | +0.518 | +0.410 |
| v2 + isotonic | 0.3098 [0.294, 0.328] | 0.0986 [0.094, 0.105] | 0.0083 | +0.552 [0.527, 0.574] | +0.516 | +0.408 |
| best logistic regression (new features) | 0.3099 [0.295, 0.327] | 0.0988 [0.093, 0.105] | 0.0136 | +0.552 [0.528, 0.574] | +0.516 | +0.408 |
| legacy v1 logistic (C=1e-4, team1 features) | 0.5923 [0.588, 0.597] | 0.2009 [0.199, 0.203] | 0.2170 | +0.144 [0.138, 0.151] | +0.075 | -0.132 |
| venue-par baseline | 0.5231 [0.507, 0.543] | 0.1742 [0.167, 0.182] | 0.0213 | +0.244 [0.216, 0.268] | +0.183 | — |
| Elo-only baseline | 0.6403 [0.630, 0.651] | 0.2250 [0.220, 0.230] | 0.0235 | +0.075 [0.060, 0.090] | — | -0.224 |
| constant prior | 0.6923 [0.690, 0.694] | 0.2496 [0.249, 0.250] | 0.0017 | — | -0.081 | -0.324 |

By source format:

| Format | States | v2 LL | Legacy v1 LL | Prior LL | Skill vs prior |
|---|---:|---:|---:|---:|---:|
| T20 | 92,527 | 0.3893 | 0.6187 | 0.6880 | +0.434 |
| T20I | 123,446 | 0.2526 | 0.5740 | 0.6953 | +0.637 |

#### Segments

*phase*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| powerplay (1-6) | 76,495 | 0.3608 | 0.1177 | 0.6868 | 0.6214 | 0.4949 | 0.5897 | +0.475 | +0.419 | +0.271 |
| middle (7-15) | 103,379 | 0.2929 | 0.0931 | 0.6929 | 0.6465 | 0.5317 | 0.5987 | +0.577 | +0.547 | +0.449 |
| death (16-20) | 36,099 | 0.2197 | 0.0676 | 0.7050 | 0.6714 | 0.5706 | 0.5792 | +0.688 | +0.673 | +0.615 |

*wickets remaining*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1-2 | 9,718 | 0.0864 | 0.0231 | 0.7335 | 0.6871 | 0.4788 | 0.4713 | +0.882 | +0.874 | +0.820 |
| 3-4 | 19,780 | 0.1927 | 0.0583 | 0.7226 | 0.6644 | 0.4835 | 0.5544 | +0.733 | +0.710 | +0.601 |
| 5-7 | 68,471 | 0.3027 | 0.0957 | 0.7005 | 0.6594 | 0.5475 | 0.6167 | +0.568 | +0.541 | +0.447 |
| 8-10 | 118,004 | 0.3447 | 0.1120 | 0.6807 | 0.6236 | 0.5194 | 0.5941 | +0.494 | +0.447 | +0.336 |

*required run rate*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| <6 | 54,592 | 0.1568 | 0.0452 | 0.6560 | 0.5854 | 0.3648 | 0.5289 | +0.761 | +0.732 | +0.570 |
| 6-8 | 45,934 | 0.4939 | 0.1629 | 0.6820 | 0.6656 | 0.6855 | 0.6632 | +0.276 | +0.258 | +0.279 |
| 8-10 | 43,888 | 0.5322 | 0.1802 | 0.7020 | 0.6736 | 0.7123 | 0.6741 | +0.242 | +0.210 | +0.253 |
| 10-12 | 29,000 | 0.3595 | 0.1148 | 0.7217 | 0.6737 | 0.5548 | 0.6304 | +0.502 | +0.466 | +0.352 |
| 12+ | 42,559 | 0.1003 | 0.0263 | 0.7358 | 0.6496 | 0.3993 | 0.5131 | +0.864 | +0.846 | +0.749 |

*situation*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ahead of par (<0.8) | 59,242 | 0.1426 | 0.0379 | 0.6536 | 0.5862 | 0.3813 | 0.5313 | +0.782 | +0.757 | +0.626 |
| balanced (0.8-1.2) | 70,193 | 0.6107 | 0.2117 | 0.6870 | 0.6771 | 0.7595 | 0.6814 | +0.111 | +0.098 | +0.196 |
| behind par (>1.2) | 86,538 | 0.2117 | 0.0619 | 0.7317 | 0.6592 | 0.4579 | 0.5747 | +0.711 | +0.679 | +0.538 |

#### Model selection (validation partition)

| Candidate | Validation log loss | Validation Brier |
|---|---:|---:|
| logistic_C=0.01 | 0.3376 | 0.1082 |
| logistic_C=0.1 | 0.3330 | 0.1071 |
| logistic_C=1.0 | 0.3325 | 0.1069 |
| logistic_C=10.0 | 0.3325 | 0.1068 |
| hgb_depth=2_iter=50 | 0.3578 | 0.1115 |
| hgb_depth=2_iter=100 | 0.3392 | 0.1086 |
| hgb_depth=2_iter=300 | 0.3309 | 0.1065 |
| hgb_depth=2_iter=600 | 0.3314 | 0.1068 |
| hgb_depth=3_iter=50 | 0.3516 | 0.1101 |
| hgb_depth=3_iter=100 | 0.3346 | 0.1076 |
| hgb_depth=3_iter=300 ✅ | 0.3303 | 0.1066 |
| hgb_depth=3_iter=600 | 0.3350 | 0.1084 |
| hgb_depth=4_iter=50 | 0.3481 | 0.1091 |
| hgb_depth=4_iter=100 | 0.3324 | 0.1071 |
| hgb_depth=4_iter=300 | 0.3332 | 0.1077 |
| hgb_depth=4_iter=600 | 0.3400 | 0.1099 |
| hgb_depth=6_iter=50 | 0.3461 | 0.1083 |
| hgb_depth=6_iter=100 | 0.3313 | 0.1068 |
| hgb_depth=6_iter=300 | 0.3403 | 0.1101 |
| hgb_depth=6_iter=600 | 0.3532 | 0.1139 |
| hgb_depth=3_iter=300_monotone | 0.3305 | 0.1067 |

Calibration chosen by match-grouped 4-fold CV inside the calibration partition: **none** (none 0.3374, sigmoid 0.3381, isotonic 0.3388).

### Resource table (expected runs remaining, training first innings)

| Balls remaining | 0 down | 2 down | 4 down | 6 down | 8 down |
|---:|---:|---:|---:|---:|---:|
| 120 | 152.4 | 122.9 | 110.6 | 105.6 | 101.8 |
| 60 | 93.4 | 87.2 | 73.4 | 59.0 | 53.1 |
| 30 | 54.9 | 51.1 | 47.2 | 35.2 | 26.6 |
| 12 | 29.8 | 25.8 | 23.1 | 17.3 | 10.3 |

## ODI (ODI)

| Partition | From | To | Matches |
|---|---|---|---:|
| train | 2002-06-27 | 2019-02-03 | 1,849 |
| validation | 2019-02-07 | 2022-09-18 | 462 |
| calibration | 2022-09-19 | 2024-04-07 | 308 |
| test | 2024-04-11 | 2026-11-02 | 462 |

Unlabelled (excluded from training/evaluation): 156 matches (no result, abandoned, or tie without recorded winner).

State audit: pre delivery states 1,666,026, invalid states excluded 0, terminal pre delivery states excluded 756, unlabelled states excluded 44,477, second innings target derived from first innings 1,982, chase states beyond rounded dls allotment 89

### Test partition, both innings

| Model | Log loss [95% CI] | Brier [95% CI] | ECE | Skill vs prior [95% CI] | Skill vs Elo | Skill vs venue-par |
|---|---|---|---|---|---|---|
| **v2 model (calibrated, deployed)** | 0.4615 [0.425, 0.498] | 0.1534 [0.139, 0.166] | 0.0198 | +0.335 [0.283, 0.389] | +0.286 | +0.234 |
| v2 model, uncalibrated | 0.4615 [0.425, 0.498] | 0.1534 [0.139, 0.166] | 0.0198 | +0.335 [0.283, 0.389] | +0.286 | +0.234 |
| best logistic regression (new features) | 0.4615 [0.425, 0.498] | 0.1534 [0.139, 0.166] | 0.0198 | +0.335 [0.283, 0.389] | +0.286 | +0.234 |
| legacy v1 logistic (C=1e-4, team1 features) | 0.6948 [0.683, 0.705] | 0.2508 [0.245, 0.256] | 0.0656 | -0.002 [-0.022, 0.022] | -0.075 | -0.153 |
| venue-par baseline | 0.6028 [0.572, 0.633] | 0.2056 [0.194, 0.218] | 0.0339 | +0.131 [0.087, 0.174] | +0.067 | — |
| Elo-only baseline | 0.6464 [0.611, 0.678] | 0.2291 [0.214, 0.243] | 0.0549 | +0.068 [0.023, 0.117] | — | -0.072 |
| constant prior | 0.6936 [0.690, 0.698] | 0.2502 [0.248, 0.252] | 0.0165 | — | -0.073 | -0.151 |

### Innings 1

Calibration plot: [plots/odi_innings1.svg](plots/odi_innings1.svg)

| Model | Log loss [95% CI] | Brier [95% CI] | ECE | Skill vs prior [95% CI] | Skill vs Elo | Skill vs venue-par |
|---|---|---|---|---|---|---|
| **v2 model (calibrated, deployed)** | 0.5772 [0.535, 0.616] | 0.1965 [0.179, 0.212] | 0.0233 | +0.168 [0.112, 0.229] | +0.107 | +0.128 |
| v2 model, uncalibrated | 0.5772 [0.535, 0.616] | 0.1965 [0.179, 0.212] | 0.0233 | +0.168 [0.112, 0.229] | +0.107 | +0.128 |
| v2 + Platt/sigmoid | 0.5759 [0.536, 0.612] | 0.1962 [0.180, 0.211] | 0.0194 | +0.170 [0.118, 0.227] | +0.109 | +0.130 |
| v2 + isotonic | 0.5929 [0.545, 0.638] | 0.1973 [0.182, 0.212] | 0.0300 | +0.145 [0.079, 0.215] | +0.083 | +0.104 |
| best logistic regression (new features) | 0.5772 [0.535, 0.616] | 0.1965 [0.179, 0.212] | 0.0233 | +0.168 [0.112, 0.229] | +0.107 | +0.128 |
| legacy v1 logistic (C=1e-4, team1 features) | 0.6992 [0.688, 0.709] | 0.2530 [0.247, 0.258] | 0.0648 | -0.008 [-0.028, 0.015] | -0.082 | -0.056 |
| venue-par baseline | 0.6621 [0.644, 0.683] | 0.2311 [0.223, 0.240] | 0.0486 | +0.045 [0.014, 0.073] | -0.024 | — |
| Elo-only baseline | 0.6464 [0.611, 0.678] | 0.2291 [0.214, 0.243] | 0.0764 | +0.068 [0.023, 0.117] | — | +0.024 |
| constant prior | 0.6936 [0.690, 0.698] | 0.2502 [0.248, 0.252] | 0.0165 | — | -0.073 | -0.048 |

#### Segments

*phase*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| powerplay (1-10) | 27,720 | 0.6209 | 0.2168 | 0.6908 | 0.6447 | 0.7545 | 0.7075 | +0.101 | +0.037 | +0.177 |
| middle (11-40) | 80,439 | 0.5664 | 0.1917 | 0.6926 | 0.6449 | 0.6417 | 0.7015 | +0.182 | +0.122 | +0.117 |
| death (41-50) | 21,042 | 0.5587 | 0.1868 | 0.7017 | 0.6551 | 0.6122 | 0.6780 | +0.204 | +0.147 | +0.087 |

*wickets remaining*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1-2 | 6,289 | 0.5002 | 0.1595 | 0.6731 | 0.6240 | 0.6293 | 0.7467 | +0.257 | +0.198 | +0.205 |
| 3-4 | 13,616 | 0.5043 | 0.1654 | 0.6799 | 0.6176 | 0.6260 | 0.7320 | +0.258 | +0.183 | +0.194 |
| 5-7 | 46,798 | 0.5846 | 0.1988 | 0.6928 | 0.6455 | 0.6318 | 0.7014 | +0.156 | +0.094 | +0.075 |
| 8-10 | 62,499 | 0.5970 | 0.2060 | 0.6996 | 0.6562 | 0.6967 | 0.6847 | +0.147 | +0.090 | +0.143 |

*situation*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| below par | 27,801 | 0.4922 | 0.1595 | 0.6684 | 0.6102 | 0.6095 | 0.7601 | +0.264 | +0.193 | +0.192 |
| near par | 49,446 | 0.6398 | 0.2259 | 0.6895 | 0.6473 | 0.7362 | 0.7117 | +0.072 | +0.012 | +0.131 |
| above par | 51,955 | 0.5671 | 0.1899 | 0.7131 | 0.6676 | 0.6208 | 0.6496 | +0.205 | +0.151 | +0.086 |

#### Model selection (validation partition)

| Candidate | Validation log loss | Validation Brier |
|---|---:|---:|
| logistic_C=0.01 | 0.5453 | 0.1837 |
| logistic_C=0.1 ✅ | 0.5428 | 0.1824 |
| logistic_C=1.0 | 0.5433 | 0.1824 |
| logistic_C=10.0 | 0.5434 | 0.1825 |
| hgb_depth=2_iter=50 | 0.5570 | 0.1875 |
| hgb_depth=2_iter=100 | 0.5474 | 0.1845 |
| hgb_depth=2_iter=300 | 0.5476 | 0.1848 |
| hgb_depth=2_iter=600 | 0.5483 | 0.1852 |
| hgb_depth=3_iter=50 | 0.5474 | 0.1841 |
| hgb_depth=3_iter=100 | 0.5428 | 0.1827 |
| hgb_depth=3_iter=300 | 0.5500 | 0.1853 |
| hgb_depth=3_iter=600 | 0.5594 | 0.1880 |
| hgb_depth=4_iter=50 | 0.5466 | 0.1839 |
| hgb_depth=4_iter=100 | 0.5476 | 0.1845 |
| hgb_depth=4_iter=300 | 0.5592 | 0.1888 |
| hgb_depth=4_iter=600 | 0.5899 | 0.1995 |
| hgb_depth=6_iter=50 | 0.5470 | 0.1844 |
| hgb_depth=6_iter=100 | 0.5505 | 0.1859 |
| hgb_depth=6_iter=300 | 0.5783 | 0.1960 |
| hgb_depth=6_iter=600 | 0.6168 | 0.2069 |
| hgb_depth=3_iter=100_monotone | 0.5458 | 0.1839 |

Calibration chosen by match-grouped 4-fold CV inside the calibration partition: **none** (none 0.5496, sigmoid 0.5541, isotonic 0.5988).

### Innings 2

Calibration plot: [plots/odi_innings2.svg](plots/odi_innings2.svg)

| Model | Log loss [95% CI] | Brier [95% CI] | ECE | Skill vs prior [95% CI] | Skill vs Elo | Skill vs venue-par |
|---|---|---|---|---|---|---|
| **v2 model (calibrated, deployed)** | 0.3459 [0.306, 0.384] | 0.1103 [0.096, 0.123] | 0.0230 | +0.501 [0.444, 0.558] | +0.465 | +0.364 |
| v2 model, uncalibrated | 0.3459 [0.306, 0.384] | 0.1103 [0.096, 0.123] | 0.0230 | +0.501 [0.444, 0.558] | +0.465 | +0.364 |
| v2 + Platt/sigmoid | 0.3435 [0.307, 0.380] | 0.1098 [0.096, 0.122] | 0.0140 | +0.505 [0.452, 0.558] | +0.469 | +0.368 |
| v2 + isotonic | 0.3479 [0.310, 0.387] | 0.1097 [0.097, 0.122] | 0.0117 | +0.498 [0.442, 0.554] | +0.462 | +0.360 |
| best logistic regression (new features) | 0.3459 [0.306, 0.384] | 0.1103 [0.096, 0.123] | 0.0230 | +0.501 [0.444, 0.558] | +0.465 | +0.364 |
| legacy v1 logistic (C=1e-4, team1 features) | 0.6904 [0.678, 0.700] | 0.2487 [0.243, 0.254] | 0.0664 | +0.005 [-0.015, 0.028] | -0.068 | -0.270 |
| venue-par baseline | 0.5435 [0.494, 0.594] | 0.1800 [0.161, 0.200] | 0.0476 | +0.216 [0.145, 0.286] | +0.159 | — |
| Elo-only baseline | 0.6464 [0.611, 0.678] | 0.2291 [0.214, 0.243] | 0.0746 | +0.068 [0.023, 0.117] | — | -0.189 |
| constant prior | 0.6936 [0.690, 0.698] | 0.2502 [0.248, 0.252] | 0.0165 | — | -0.073 | -0.276 |

#### Segments

*phase*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| powerplay (1-10) | 27,720 | 0.4444 | 0.1447 | 0.6902 | 0.6318 | 0.4997 | 0.6985 | +0.356 | +0.297 | +0.111 |
| middle (11-40) | 71,660 | 0.3169 | 0.1002 | 0.6944 | 0.6499 | 0.5471 | 0.6885 | +0.544 | +0.512 | +0.421 |
| death (41-50) | 10,339 | 0.2367 | 0.0720 | 0.6994 | 0.6691 | 0.6684 | 0.6778 | +0.662 | +0.646 | +0.646 |

*wickets remaining*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1-2 | 6,007 | 0.1397 | 0.0355 | 0.7333 | 0.7007 | 0.5605 | 0.5808 | +0.809 | +0.801 | +0.751 |
| 3-4 | 11,608 | 0.1984 | 0.0588 | 0.7239 | 0.7020 | 0.5689 | 0.6109 | +0.726 | +0.717 | +0.651 |
| 5-7 | 37,653 | 0.3463 | 0.1116 | 0.6972 | 0.6616 | 0.5749 | 0.6839 | +0.503 | +0.477 | +0.398 |
| 8-10 | 54,451 | 0.3957 | 0.1272 | 0.6813 | 0.6203 | 0.5169 | 0.7214 | +0.419 | +0.362 | +0.234 |

*required run rate*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| <4.5 | 34,469 | 0.2360 | 0.0714 | 0.6606 | 0.5888 | 0.4312 | 0.7704 | +0.643 | +0.599 | +0.453 |
| 4.5-6 | 27,912 | 0.5442 | 0.1837 | 0.6928 | 0.6919 | 0.7067 | 0.7011 | +0.215 | +0.214 | +0.230 |
| 6-7.5 | 23,381 | 0.4257 | 0.1378 | 0.7165 | 0.7057 | 0.5814 | 0.6356 | +0.406 | +0.397 | +0.268 |
| 7.5-9 | 12,176 | 0.3299 | 0.0993 | 0.7250 | 0.6461 | 0.5673 | 0.6087 | +0.545 | +0.489 | +0.418 |
| 9+ | 11,781 | 0.1485 | 0.0398 | 0.7346 | 0.6325 | 0.4725 | 0.5759 | +0.798 | +0.765 | +0.686 |

*situation*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ahead of par (<0.8) | 29,925 | 0.1629 | 0.0435 | 0.6525 | 0.5838 | 0.3660 | 0.7889 | +0.750 | +0.721 | +0.555 |
| balanced (0.8-1.2) | 33,612 | 0.6426 | 0.2259 | 0.6885 | 0.6839 | 0.7896 | 0.7142 | +0.067 | +0.060 | +0.186 |
| behind par (>1.2) | 46,182 | 0.2855 | 0.0831 | 0.7305 | 0.6708 | 0.5142 | 0.5939 | +0.609 | +0.574 | +0.445 |

#### Model selection (validation partition)

| Candidate | Validation log loss | Validation Brier |
|---|---:|---:|
| logistic_C=0.01 | 0.3603 | 0.1137 |
| logistic_C=0.1 | 0.3405 | 0.1086 |
| logistic_C=1.0 | 0.3343 | 0.1073 |
| logistic_C=10.0 ✅ | 0.3327 | 0.1070 |
| hgb_depth=2_iter=50 | 0.3697 | 0.1156 |
| hgb_depth=2_iter=100 | 0.3444 | 0.1100 |
| hgb_depth=2_iter=300 | 0.3365 | 0.1079 |
| hgb_depth=2_iter=600 | 0.3400 | 0.1095 |
| hgb_depth=3_iter=50 | 0.3573 | 0.1115 |
| hgb_depth=3_iter=100 | 0.3370 | 0.1077 |
| hgb_depth=3_iter=300 | 0.3342 | 0.1077 |
| hgb_depth=3_iter=600 | 0.3427 | 0.1104 |
| hgb_depth=4_iter=50 | 0.3530 | 0.1102 |
| hgb_depth=4_iter=100 | 0.3356 | 0.1075 |
| hgb_depth=4_iter=300 | 0.3418 | 0.1104 |
| hgb_depth=4_iter=600 | 0.3598 | 0.1157 |
| hgb_depth=6_iter=50 | 0.3533 | 0.1105 |
| hgb_depth=6_iter=100 | 0.3389 | 0.1090 |
| hgb_depth=6_iter=300 | 0.3499 | 0.1126 |
| hgb_depth=6_iter=600 | 0.3874 | 0.1217 |
| hgb_depth=3_iter=300_monotone | 0.3364 | 0.1080 |

Calibration chosen by match-grouped 4-fold CV inside the calibration partition: **none** (none 0.3215, sigmoid 0.3216, isotonic 0.3278).

### Resource table (expected runs remaining, training first innings)

| Balls remaining | 0 down | 2 down | 4 down | 6 down | 8 down |
|---:|---:|---:|---:|---:|---:|
| 300 | 246.2 | 187.1 | 132.7 | 102.2 | 77.2 |
| 150 | 173.8 | 153.7 | 122.2 | 86.6 | 58.3 |
| 75 | 123.1 | 115.3 | 83.4 | 64.2 | 36.3 |
| 12 | 81.7 | 73.1 | 31.7 | 19.2 | 6.0 |

## ODM (ODM)

| Partition | From | To | Matches |
|---|---|---|---:|
| train | 2010-05-28 | 2023-08-13 | 1,201 |
| validation | 2023-08-14 | 2024-09-28 | 293 |
| calibration | 2024-09-29 | 2025-08-24 | 206 |
| test | 2025-08-25 | 2026-10-31 | 291 |

Unlabelled (excluded from training/evaluation): 103 matches (no result, abandoned, or tie without recorded winner).

State audit: pre delivery states 1,047,560, invalid states excluded 0, terminal pre delivery states excluded 781, unlabelled states excluded 26,822, second innings target derived from first innings 74,013, chase states beyond rounded dls allotment 60

### Test partition, both innings

| Model | Log loss [95% CI] | Brier [95% CI] | ECE | Skill vs prior [95% CI] | Skill vs Elo | Skill vs venue-par |
|---|---|---|---|---|---|---|
| **v2 model (calibrated, deployed)** | 0.5283 [0.486, 0.569] | 0.1764 [0.161, 0.191] | 0.0425 | +0.235 [0.175, 0.295] | +0.194 | +0.158 |
| v2 model, uncalibrated | 0.5223 [0.482, 0.560] | 0.1758 [0.160, 0.190] | 0.0241 | +0.243 [0.189, 0.301] | +0.203 | +0.168 |
| best logistic regression (new features) | 0.5193 [0.479, 0.560] | 0.1744 [0.159, 0.189] | 0.0216 | +0.248 [0.188, 0.306] | +0.208 | +0.173 |
| legacy v1 logistic (C=1e-4, team1 features) | 0.6843 [0.682, 0.686] | 0.2456 [0.245, 0.246] | 0.1071 | +0.009 [0.003, 0.014] | -0.044 | -0.090 |
| venue-par baseline | 0.6277 [0.599, 0.660] | 0.2185 [0.206, 0.232] | 0.0316 | +0.091 [0.042, 0.133] | +0.043 | — |
| Elo-only baseline | 0.6556 [0.640, 0.672] | 0.2315 [0.224, 0.240] | 0.0601 | +0.050 [0.027, 0.070] | — | -0.044 |
| constant prior | 0.6903 [0.686, 0.695] | 0.2486 [0.246, 0.251] | 0.0268 | — | -0.053 | -0.100 |

### Innings 1

Calibration plot: [plots/odm_innings1.svg](plots/odm_innings1.svg)

| Model | Log loss [95% CI] | Brier [95% CI] | ECE | Skill vs prior [95% CI] | Skill vs Elo | Skill vs venue-par |
|---|---|---|---|---|---|---|
| **v2 model (calibrated, deployed)** | 0.6125 [0.580, 0.642] | 0.2118 [0.198, 0.225] | 0.0425 | +0.113 [0.069, 0.156] | +0.066 | +0.061 |
| v2 model, uncalibrated | 0.6073 [0.578, 0.636] | 0.2101 [0.197, 0.224] | 0.0460 | +0.120 [0.076, 0.162] | +0.074 | +0.069 |
| v2 + Platt/sigmoid | 0.6056 [0.576, 0.633] | 0.2093 [0.196, 0.222] | 0.0405 | +0.123 [0.083, 0.163] | +0.076 | +0.072 |
| v2 + isotonic | 0.6125 [0.580, 0.642] | 0.2118 [0.198, 0.225] | 0.0425 | +0.113 [0.069, 0.156] | +0.066 | +0.061 |
| best logistic regression (new features) | 0.6013 [0.567, 0.638] | 0.2074 [0.193, 0.223] | 0.0544 | +0.129 [0.074, 0.178] | +0.083 | +0.078 |
| legacy v1 logistic (C=1e-4, team1 features) | 0.6884 [0.686, 0.691] | 0.2476 [0.246, 0.249] | 0.0585 | +0.003 [-0.001, 0.006] | -0.050 | -0.055 |
| venue-par baseline | 0.6523 [0.633, 0.673] | 0.2290 [0.220, 0.239] | 0.0711 | +0.055 [0.023, 0.083] | +0.005 | — |
| Elo-only baseline | 0.6556 [0.640, 0.672] | 0.2315 [0.224, 0.240] | 0.0601 | +0.050 [0.027, 0.070] | — | -0.005 |
| constant prior | 0.6903 [0.686, 0.695] | 0.2486 [0.246, 0.251] | 0.0268 | — | -0.053 | -0.058 |

#### Segments

*phase*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| powerplay (1-10) | 17,460 | 0.6314 | 0.2204 | 0.6891 | 0.6515 | 0.6640 | 0.6881 | +0.084 | +0.031 | +0.049 |
| middle (11-40) | 50,371 | 0.6050 | 0.2086 | 0.6897 | 0.6545 | 0.6488 | 0.6883 | +0.123 | +0.076 | +0.068 |
| death (41-50) | 13,275 | 0.6159 | 0.2121 | 0.6941 | 0.6657 | 0.6498 | 0.6894 | +0.113 | +0.075 | +0.052 |

*wickets remaining*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1-2 | 4,468 | 0.5510 | 0.1739 | 0.6741 | 0.6209 | 0.6394 | 0.6773 | +0.183 | +0.113 | +0.138 |
| 3-4 | 9,144 | 0.5224 | 0.1749 | 0.6813 | 0.6335 | 0.6325 | 0.6827 | +0.233 | +0.175 | +0.174 |
| 5-7 | 28,971 | 0.6240 | 0.2172 | 0.6909 | 0.6545 | 0.6492 | 0.6891 | +0.097 | +0.047 | +0.039 |
| 8-10 | 38,523 | 0.6338 | 0.2215 | 0.6941 | 0.6662 | 0.6612 | 0.6906 | +0.087 | +0.049 | +0.041 |

*situation*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| below par | 16,541 | 0.5201 | 0.1692 | 0.6723 | 0.6221 | 0.6044 | 0.6762 | +0.226 | +0.164 | +0.139 |
| near par | 30,758 | 0.6389 | 0.2241 | 0.6864 | 0.6516 | 0.6796 | 0.6889 | +0.069 | +0.020 | +0.060 |
| above par | 33,807 | 0.6390 | 0.2238 | 0.7039 | 0.6779 | 0.6533 | 0.6947 | +0.092 | +0.057 | +0.022 |

#### Model selection (validation partition)

| Candidate | Validation log loss | Validation Brier |
|---|---:|---:|
| logistic_C=0.01 | 0.5973 | 0.2055 |
| logistic_C=0.1 | 0.5921 | 0.2036 |
| logistic_C=1.0 | 0.5914 | 0.2034 |
| logistic_C=10.0 | 0.5914 | 0.2034 |
| hgb_depth=2_iter=50 | 0.5956 | 0.2043 |
| hgb_depth=2_iter=100 ✅ | 0.5898 | 0.2023 |
| hgb_depth=2_iter=300 | 0.5953 | 0.2047 |
| hgb_depth=2_iter=600 | 0.6041 | 0.2084 |
| hgb_depth=3_iter=50 | 0.5933 | 0.2035 |
| hgb_depth=3_iter=100 | 0.5943 | 0.2044 |
| hgb_depth=3_iter=300 | 0.5976 | 0.2061 |
| hgb_depth=3_iter=600 | 0.6151 | 0.2123 |
| hgb_depth=4_iter=50 | 0.5950 | 0.2046 |
| hgb_depth=4_iter=100 | 0.5929 | 0.2039 |
| hgb_depth=4_iter=300 | 0.6146 | 0.2115 |
| hgb_depth=4_iter=600 | 0.6630 | 0.2279 |
| hgb_depth=6_iter=50 | 0.5994 | 0.2067 |
| hgb_depth=6_iter=100 | 0.6066 | 0.2099 |
| hgb_depth=6_iter=300 | 0.6448 | 0.2230 |
| hgb_depth=6_iter=600 | 0.7030 | 0.2384 |
| hgb_depth=2_iter=100_monotone | 0.5916 | 0.2031 |

Calibration chosen by match-grouped 4-fold CV inside the calibration partition: **isotonic** (none 0.6376, sigmoid 0.6344, isotonic 0.6332).

### Innings 2

Calibration plot: [plots/odm_innings2.svg](plots/odm_innings2.svg)

| Model | Log loss [95% CI] | Brier [95% CI] | ECE | Skill vs prior [95% CI] | Skill vs Elo | Skill vs venue-par |
|---|---|---|---|---|---|---|
| **v2 model (calibrated, deployed)** | 0.4441 [0.375, 0.511] | 0.1409 [0.118, 0.162] | 0.0525 | +0.357 [0.259, 0.456] | +0.323 | +0.264 |
| v2 model, uncalibrated | 0.4373 [0.379, 0.500] | 0.1414 [0.120, 0.163] | 0.0511 | +0.367 [0.274, 0.450] | +0.333 | +0.275 |
| v2 + Platt/sigmoid | 0.4441 [0.375, 0.511] | 0.1409 [0.118, 0.162] | 0.0525 | +0.357 [0.259, 0.456] | +0.323 | +0.264 |
| v2 + isotonic | 0.4946 [0.409, 0.589] | 0.1407 [0.118, 0.161] | 0.0434 | +0.284 [0.146, 0.406] | +0.246 | +0.180 |
| best logistic regression (new features) | 0.4373 [0.379, 0.500] | 0.1414 [0.120, 0.163] | 0.0511 | +0.367 [0.274, 0.450] | +0.333 | +0.275 |
| legacy v1 logistic (C=1e-4, team1 features) | 0.6802 [0.677, 0.683] | 0.2435 [0.242, 0.245] | 0.1556 | +0.015 [0.007, 0.023] | -0.037 | -0.128 |
| venue-par baseline | 0.6031 [0.557, 0.655] | 0.2080 [0.189, 0.229] | 0.0741 | +0.126 [0.051, 0.193] | +0.080 | — |
| Elo-only baseline | 0.6556 [0.640, 0.672] | 0.2315 [0.224, 0.240] | 0.0601 | +0.050 [0.027, 0.070] | — | -0.087 |
| constant prior | 0.6903 [0.686, 0.695] | 0.2486 [0.246, 0.251] | 0.0268 | — | -0.053 | -0.145 |

#### Segments

*phase*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| powerplay (1-10) | 17,455 | 0.5471 | 0.1761 | 0.6884 | 0.6452 | 0.5768 | 0.6788 | +0.205 | +0.152 | +0.052 |
| middle (11-40) | 45,442 | 0.4162 | 0.1309 | 0.6912 | 0.6568 | 0.6032 | 0.6800 | +0.398 | +0.366 | +0.310 |
| death (41-50) | 6,291 | 0.3036 | 0.0976 | 0.6894 | 0.6837 | 0.6988 | 0.6861 | +0.560 | +0.556 | +0.566 |

*wickets remaining*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1-2 | 3,474 | 0.2240 | 0.0740 | 0.7221 | 0.6812 | 0.5696 | 0.6604 | +0.690 | +0.671 | +0.607 |
| 3-4 | 7,731 | 0.4035 | 0.1262 | 0.7098 | 0.6781 | 0.6464 | 0.6805 | +0.432 | +0.405 | +0.376 |
| 5-7 | 24,411 | 0.4552 | 0.1388 | 0.6915 | 0.6674 | 0.6312 | 0.6849 | +0.342 | +0.318 | +0.279 |
| 8-10 | 33,572 | 0.4670 | 0.1521 | 0.6822 | 0.6404 | 0.5783 | 0.6789 | +0.315 | +0.271 | +0.192 |

*required run rate*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| <4.5 | 19,857 | 0.3478 | 0.1049 | 0.6652 | 0.6102 | 0.5141 | 0.6720 | +0.477 | +0.430 | +0.324 |
| 4.5-6 | 19,284 | 0.6017 | 0.2037 | 0.6871 | 0.6806 | 0.7443 | 0.6900 | +0.124 | +0.116 | +0.192 |
| 6-7.5 | 15,845 | 0.5454 | 0.1753 | 0.7049 | 0.6802 | 0.6545 | 0.6890 | +0.226 | +0.198 | +0.167 |
| 7.5-9 | 7,552 | 0.3917 | 0.1079 | 0.7186 | 0.6616 | 0.5808 | 0.6799 | +0.455 | +0.408 | +0.326 |
| 9+ | 6,650 | 0.1832 | 0.0554 | 0.7275 | 0.6899 | 0.4404 | 0.6628 | +0.748 | +0.734 | +0.584 |

*situation*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ahead of par (<0.8) | 20,094 | 0.3045 | 0.0852 | 0.6625 | 0.6165 | 0.5200 | 0.6720 | +0.540 | +0.506 | +0.414 |
| balanced (0.8-1.2) | 24,245 | 0.6413 | 0.2234 | 0.6873 | 0.6709 | 0.7662 | 0.6932 | +0.067 | +0.044 | +0.163 |
| behind par (>1.2) | 24,849 | 0.3940 | 0.1174 | 0.7202 | 0.6792 | 0.5301 | 0.6758 | +0.453 | +0.420 | +0.257 |

#### Model selection (validation partition)

| Candidate | Validation log loss | Validation Brier |
|---|---:|---:|
| logistic_C=0.01 | 0.3954 | 0.1261 |
| logistic_C=0.1 | 0.3701 | 0.1200 |
| logistic_C=1.0 ✅ | 0.3694 | 0.1200 |
| logistic_C=10.0 | 0.3706 | 0.1203 |
| hgb_depth=2_iter=50 | 0.3988 | 0.1260 |
| hgb_depth=2_iter=100 | 0.3797 | 0.1213 |
| hgb_depth=2_iter=300 | 0.3762 | 0.1218 |
| hgb_depth=2_iter=600 | 0.3833 | 0.1244 |
| hgb_depth=3_iter=50 | 0.3875 | 0.1221 |
| hgb_depth=3_iter=100 | 0.3734 | 0.1200 |
| hgb_depth=3_iter=300 | 0.3771 | 0.1221 |
| hgb_depth=3_iter=600 | 0.4000 | 0.1295 |
| hgb_depth=4_iter=50 | 0.3841 | 0.1210 |
| hgb_depth=4_iter=100 | 0.3711 | 0.1193 |
| hgb_depth=4_iter=300 | 0.3852 | 0.1243 |
| hgb_depth=4_iter=600 | 0.4248 | 0.1350 |
| hgb_depth=6_iter=50 | 0.3858 | 0.1219 |
| hgb_depth=6_iter=100 | 0.3759 | 0.1214 |
| hgb_depth=6_iter=300 | 0.4029 | 0.1291 |
| hgb_depth=6_iter=600 | 0.4540 | 0.1403 |
| hgb_depth=4_iter=100_monotone | 0.3725 | 0.1200 |

Calibration chosen by match-grouped 4-fold CV inside the calibration partition: **sigmoid** (none 0.3262, sigmoid 0.3260, isotonic 0.3366).

### Resource table (expected runs remaining, training first innings)

| Balls remaining | 0 down | 2 down | 4 down | 6 down | 8 down |
|---:|---:|---:|---:|---:|---:|
| 300 | 243.0 | 189.8 | 127.2 | 82.5 | 60.5 |
| 150 | 176.0 | 161.5 | 125.0 | 75.9 | 50.1 |
| 75 | 125.2 | 122.3 | 86.1 | 64.5 | 39.4 |
| 12 | 103.4 | 98.4 | 43.5 | 20.2 | 6.7 |

## Test (Test)

| Partition | From | To | Matches |
|---|---|---|---:|
| train | 2001-12-19 | 2017-08-27 | 554 |
| validation | 2017-09-04 | 2021-02-24 | 138 |
| calibration | 2021-03-04 | 2023-04-24 | 93 |
| test | 2023-06-01 | 2026-10-28 | 138 |

Unlabelled (excluded from training/evaluation): 0 matches (no result or tie).

State audit: pre delivery states 1,762,181, invalid states excluded 0, terminal pre delivery states excluded 0, unlabelled states excluded 0

### Test partition (three-class: batting win / bowling win / draw)

| Model | Log loss [95% CI] | Brier [95% CI] | RPS | ECE | Skill vs prior [95% CI] | Skill vs Elo | Skill vs venue-par |
|---|---|---|---|---|---|---|---|
| **v2 model (calibrated, deployed)** | 0.7266 [0.636, 0.820] | 0.4340 [0.371, 0.498] | 0.1759 | 0.0700 | +0.267 [0.174, 0.354] | +0.214 | +0.177 |
| v2 model, uncalibrated | 0.7266 [0.636, 0.820] | 0.4340 [0.371, 0.498] | 0.1759 | 0.0700 | +0.267 [0.174, 0.354] | +0.214 | +0.177 |
| v2 + Platt/sigmoid | 0.7608 [0.670, 0.853] | 0.4595 [0.400, 0.519] | 0.1812 | 0.0788 | +0.233 [0.146, 0.318] | +0.177 | +0.139 |
| v2 + isotonic | 0.7652 [0.660, 0.871] | 0.4511 [0.389, 0.513] | 0.1800 | 0.0761 | +0.228 [0.123, 0.328] | +0.172 | +0.133 |
| best logistic regression (new features) | 0.7266 [0.636, 0.820] | 0.4340 [0.371, 0.498] | 0.1759 | 0.0700 | +0.267 [0.174, 0.354] | +0.214 | +0.177 |
| legacy v1 logistic (C=1e-4, team1 features) | 0.9848 [0.952, 1.021] | 0.5942 [0.571, 0.621] | 0.2524 | 0.1142 | +0.007 [-0.024, 0.032] | -0.066 | -0.115 |
| venue-par baseline | 0.8831 [0.833, 0.941] | 0.5190 [0.485, 0.559] | 0.2135 | 0.1228 | +0.110 [0.057, 0.155] | +0.044 | — |
| Elo-only baseline | 0.9242 [0.851, 1.015] | 0.5400 [0.491, 0.602] | 0.2268 | 0.1109 | +0.068 [-0.022, 0.138] | — | -0.047 |
| constant prior | 0.9918 [0.974, 1.013] | 0.6014 [0.590, 0.614] | 0.2558 | 0.1130 | — | -0.073 | -0.123 |

Per-class calibration error (ECE) of the deployed model: batting_win 0.0559, bowling_win 0.0571, draw 0.0971

Calibration plots: [batting_win](plots/test_batting_win.svg), [bowling_win](plots/test_bowling_win.svg), [draw](plots/test_draw.svg)

### Segments (test partition)

*innings*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| innings 1 | 12,213 | 0.8857 | 0.5275 | 0.9932 | 0.9109 | 0.9487 | 0.9786 | +0.108 | +0.028 | +0.066 |
| innings 2 | 11,710 | 0.7537 | 0.4578 | 0.9913 | 0.9213 | 0.9458 | 1.0312 | +0.240 | +0.182 | +0.203 |
| innings 3 | 9,648 | 0.6521 | 0.3892 | 0.9892 | 0.9171 | 0.7755 | 0.9690 | +0.341 | +0.289 | +0.159 |
| innings 4 | 5,356 | 0.4251 | 0.2401 | 0.9946 | 0.9761 | 0.7844 | 0.9215 | +0.573 | +0.564 | +0.458 |

*match stage overs*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-90 | 12,558 | 0.8468 | 0.5086 | 0.9823 | 0.8928 | 0.9820 | 1.0018 | +0.138 | +0.052 | +0.138 |
| 90-180 | 12,208 | 0.6735 | 0.4061 | 0.9837 | 0.8968 | 0.8543 | 0.9883 | +0.315 | +0.249 | +0.212 |
| 180-270 | 9,469 | 0.6579 | 0.3896 | 0.9987 | 0.9641 | 0.7978 | 0.9683 | +0.341 | +0.318 | +0.175 |
| 270-360 | 4,165 | 0.6640 | 0.3798 | 1.0239 | 1.0212 | 0.8238 | 0.9375 | +0.351 | +0.350 | +0.194 |
| 360+ | 527 | 0.4163 | 0.2453 | 1.1658 | 1.1746 | 0.8752 | 1.0678 | +0.643 | +0.646 | +0.524 |

*wickets remaining*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1-2 | 3,491 | 0.6057 | 0.3680 | 0.9883 | 0.9027 | 0.9413 | 0.9797 | +0.387 | +0.329 | +0.357 |
| 3-4 | 6,183 | 0.6560 | 0.3948 | 0.9904 | 0.9379 | 0.8810 | 0.9713 | +0.338 | +0.301 | +0.255 |
| 5-7 | 14,378 | 0.7341 | 0.4363 | 0.9924 | 0.9216 | 0.8719 | 0.9866 | +0.260 | +0.203 | +0.158 |
| 8-10 | 14,875 | 0.7777 | 0.4639 | 0.9927 | 0.9261 | 0.8808 | 0.9899 | +0.217 | +0.160 | +0.117 |

### Model selection (validation partition)

| Candidate | Validation log loss | Validation Brier |
|---|---:|---:|
| logistic_C=0.01 | 0.8098 | 0.4694 |
| logistic_C=0.1 | 0.7515 | 0.4397 |
| logistic_C=1.0 ✅ | 0.7392 | 0.4366 |
| logistic_C=10.0 | 0.7418 | 0.4381 |
| hgb_depth=2_iter=50 | 0.8368 | 0.4946 |
| hgb_depth=2_iter=100 | 0.7973 | 0.4732 |
| hgb_depth=2_iter=300 | 0.7835 | 0.4723 |
| hgb_depth=2_iter=600 | 0.8201 | 0.4974 |
| hgb_depth=3_iter=50 | 0.8186 | 0.4862 |
| hgb_depth=3_iter=100 | 0.7989 | 0.4785 |
| hgb_depth=3_iter=300 | 0.8146 | 0.4924 |
| hgb_depth=3_iter=600 | 0.8620 | 0.5130 |
| hgb_depth=4_iter=50 | 0.8071 | 0.4810 |
| hgb_depth=4_iter=100 | 0.7947 | 0.4788 |
| hgb_depth=4_iter=300 | 0.8354 | 0.5045 |
| hgb_depth=4_iter=600 | 0.8772 | 0.5184 |
| hgb_depth=6_iter=50 | 0.8105 | 0.4874 |
| hgb_depth=6_iter=100 | 0.8032 | 0.4878 |
| hgb_depth=6_iter=300 | 0.8740 | 0.5261 |
| hgb_depth=6_iter=600 | 0.9555 | 0.5500 |
| hgb_monotone_attempt | not supported: monotonic constraints are not supported for multiclass classification. | |

Calibration chosen by match-grouped 4-fold CV inside the calibration partition: **none** (none 0.7776, sigmoid 0.7851, isotonic 0.8085).

## MDM (MDM)

| Partition | From | To | Matches |
|---|---|---|---:|
| train | 2006-12-05 | 2022-07-25 | 1,345 |
| validation | 2022-07-26 | 2024-06-23 | 337 |
| calibration | 2024-06-30 | 2025-05-09 | 222 |
| test | 2025-05-16 | 2026-10-31 | 336 |

Unlabelled (excluded from training/evaluation): 2 matches (no result or tie).

State audit: pre delivery states 3,784,304, invalid states excluded 0, terminal pre delivery states excluded 15, unlabelled states excluded 3,231

### Test partition (three-class: batting win / bowling win / draw)

| Model | Log loss [95% CI] | Brier [95% CI] | RPS | ECE | Skill vs prior [95% CI] | Skill vs Elo | Skill vs venue-par |
|---|---|---|---|---|---|---|---|
| **v2 model (calibrated, deployed)** | 0.8851 [0.827, 0.936] | 0.5331 [0.498, 0.564] | 0.1625 | 0.0408 | +0.187 [0.142, 0.239] | +0.194 | +0.157 |
| v2 model, uncalibrated | 0.8865 [0.848, 0.919] | 0.5339 [0.509, 0.556] | 0.1618 | 0.0423 | +0.186 [0.157, 0.219] | +0.193 | +0.156 |
| v2 + Platt/sigmoid | 0.8851 [0.827, 0.936] | 0.5331 [0.498, 0.564] | 0.1625 | 0.0408 | +0.187 [0.142, 0.239] | +0.194 | +0.157 |
| v2 + isotonic | 0.8794 [0.822, 0.926] | 0.5303 [0.496, 0.558] | 0.1613 | 0.0349 | +0.192 [0.151, 0.243] | +0.199 | +0.162 |
| best logistic regression (new features) | 0.9219 [0.882, 0.957] | 0.5593 [0.533, 0.581] | 0.1734 | 0.0441 | +0.153 [0.122, 0.189] | +0.161 | +0.122 |
| legacy v1 logistic (C=1e-4, team1 features) | 1.0761 [1.070, 1.082] | 0.6516 [0.647, 0.655] | 0.2011 | 0.0498 | +0.011 [0.010, 0.014] | +0.020 | -0.025 |
| venue-par baseline | 1.0498 [1.033, 1.067] | 0.6400 [0.630, 0.651] | 0.1956 | 0.0501 | +0.036 [0.020, 0.049] | +0.044 | — |
| Elo-only baseline | 1.0983 [1.073, 1.125] | 0.6655 [0.650, 0.681] | 0.2076 | 0.0678 | -0.009 [-0.032, 0.013] | — | -0.046 |
| constant prior | 1.0886 [1.083, 1.095] | 0.6599 [0.656, 0.664] | 0.2042 | 0.0503 | — | +0.009 | -0.037 |

Per-class calibration error (ECE) of the deployed model: batting_win 0.0431, bowling_win 0.0335, draw 0.0457

Calibration plots: [batting_win](plots/mdm_batting_win.svg), [bowling_win](plots/mdm_bowling_win.svg), [draw](plots/mdm_draw.svg)

### Segments (test partition)

*innings*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| innings 1 | 31,001 | 1.0137 | 0.6113 | 1.0806 | 1.0914 | 1.0654 | 1.0730 | +0.062 | +0.071 | +0.049 |
| innings 2 | 29,151 | 0.8837 | 0.5344 | 1.0821 | 1.0835 | 1.0353 | 1.0672 | +0.183 | +0.184 | +0.146 |
| innings 3 | 23,171 | 0.7834 | 0.4768 | 1.0971 | 1.1090 | 1.0402 | 1.0829 | +0.286 | +0.294 | +0.247 |
| innings 4 | 10,091 | 0.6988 | 0.3993 | 1.1153 | 1.1419 | 1.0644 | 1.0973 | +0.373 | +0.388 | +0.343 |

*match stage overs*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0-90 | 30,574 | 1.0365 | 0.6202 | 1.0859 | 1.0919 | 1.0959 | 1.0808 | +0.046 | +0.051 | +0.054 |
| 90-180 | 29,598 | 0.9124 | 0.5547 | 1.0891 | 1.0961 | 1.0366 | 1.0722 | +0.162 | +0.168 | +0.120 |
| 180-270 | 24,044 | 0.7316 | 0.4419 | 1.0920 | 1.1073 | 0.9989 | 1.0734 | +0.330 | +0.339 | +0.268 |
| 270-360 | 8,977 | 0.5886 | 0.3457 | 1.0881 | 1.1097 | 1.0622 | 1.0799 | +0.459 | +0.470 | +0.446 |
| 360+ | 221 | 0.6044 | 0.3943 | 1.0695 | 1.0392 | 0.9722 | 1.0712 | +0.435 | +0.418 | +0.378 |

*wickets remaining*

| Segment | States | v2 log loss | v2 Brier | Prior LL | Elo LL | Venue-par LL | Legacy v1 LL | Skill vs prior | Skill vs Elo | Skill vs venue-par |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1-2 | 9,296 | 0.8310 | 0.5003 | 1.0995 | 1.1140 | 1.0570 | 1.0831 | +0.244 | +0.254 | +0.214 |
| 3-4 | 15,717 | 0.8719 | 0.5237 | 1.0939 | 1.1076 | 1.0261 | 1.0775 | +0.203 | +0.213 | +0.150 |
| 5-7 | 33,466 | 0.8615 | 0.5194 | 1.0867 | 1.0962 | 1.0287 | 1.0727 | +0.207 | +0.214 | +0.163 |
| 8-10 | 34,935 | 0.9282 | 0.5591 | 1.0851 | 1.0921 | 1.0787 | 1.0768 | +0.145 | +0.150 | +0.140 |

### Model selection (validation partition)

| Candidate | Validation log loss | Validation Brier |
|---|---:|---:|
| logistic_C=0.01 | 0.9349 | 0.5644 |
| logistic_C=0.1 | 0.9000 | 0.5442 |
| logistic_C=1.0 | 0.8967 | 0.5424 |
| logistic_C=10.0 | 0.8979 | 0.5430 |
| hgb_depth=2_iter=50 | 0.9107 | 0.5463 |
| hgb_depth=2_iter=100 | 0.8905 | 0.5356 |
| hgb_depth=2_iter=300 | 0.9115 | 0.5487 |
| hgb_depth=2_iter=600 | 0.9296 | 0.5557 |
| hgb_depth=3_iter=50 | 0.8882 | 0.5341 |
| hgb_depth=3_iter=100 | 0.8895 | 0.5372 |
| hgb_depth=3_iter=300 | 0.9272 | 0.5544 |
| hgb_depth=3_iter=600 | 0.9568 | 0.5687 |
| hgb_depth=4_iter=50 ✅ | 0.8833 | 0.5311 |
| hgb_depth=4_iter=100 | 0.8925 | 0.5382 |
| hgb_depth=4_iter=300 | 0.9293 | 0.5577 |
| hgb_depth=4_iter=600 | 0.9896 | 0.5846 |
| hgb_depth=6_iter=50 | 0.8884 | 0.5361 |
| hgb_depth=6_iter=100 | 0.9003 | 0.5446 |
| hgb_depth=6_iter=300 | 0.9911 | 0.5883 |
| hgb_depth=6_iter=600 | 1.1044 | 0.6321 |
| hgb_monotone_attempt | not supported: monotonic constraints are not supported for multiclass classification. | |

Calibration chosen by match-grouped 4-fold CV inside the calibration partition: **sigmoid** (none 0.8748, sigmoid 0.8618, isotonic 0.8687).

