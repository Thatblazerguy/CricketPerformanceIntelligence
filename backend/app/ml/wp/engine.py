"""Runtime win-probability predictor shared by the API, simulator and precompute job.

All model outputs are batting-side probabilities. Decided matches are resolved by
the Laws (target reached, all out, overs exhausted) rather than by the model; the
model is never asked about a finished match and no probability is hard-coded for
an undecided one.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from . import features as F
from . import modeling as M
from .constants import FULL_BALLS, GROUP_OF_FORMAT, MIN_SUPPORT

ARTIFACT_DIR = Path(__file__).resolve().parents[3] / "artifacts" / "win_probability" / "v2"


class ModelUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=8)
def load_bundle(group: str, artifact_dir: Optional[str] = None) -> dict:
    import joblib

    path = Path(artifact_dir or ARTIFACT_DIR) / f"{group.lower()}.joblib"
    if not path.exists():
        raise ModelUnavailable(f"No trained {group} win-probability model ({path.name}); run scripts/train_win_probability_v2.py")
    return joblib.load(path)


class WinProbabilityEngine:
    def __init__(self, bundle: dict):
        self.bundle = bundle
        self.group = bundle["group"]
        self.version = bundle["version"]
        self.kind = bundle["kind"]

    @classmethod
    def for_format(cls, match_format: str, artifact_dir: Optional[str] = None) -> "WinProbabilityEngine":
        group = GROUP_OF_FORMAT.get(match_format)
        if group is None:
            raise ModelUnavailable(f"No win-probability model for format {match_format!r}")
        return cls(load_bundle(group, artifact_dir))

    # ------------------------------------------------------------------ context
    def _context(self, gender: str, batting_team_id=None, bowling_team_id=None, venue_id=None):
        ctx = self.bundle["context"]
        notes = []
        pool_prefix = next(iter(ctx["elo"]), "t20|").split("|")[0]
        def rating(team):
            item = ctx["elo"].get(f"{pool_prefix}|{gender}|{team}") if team else None
            return item
        rb, rw = rating(batting_team_id), rating(bowling_team_id)
        if rb and rw:
            elo_diff = rb["rating"] - rw["rating"]
        else:
            elo_diff = 0.0
            notes.append("Team strength unknown for at least one side; Elo difference set to 0 (equal teams).")
        era = (ctx["era"].get(f"{self.group}|{gender}") or {}).get("par")
        venue = (ctx["venue"].get(f"{self.group}|{gender}|{venue_id}") or {}).get("par") if venue_id else None
        if venue is None:
            notes.append("No venue history; venue par set to the current era par.")
            venue = era
        return {"elo_diff": elo_diff, "era_par": era, "venue_par": venue}, notes

    # ------------------------------------------------------------------ limited
    def predict_limited_frame(self, raw: pd.DataFrame) -> pd.DataFrame:
        """Vectorised batting-side prediction for raw limited-overs states.

        Returns columns ``batting_win``, ``tie``, ``status`` ('model' | 'decided' |
        'invalid'), ``support`` and ``confidence``. Completed first innings are
        evaluated as the start of the chase (and flipped back to the side that batted).
        """
        if self.kind != "limited":
            raise ModelUnavailable("Not a limited-overs model")
        raw = raw.reset_index(drop=True).copy()
        full = FULL_BALLS[self.group]
        n = len(raw)
        out = pd.DataFrame({"batting_win": np.full(n, np.nan), "tie": np.zeros(n), "status": "invalid",
                            "support": np.zeros(n), "confidence": "n/a"})
        valid = F.validate_limited(raw, self.group)
        # Innings 1 finished: the match continues as innings 2 from ball 0.
        inn1_done = valid & (raw["innings"].to_numpy() == 1) & (
            (raw["wickets_lost"].to_numpy() >= 10) | (raw["legal_balls"].to_numpy() >= raw["max_balls"].to_numpy()))
        work = raw.copy()
        if inn1_done.any():
            idx = np.where(inn1_done)[0]
            work.loc[idx, "target"] = raw.loc[idx, "runs"] + 1
            work.loc[idx, ["innings", "runs", "wickets_lost", "legal_balls"]] = [2, 0, 0, 0]
            work.loc[idx, "max_balls"] = full
            work.loc[idx, "elo_diff"] = -raw.loc[idx, "elo_diff"]
            work.loc[idx, "batting_won_toss"] = 1 - raw.loc[idx, "batting_won_toss"]
        decided = F.limited_terminal(work)
        dec = valid & ~np.isnan(decided)
        out.loc[dec, "batting_win"] = np.where(decided[dec] == 0.5, 0.0, decided[dec])
        out.loc[dec, "tie"] = (decided[dec] == 0.5).astype(float)
        out.loc[dec, "status"] = "decided"
        for innings in (1, 2):
            m = valid & ~dec & (work["innings"].to_numpy() == innings)
            if not m.any():
                continue
            spec = self.bundle["models"][innings]
            X = F.limited_features(work[m], innings, self.bundle["resource_table"])
            p = spec["calibrator"].transform(M.predict(spec["model"], X.to_numpy(np.float64)))
            out.loc[m, "batting_win"] = p
            out.loc[m, "status"] = "model"
            table = spec.get("support_table")
            if table is not None:
                b = np.clip(X["balls_remaining"].to_numpy(int), 0, full)
                w = np.clip(X["wickets_lost"].to_numpy(int), 0, 10)
                cum = np.vstack([np.zeros((1, 11)), np.cumsum(table, axis=0)])
                lo, hi = np.clip(b - 6, 0, full), np.clip(b + 7, 0, full + 1)
                out.loc[m, "support"] = cum[hi, w] - cum[lo, w]
        out.loc[inn1_done & (out["status"] == "model").to_numpy(), "batting_win"] = \
            1 - out.loc[inn1_done & (out["status"] == "model").to_numpy(), "batting_win"]
        model_rows = out["status"] == "model"
        out.loc[model_rows, "confidence"] = np.where(out.loc[model_rows, "support"] >= MIN_SUPPORT, "normal", "low")
        out.loc[out["status"] == "decided", "confidence"] = "certain"
        return out

    def predict_limited(self, *, innings: int, runs: int, wickets_lost: int, legal_balls: int,
                        target: Optional[int] = None, max_balls: Optional[int] = None, gender: str = "male",
                        batting_team_id: Optional[str] = None, bowling_team_id: Optional[str] = None,
                        venue_id: Optional[str] = None, international: Optional[bool] = None,
                        batting_won_toss: Optional[bool] = None, elo_diff: Optional[float] = None,
                        venue_par: Optional[float] = None, era_par: Optional[float] = None) -> dict:
        """Probability that the side currently batting wins.

        Raises ``features.InvalidStateError`` for impossible states.
        """
        full = FULL_BALLS[self.group]
        if innings not in (1, 2):
            raise F.InvalidStateError("Limited-overs innings must be 1 or 2 (super overs are not modelled)")
        if innings == 2 and (target is None or target < 1):
            raise F.InvalidStateError("A chase needs a target of at least 1 run")
        if innings == 1 and target is not None:
            raise F.InvalidStateError("The first innings has no target")
        mb = int(max_balls if max_balls is not None else full)
        if not 0 < mb <= full:
            raise F.InvalidStateError(f"Innings length must be 1-{full} balls")
        if runs < 0 or legal_balls < 0 or not 0 <= wickets_lost <= 10:
            raise F.InvalidStateError("Runs/balls must be non-negative and wickets between 0 and 10")
        if legal_balls > mb:
            raise F.InvalidStateError(f"{legal_balls} legal balls exceeds the {mb}-ball innings")
        if innings == 2 and runs >= target + 6 + 1:
            # A chase stops when the target is reached; the last ball can add at most a six (+ no-ball run).
            raise F.InvalidStateError("Chasing score is impossible: the chase would already have ended")
        ctx, notes = self._context(gender, batting_team_id, bowling_team_id, venue_id)
        if elo_diff is not None:
            ctx["elo_diff"] = elo_diff
            notes = [x for x in notes if not x.startswith("Team strength")]
        if venue_par is not None:
            ctx["venue_par"] = venue_par
            notes = [x for x in notes if not x.startswith("No venue")]
        if era_par is not None:
            ctx["era_par"] = era_par
        raw = pd.DataFrame([{
            "innings": innings, "runs": runs, "wickets_lost": wickets_lost, "legal_balls": legal_balls,
            "target": float(target) if target is not None else np.nan, "max_balls": mb,
            "elo_diff": ctx["elo_diff"], "venue_par": ctx["venue_par"], "era_par": ctx["era_par"],
            "batting_won_toss": float(bool(batting_won_toss)) if batting_won_toss is not None else 0.5,
            "female": float(str(gender).casefold() in {"female", "women", "women's"}),
            "international": float(bool(international)) if international is not None else
            (1.0 if self.group == "ODI" else 0.0),
        }])
        row = self.predict_limited_frame(raw).iloc[0]
        if row["status"] == "invalid":
            raise F.InvalidStateError("State failed validation")
        p = float(row["batting_win"])
        tie = float(row["tie"])
        if row["status"] == "model" and row["confidence"] == "low":
            notes.append(f"Few comparable training states (support {int(row['support'])} < {MIN_SUPPORT}); treat as low confidence.")
        return {"status": row["status"], "batting_team_win": round(p, 6),
                "bowling_team_win": round(1 - p - tie, 6), "draw_or_tie": round(tie, 6),
                "confidence": row["confidence"], "support_states": int(row["support"]),
                "model_version": self.version, "notes": notes}

    # ------------------------------------------------------------------ multi-day
    def predict_multiday_frame(self, raw: pd.DataFrame) -> pd.DataFrame:
        if self.kind != "multiday":
            raise ModelUnavailable("Not a multi-day model")
        raw = raw.reset_index(drop=True)
        n = len(raw)
        out = pd.DataFrame({"batting_win": np.full(n, np.nan), "bowling_win": np.full(n, np.nan),
                            "draw": np.full(n, np.nan), "status": "invalid", "support": np.zeros(n), "confidence": "n/a"})
        valid = F.validate_multiday(raw)
        decided = F.multiday_terminal(raw)
        dec = valid & ~np.isnan(decided)
        for code, col in ((0, "batting_win"), (1, "bowling_win")):
            out.loc[dec, col] = (decided[dec] == code).astype(float)
        out.loc[dec, "draw"] = (decided[dec] == 3).astype(float)  # tie reported in the draw/tie column
        out.loc[dec, "status"] = "decided"
        out.loc[dec, "confidence"] = "certain"
        m = valid & ~dec
        if m.any():
            spec = self.bundle["models"]["all"]
            X = F.multiday_features(raw[m])
            p = spec["calibrator"].transform(M.predict(spec["model"], X.to_numpy(np.float64), 3))
            out.loc[m, ["batting_win", "bowling_win", "draw"]] = p
            out.loc[m, "status"] = "model"
            keys = F.multiday_support_key(raw.loc[m, "innings"], raw.loc[m, "wickets_lost"], raw.loc[m, "match_legal_balls"])
            table = spec.get("support_table") or {}
            sup = np.array([table.get(int(k), 0) for k in keys], dtype=float)
            out.loc[m, "support"] = sup
            out.loc[m, "confidence"] = np.where(sup >= MIN_SUPPORT, "normal", "low")
        return out

    def predict_multiday(self, *, innings: int, runs: int, wickets_lost: int, legal_balls: int,
                         match_legal_balls: int, batting_prior_runs: int, opposition_runs: int,
                         gender: str = "male", batting_team_id=None, bowling_team_id=None, venue_id=None,
                         international: Optional[bool] = None, batting_won_toss: Optional[bool] = None,
                         elo_diff: Optional[float] = None) -> dict:
        if innings not in (1, 2, 3, 4):
            raise F.InvalidStateError("Multi-day innings must be 1-4")
        ctx, notes = self._context(gender, batting_team_id, bowling_team_id, venue_id)
        if elo_diff is not None:
            ctx["elo_diff"] = elo_diff
            notes = [x for x in notes if not x.startswith("Team strength")]
        raw = pd.DataFrame([{
            "innings": innings, "runs": runs, "wickets_lost": wickets_lost, "legal_balls": legal_balls,
            "match_legal_balls": match_legal_balls, "batting_prior_runs": batting_prior_runs,
            "opposition_runs": opposition_runs, "elo_diff": ctx["elo_diff"], "venue_par": ctx["venue_par"],
            "era_par": ctx["era_par"],
            "batting_won_toss": float(bool(batting_won_toss)) if batting_won_toss is not None else 0.5,
            "female": float(str(gender).casefold() in {"female", "women", "women's"}),
            "international": float(bool(international)) if international is not None else float(self.group == "Test"),
        }])
        row = self.predict_multiday_frame(raw).iloc[0]
        if row["status"] == "invalid":
            raise F.InvalidStateError("Impossible multi-day state (check innings totals, wickets and balls)")
        if row["status"] == "model" and row["confidence"] == "low":
            notes.append(f"Few comparable training states (support {int(row['support'])} < {MIN_SUPPORT}); treat as low confidence.")
        notes.append("Declarations, follow-on decisions and time remaining are not recorded in CPI data; the draw "
                     "probability is driven by overs already bowled in the match.")
        return {"status": row["status"], "batting_team_win": round(float(row["batting_win"]), 6),
                "bowling_team_win": round(float(row["bowling_win"]), 6), "draw_or_tie": round(float(row["draw"]), 6),
                "confidence": row["confidence"], "support_states": int(row["support"]),
                "model_version": self.version, "notes": notes}
