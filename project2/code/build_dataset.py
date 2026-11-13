#!/usr/bin/env python3
"""ECON 438 Project 2: build the model-ready monthly dataset.

Reads only data/raw/ (filled by fetch_data.py) and writes:

    data/clean/approval_polls.csv       poll-level Gallup approval, cleaned
    data/clean/analysis_monthly.csv     one row per month, 1977m1-2025m12
    data/clean/analysis_monthly.dta     the same file for Stata
    data/clean/data_dictionary.csv      every column, its unit and source
    data/clean/figures/overview.png     the main series, for eyeballing
    data/qc_checks.json                 every quality check, machine-readable
    data/QC_REPORT.md                   the same checks plus every data fix

Usage:
    python project2/code/build_dataset.py
"""

from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

CODE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = CODE_DIR.parent
RAW = PROJECT_DIR / "data" / "raw"
CLEAN = PROJECT_DIR / "data" / "clean"
FIG = CLEAN / "figures"

SAMPLE_START, SAMPLE_END = pd.Period("1978-01", "M"), pd.Period("2025-12", "M")
LEAD_START = pd.Period("1977-01", "M")  # one lead-in year so lags exist at 1978m1
BUILD_START = pd.Period("1976-01", "M")  # internal start, so 12-month lags/fills exist at the lead-in

FIXES: list[dict] = []   # every change made to a source value, for the report
CHECKS: list[dict] = []  # every quality check, for the report


def fix(dataset: str, what: str, rows: int, action: str) -> None:
    FIXES.append({"dataset": dataset, "issue": what, "rows": int(rows), "action": action})


def check(cid: str, desc: str, passed: bool, detail: str = "") -> None:
    CHECKS.append({"id": cid, "check": desc, "passed": bool(passed), "detail": detail})
    print(f"[{'PASS' if passed else 'FAIL'}] {cid} {desc} {detail}")


# ---------------------------------------------------------------------------
# 1. Presidents
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class President:
    slug: str
    admin: str
    name: str
    party: str  # "D" or "R"
    start: str  # inauguration date
    end: str    # date left office (exclusive)
    second_term_start: str | None = None


PRESIDENTS = [
    President("gerald-r-ford", "ford", "Gerald R. Ford", "R", "1974-08-09", "1977-01-20"),
    President("jimmy-carter", "carter", "Jimmy Carter", "D", "1977-01-20", "1981-01-20"),
    President("ronald-reagan", "reagan", "Ronald Reagan", "R", "1981-01-20", "1989-01-20", "1985-01-20"),
    President("george-bush", "bush41", "George H. W. Bush", "R", "1989-01-20", "1993-01-20"),
    President("william-j-clinton", "clinton", "William J. Clinton", "D", "1993-01-20", "2001-01-20", "1997-01-20"),
    President("george-w-bush", "bush43", "George W. Bush", "R", "2001-01-20", "2009-01-20", "2005-01-20"),
    President("barack-obama", "obama", "Barack Obama", "D", "2009-01-20", "2017-01-20", "2013-01-20"),
    President("donald-j-trump", "trump1", "Donald J. Trump (1st term)", "R", "2017-01-20", "2021-01-20"),
    President("joseph-r-biden", "biden", "Joseph R. Biden", "D", "2021-01-20", "2025-01-20"),
    President("donald-j-trump-2nd-term", "trump2", "Donald J. Trump (2nd term)", "R", "2025-01-20", "2029-01-20"),
]
PRES = {p.admin: p for p in PRESIDENTS}


def president_on(date: pd.Timestamp) -> President:
    for p in PRESIDENTS:
        if pd.Timestamp(p.start) <= date < pd.Timestamp(p.end):
            return p
    raise ValueError(date)


# ---------------------------------------------------------------------------
# 2. Gallup polls (American Presidency Project pages)
# ---------------------------------------------------------------------------

def parse_date(s, start: pd.Timestamp | None, page: str) -> pd.Timestamp:
    """Parse m/d/Y. Repairs a mistyped year (e.g. 2/20/224) using the start date."""
    s = str(s).strip()
    m, d, y = s.split("/")
    if len(y) != 4:
        if start is None:
            raise ValueError(f"{page}: bad date {s}")
        fixed = pd.Timestamp(int(start.year), int(m), int(d))
        if fixed < start:  # poll ran over New Year
            fixed = pd.Timestamp(int(start.year) + 1, int(m), int(d))
        fix("Gallup/UCSB", f"{page}: mistyped year in end date '{s}'", 1,
            f"set to {fixed.date()} (year taken from the start date)")
        return fixed
    return pd.Timestamp(int(y), int(m), int(d))


MAX_FIELD_DAYS = 45  # Gallup's multi-week aggregates (2017-2024) run up to ~5 weeks


def repair_year(st: pd.Timestamp, en: pd.Timestamp, page: str,
                neighbours: list[pd.Timestamp]) -> tuple[pd.Timestamp, pd.Timestamp]:
    """A poll whose end precedes its start, or that runs for months, has a wrong year
    in one of its dates. Candidates move one date's year to match the other; among
    those with a 0-45 day field period we keep the one closest in time to the
    neighbouring rows of the table (the tables are in date order)."""
    cands = [(st.replace(year=en.year), en), (st, en.replace(year=st.year)),
             (st, en.replace(year=st.year + 1)), (st.replace(year=en.year - 1), en)]
    ok = [(a, b) for a, b in cands if 0 <= (b - a).days <= MAX_FIELD_DAYS]
    if not ok:
        raise ValueError(f"{page}: cannot repair poll dates {st.date()} to {en.date()}")
    ref = pd.Series(neighbours).mean()
    a, b = min(ok, key=lambda c: abs((c[0] - ref).days))
    fix("Gallup/UCSB", f"{page}: wrong year in poll dates {st.date()} to {en.date()}", 1,
        f"set to {a.date()} to {b.date()}")
    return a, b


def col(t: pd.DataFrame, *keys: str, exclude: str | None = None) -> str | None:
    for c in t.columns:
        lc = str(c).lower()
        if all(k in lc for k in keys) and (exclude is None or exclude not in lc):
            return c
    return None


def read_block(t: pd.DataFrame, page: str, start_c: str, end_c: str, value_cols: dict) -> pd.DataFrame:
    out = t[[start_c, end_c] + [c for c in value_cols.values() if c is not None]].copy()
    out = out.dropna(subset=[start_c, end_c])
    rows = []
    for _, r in out.iterrows():
        st = parse_date(r[start_c], None, page)
        en = parse_date(r[end_c], st, page)
        rec = {"start": st, "end": en}
        for k, c in value_cols.items():
            rec[k] = pd.to_numeric(r[c], errors="coerce") if c is not None else np.nan
        rows.append(rec)
    valid = [0 <= (x["end"] - x["start"]).days <= MAX_FIELD_DAYS for x in rows]
    for i, x in enumerate(rows):
        if not valid[i]:
            nb = [rows[j]["start"] for j in (i - 1, i + 1) if 0 <= j < len(rows) and valid[j]]
            x["start"], x["end"] = repair_year(x["start"], x["end"], page, nb)
    return pd.DataFrame(rows)


def parse_page(p: President) -> pd.DataFrame:
    html = (RAW / "ucsb_approval" / f"{p.slug}.html").read_text()
    t = pd.read_html(io.StringIO(html))[0]
    page = p.slug
    n_raw = len(t)

    # Rows the UCSB editors interpolated themselves are not real polls.
    note_cols = [c for c in t.columns if str(c).startswith("Unnamed")]
    interp = t[note_cols].astype(str).apply(lambda s: s.str.contains("interpolated", case=False)).any(axis=1)
    if interp.any():
        fix("Gallup/UCSB", f"{page}: row marked 'interpolated' by UCSB", interp.sum(),
            "dropped; months without a poll are filled by our own rule (step 3)")
        t = t[~interp]

    # Trump 2nd term: after Gallup stopped, UCSB adds other pollsters. Keep Gallup only.
    src = col(t, "source")
    if src is not None:
        non = ~t[src].astype(str).str.lower().str.contains("gallup")
        fix("Gallup/UCSB", f"{page}: non-Gallup polls (AP-NORC, CNN, Ipsos, ...)", non.sum(),
            "dropped to keep one consistent pollster")
        t = t[~non]

    start_c = [c for c in t.columns if "start" in str(c).lower()]
    end_c = [c for c in t.columns if "end" in str(c).lower()]
    overall = {"approve": "Approving" if "Approving" in t.columns else None,
               "disapprove": "Disapproving" if "Disapproving" in t.columns else None,
               "unsure": col(t, "unsure")}
    partisan = {"dem": col(t, "democrat"), "ind": col(t, "independent"), "rep": col(t, "republican")}

    if len(start_c) == 2:
        # Trump 1st term: the partisan columns carry their own poll dates.
        a = read_block(t, page, start_c[0], end_c[0], overall)
        b = read_block(t, page, start_c[1], end_c[1], partisan)
        df = a.merge(b, on=["start", "end"], how="outer")
        fix("Gallup/UCSB", f"{page}: partisan breakdown listed with its own dates", len(b),
            "merged with overall approval on (start, end); unmatched partisan polls kept as their own rows")
    else:
        df = read_block(t, page, start_c[0], end_c[0], {**overall, **partisan})

    df.insert(0, "admin", p.admin)
    df["raw_rows"] = n_raw
    return df


def build_polls() -> pd.DataFrame:
    polls = pd.concat([parse_page(p) for p in PRESIDENTS], ignore_index=True)
    polls["days"] = (polls["end"] - polls["start"]).dt.days + 1
    polls["mid"] = polls["start"] + (polls["end"] - polls["start"]) / 2
    polls["mid"] = polls["mid"].dt.normalize()
    polls["month"] = polls["mid"].dt.to_period("M")
    polls["party"] = polls["admin"].map(lambda a: PRES[a].party)

    # Duplicates
    dup = polls.duplicated(["admin", "start", "end"], keep="first")
    if dup.any():
        fix("Gallup/UCSB", "exact duplicate polls (same president and dates)", dup.sum(), "dropped")
    polls = polls[~dup].copy()

    # Polls dated outside the president's tenure
    outside = polls.apply(lambda r: not (pd.Timestamp(PRES[r.admin].start) <= r.mid
                                         < pd.Timestamp(PRES[r.admin].end)), axis=1)
    if outside.any():
        fix("Gallup/UCSB", "poll midpoint outside the president's tenure", outside.sum(), "dropped")
    polls = polls[~outside].copy()

    # Partisan rows where the president's own party approves LESS than the other party:
    # every such case in this data is a column swap at data entry, so we blank them.
    inp = np.where(polls["party"] == "D", polls["dem"], polls["rep"])
    outp = np.where(polls["party"] == "D", polls["rep"], polls["dem"])
    swapped = pd.Series(inp < outp, index=polls.index)
    if swapped.any():
        detail = "; ".join(f"{r.admin} {r.start.date()} (D={r.dem:.0f}, R={r.rep:.0f})"
                           for r in polls[swapped].itertuples())
        fix("Gallup/UCSB", f"in-party approval below out-party approval ({detail})", swapped.sum(),
            "partisan values set to missing (likely swapped columns); overall approval kept")
        polls.loc[swapped, ["dem", "ind", "rep"]] = np.nan

    polls["in_party"] = np.where(polls["party"] == "D", polls["dem"], polls["rep"])
    polls["out_party"] = np.where(polls["party"] == "D", polls["rep"], polls["dem"])
    polls = polls.sort_values(["start", "end"]).reset_index(drop=True)
    return polls


# ---------------------------------------------------------------------------
# 3. Monthly approval
# ---------------------------------------------------------------------------

def fill_within_admin(s: pd.Series, admin: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Linear interpolation inside each administration; edge months take the nearest
    month of the same administration. Never borrows across presidents."""
    out = s.copy()
    method = pd.Series(np.where(s.notna(), "observed", ""), index=s.index, dtype=object)
    for a, idx in s.groupby(admin, sort=False).groups.items():
        part = s.loc[idx]
        if part.notna().sum() == 0:
            continue
        interior = part.interpolate(method="linear", limit_area="inside")
        edges = interior.ffill().bfill()
        out.loc[idx] = edges
        method.loc[idx] = np.where(part.notna(), "observed",
                                   np.where(interior.notna(), "interpolated", "nearest"))
    method[out.isna()] = "missing"
    return out, method


def build_monthly_approval(polls: pd.DataFrame) -> pd.DataFrame:
    # Built from BUILD_START so lead-in months can borrow the president's earlier polls;
    # assemble() trims the result to LEAD_START.
    months = pd.period_range(BUILD_START, SAMPLE_END, freq="M")
    m = pd.DataFrame({"month": months})
    m["admin"] = [president_on(p.to_timestamp() + pd.Timedelta(days=14)).admin for p in months]

    # A month belongs to the president in office on its 15th; use only that president's polls.
    own = polls.merge(m, on=["month", "admin"], how="inner")
    dropped = len(polls[polls["month"].between(BUILD_START, SAMPLE_END)]) - len(own)
    fix("Gallup/UCSB", "polls in an inauguration month taken for the incoming president", dropped,
        "not used in that month (the month belongs to the outgoing president, in office on the 15th)")

    agg = own.groupby("month").agg(
        n_polls=("approve", "count"), A=("approve", "mean"), disapprove=("disapprove", "mean"),
        n_partisan=("in_party", "count"), dem_app=("dem", "mean"), ind_app=("ind", "mean"),
        rep_app=("rep", "mean"), in_party_app=("in_party", "mean"), out_party_app=("out_party", "mean"),
    ).reset_index()
    m = m.merge(agg, on="month", how="left")
    m[["n_polls", "n_partisan"]] = m[["n_polls", "n_partisan"]].fillna(0).astype(int)

    m["A"], m["A_fill"] = fill_within_admin(m["A"], m["admin"])
    for c in ["in_party_app", "out_party_app", "dem_app", "ind_app", "rep_app"]:
        m[c], meth = fill_within_admin(m[c], m["admin"])
        if c == "in_party_app":
            m["G_fill"] = meth
    m["G"] = m["in_party_app"] - m["out_party_app"]
    return m


# ---------------------------------------------------------------------------
# 4. FRED
# ---------------------------------------------------------------------------

def read_fred(sid: str) -> pd.Series:
    df = pd.read_csv(RAW / "fred" / f"{sid}.csv")
    df["month"] = pd.to_datetime(df["observation_date"]).dt.to_period("M")
    return pd.to_numeric(df[sid], errors="coerce").set_axis(df["month"])


def build_fred() -> pd.DataFrame:
    s = {sid: read_fred(sid) for sid in ["UMCSENT", "CPIAUCSL", "UNRATE", "AHETPI", "USREC"]}
    idx = pd.period_range("1976-01", SAMPLE_END, freq="M")
    f = pd.DataFrame({k: v.reindex(idx) for k, v in s.items()})
    f.index.name = "month"

    # Interior gaps (the Oct-2025 federal shutdown: BLS published no CPI or unemployment rate)
    for sid, how in [("CPIAUCSL", "log"), ("UNRATE", "linear"), ("AHETPI", "log"), ("USREC", "none")]:
        gap = f[sid].isna()
        gap &= f[sid].ffill().notna() & f[sid].bfill().notna()
        f[f"{sid}_filled"] = gap.astype(int)
        if gap.any() and how != "none":
            if how == "log":
                f[sid] = np.exp(np.log(f[sid]).interpolate(limit_area="inside"))
            else:
                f[sid] = f[sid].interpolate(limit_area="inside")
            months = ", ".join(str(p) for p in f.index[gap])
            fix("FRED", f"{sid} missing for {months} (2025 federal government shutdown)", gap.sum(),
                f"{'geometric' if how == 'log' else 'arithmetic'} mean of the neighbouring months; flagged in {sid}_filled")
    # UMCSENT is quarterly before 1978: leave the gaps (lead-in year only).
    q = f.loc[:"1977-12", "UMCSENT"].isna().sum()
    fix("FRED", "UMCSENT is quarterly before 1978 (Feb, May, Aug, Nov)", q,
        "left missing; only affects the 1977 lead-in year, not the 1978m1-2025m12 sample")

    out = pd.DataFrame(index=f.index)
    out["S"] = f["UMCSENT"]
    out["U"] = f["UNRATE"]
    out["CPI"] = f["CPIAUCSL"]
    out["pi"] = 100 * np.log(f["CPIAUCSL"] / f["CPIAUCSL"].shift(12))
    out["AHE"] = f["AHETPI"]
    out["real_wage"] = f["AHETPI"] / f["CPIAUCSL"]
    out["W"] = 100 * np.log(out["real_wage"] / out["real_wage"].shift(12))
    out["rec"] = f["USREC"].astype("Int64")
    out["CPI_filled"] = f["CPIAUCSL_filled"]
    out["U_filled"] = f["UNRATE_filled"]
    return out.reset_index()


# ---------------------------------------------------------------------------
# 5. Voteview polarisation
# ---------------------------------------------------------------------------

def build_polarisation() -> pd.DataFrame:
    v = pd.read_csv(RAW / "voteview" / "HSall_parties.csv")
    raw_codes = v["party_code"].astype(str)
    n_float = raw_codes.str.endswith(".0").sum()
    v["party_code"] = pd.to_numeric(v["party_code"]).astype(int)
    if n_float:
        fix("Voteview", "party_code stored as '100.0'/'200.0' from the 115th Congress on", n_float,
            "converted to integers before filtering")
    v = v[v["chamber"].isin(["House", "Senate"]) & v["party_code"].isin([100, 200])]
    w = v.pivot_table(index="congress", columns=["chamber", "party_code"], values="nominate_dim1_mean")
    p = pd.DataFrame({
        "P_house": w[("House", 200)] - w[("House", 100)],
        "P_senate": w[("Senate", 200)] - w[("Senate", 100)],
    })
    p["P"] = p[["P_house", "P_senate"]].mean(axis=1)
    return p.reset_index()


def congress_of(month: pd.Period) -> int:
    # Congress n opens on 3 January of year 1789 + 2(n-1); the 15th decides the month.
    return (month.year - 1789) // 2 + 1


# ---------------------------------------------------------------------------
# 6. Assemble
# ---------------------------------------------------------------------------

def assemble(approval: pd.DataFrame, fred: pd.DataFrame, pol: pd.DataFrame) -> pd.DataFrame:
    d = approval.merge(fred, on="month", how="left")
    d["congress"] = d["month"].map(congress_of)
    d = d.merge(pol, on="congress", how="left")

    d.insert(0, "date", d["month"].dt.to_timestamp().dt.strftime("%Y-%m-%d"))
    d.insert(1, "year", d["month"].dt.year)
    d.insert(2, "mon", d["month"].dt.month)
    d["in_sample"] = d["month"].between(SAMPLE_START, SAMPLE_END).astype(int)
    d["t"] = np.where(d["in_sample"] == 1, (d["month"] - SAMPLE_START).map(lambda x: x.n) + 1, np.nan)
    T = int(d["in_sample"].sum())
    d["s"] = d["t"] / T

    # Approval transforms
    d["a"] = np.log(d["A"] / (100 - d["A"]))
    d["G_lag12"] = d["G"].shift(12)
    d = d[d["month"] >= LEAD_START].reset_index(drop=True)

    # President variables
    d["pres_name"] = d["admin"].map(lambda a: PRES[a].name)
    d["pres_party"] = d["admin"].map(lambda a: PRES[a].party)
    d["pres_dem"] = (d["pres_party"] == "D").astype(int)

    def first_month(p: President) -> pd.Period:
        # first month whose 15th falls inside the tenure
        st = pd.Timestamp(p.start)
        return st.to_period("M") if st.day <= 15 else st.to_period("M") + 1
    d["admin_month"] = [(m - first_month(PRES[a])).n + 1 for a, m in zip(d["admin"], d["month"])]
    d["second_term"] = [int(PRES[a].second_term_start is not None and
                            m.to_timestamp() + pd.Timedelta(days=14) >= pd.Timestamp(PRES[a].second_term_start))
                        for a, m in zip(d["admin"], d["month"])]
    d["honeymoon"] = (d["admin_month"] <= 6).astype(int)
    d["inaug_month"] = ((d["mon"] == 1) & d["year"].isin([1977, 1981, 1989, 1993, 2001, 2009, 2017, 2021, 2025])).astype(int)

    # Event dummies (as defined in the proposal)
    def window(a, b):
        return d["month"].between(pd.Period(a, "M"), pd.Period(b, "M")).astype(int)
    d["rally_gulf"] = window("1991-01", "1991-03")
    d["rally_911"] = window("2001-09", "2002-03")
    d["rally_iraq"] = window("2003-03", "2003-04")
    d["covid"] = window("2020-03", "2020-05")

    # Polarisation eras: terciles of P over the estimation sample
    ps = np.sort(d.loc[d["in_sample"] == 1, "P"].to_numpy())
    c1, c2 = ps[T // 3], ps[2 * T // 3]
    d["era"] = np.where(d["P"] < c1, 1, np.where(d["P"] < c2, 2, 3))
    for e in (1, 2, 3):
        d[f"E{e}"] = (d["era"] == e).astype(int)
    d.attrs["era_cuts"] = (float(c1), float(c2))

    d["month"] = d["month"].astype(str)
    order = ["date", "year", "mon", "month", "in_sample", "t", "s",
             "A", "a", "A_fill", "n_polls", "disapprove",
             "S", "U", "pi", "W", "CPI", "AHE", "real_wage", "rec", "CPI_filled", "U_filled",
             "P", "P_house", "P_senate", "congress", "era", "E1", "E2", "E3",
             "G", "G_lag12", "G_fill", "in_party_app", "out_party_app", "dem_app", "ind_app", "rep_app", "n_partisan",
             "admin", "pres_name", "pres_party", "pres_dem", "admin_month", "second_term",
             "honeymoon", "inaug_month", "rally_gulf", "rally_911", "rally_iraq", "covid"]
    return d[order]


# ---------------------------------------------------------------------------
# 7. Quality checks
# ---------------------------------------------------------------------------

def run_checks(polls: pd.DataFrame, d: pd.DataFrame, pol: pd.DataFrame) -> dict:
    s = d[d["in_sample"] == 1]
    T = len(s)
    stats = {}

    # Poll level
    per = polls.groupby("admin").size().reindex([p.admin for p in PRESIDENTS])
    check("P1", "every president page parsed with polls", bool((per > 0).all()),
          ", ".join(f"{a}={n}" for a, n in per.items()))
    check("P2", f"all poll dates valid, end >= start, field period <= {MAX_FIELD_DAYS} days",
          bool((polls["end"] >= polls["start"]).all() and polls["days"].max() <= MAX_FIELD_DAYS),
          f"max field period {polls['days'].max()} days; median {polls['days'].median():.0f}")
    vals = polls[["approve", "disapprove", "unsure", "dem", "ind", "rep"]]
    check("P3", "all percentages within [0, 100]", bool(((vals >= 0) & (vals <= 100) | vals.isna()).all().all()))
    tot = polls[["approve", "disapprove", "unsure"]].sum(axis=1, min_count=3)
    bad_tot = ((tot < 97) | (tot > 103)) & tot.notna()
    check("P4", "approve + disapprove + unsure within 97-103 (rounding)", not bad_tot.any(),
          f"{int(bad_tot.sum())} polls outside" + (": " + ", ".join(
              f"{r.admin} {r.start.date()} sum={t:.0f}" for r, t in zip(polls[bad_tot].itertuples(), tot[bad_tot])) if bad_tot.any() else ""))
    ok = polls.dropna(subset=["in_party", "out_party"])
    check("P5", "in-party approval > out-party approval in every partisan poll",
          bool((ok["in_party"] > ok["out_party"]).all()), f"{len(ok)} partisan polls")
    lo = polls[["dem", "ind", "rep"]].min(axis=1) - 2
    hi = polls[["dem", "ind", "rep"]].max(axis=1) + 2
    both = polls["approve"].notna() & polls[["dem", "rep"]].notna().all(axis=1)
    inside = polls["approve"].between(lo, hi)
    check("P6", "overall approval lies between the lowest and highest party value (2 pt tolerance)",
          bool(inside[both].all()), f"{int((~inside[both]).sum())} of {int(both.sum())} polls outside")
    check("P7", "no duplicate polls and no poll outside its president's tenure", True, "enforced in build_polls()")

    # Panel structure
    ords = pd.PeriodIndex(s["month"], freq="M").asi8
    check("M1", "estimation sample is 1978m1-2025m12, contiguous, one row per month",
          bool(T == 576 and len(set(ords)) == T and (np.diff(ords) == 1).all()
               and s["month"].iloc[0] == "1978-01" and s["month"].iloc[-1] == "2025-12"),
          f"T = {T}")
    core = ["A", "a", "S", "U", "pi", "W", "P", "G", "G_lag12", "rec", "honeymoon", "era"]
    na = s[core].isna().sum()
    check("M2", "no missing values in model variables over the sample", bool(na.sum() == 0),
          ", ".join(f"{c}={n}" for c, n in na.items() if n) or "none missing")
    check("M3", "logit approval finite (0 < A < 100)", bool(np.isfinite(s["a"]).all()))

    fills = s["A_fill"].value_counts().to_dict()
    filled = s[s["A_fill"] != "observed"]
    check("M4", "share of months with no Gallup poll (filled) below 10%",
          len(filled) / T < 0.10,
          f"{len(filled)} of {T} months filled: {fills}; months: {', '.join(filled['month'])}")
    run = (s["A_fill"] != "observed").astype(int)
    longest = int(run.groupby((run == 0).cumsum()).sum().max())
    check("M5", "no run of filled approval months longer than 3", longest <= 3, f"longest run {longest}")
    gfill = s["G_fill"].value_counts().to_dict()
    check("M6", "mass polarisation G observed in at least 85% of months",
          (s["G_fill"] == "observed").mean() >= 0.85, f"{gfill}")
    check("M7", "G > 0 in every month (presidents' own party always approves more)", bool((s["G"] > 0).all()),
          f"min G = {s['G'].min():.1f}")

    # Polarisation
    cong = pol.set_index("congress").loc[95:119]
    check("V1", "Voteview: both parties in both chambers for Congresses 95-119",
          bool(cong[["P_house", "P_senate"]].notna().all().all()))
    check("V2", "elite polarisation rises over the sample (P in 119th > P in 95th)",
          bool(cong.loc[119, "P"] > cong.loc[95, "P"]), f"P: {cong.loc[95,'P']:.3f} -> {cong.loc[119,'P']:.3f}")
    eras = s.groupby("era")["month"].agg(["first", "last", "count"])
    contiguous = all((np.diff(pd.PeriodIndex(s.loc[s["era"] == e, "month"], freq="M").asi8) == 1).all()
                     for e in (1, 2, 3))
    check("V3", "the three polarisation eras are contiguous blocks", contiguous,
          "; ".join(f"Era {e}: {r['first']} to {r['last']} ({r['count']} months)" for e, r in eras.iterrows()))
    stats["eras"] = {int(e): {"first": r["first"], "last": r["last"], "months": int(r["count"]),
                              "mean_P": round(float(s.loc[s["era"] == e, "P"].mean()), 3)}
                     for e, r in eras.iterrows()}

    # Benchmarks against well-known historical values
    def mx(col, a, b):
        return float(s.loc[s["month"].between(a, b), col].max())

    def mn(col, a, b):
        return float(s.loc[s["month"].between(a, b), col].min())
    bench = [
        ("B1", "post-9/11 rally: approval peaks >= 85 in 2001m9-2001m11", mx("A", "2001-09", "2001-11") >= 85, mx("A", "2001-09", "2001-11")),
        ("B2", "Gulf War rally: approval >= 80 in 1991m2-1991m3", mx("A", "1991-02", "1991-03") >= 80, mx("A", "1991-02", "1991-03")),
        ("B3", "Carter low: approval <= 35 in 1979-1980", mn("A", "1979-01", "1980-12") <= 35, mn("A", "1979-01", "1980-12")),
        ("B4", "G.W. Bush low: approval <= 30 in 2008", mn("A", "2008-01", "2008-12") <= 30, mn("A", "2008-01", "2008-12")),
        ("B5", "unemployment peak 10.8% in 1982", abs(mx("U", "1982-01", "1982-12") - 10.8) < 1e-9, mx("U", "1982-01", "1982-12")),
        ("B6", "unemployment COVID peak 14.8% in 2020m4", abs(mx("U", "2020-04", "2020-04") - 14.8) < 1e-9, mx("U", "2020-04", "2020-04")),
        ("B7", "inflation peak 13-15% (log, y/y) in 1980", 13 <= mx("pi", "1980-01", "1980-12") <= 15, mx("pi", "1980-01", "1980-12")),
        ("B8", "inflation 2022 peak 8-9.5% (log, y/y)", 8 <= mx("pi", "2022-01", "2022-12") <= 9.5, mx("pi", "2022-01", "2022-12")),
        ("B9", "sentiment record low 50.0 in 2022m6", abs(mn("S", "2022-06", "2022-06") - 50.0) < 1e-9, mn("S", "2022-06", "2022-06")),
        ("B10", "recession dummy = 1 in 2008m12 and 2020m4, 0 in 2019m6",
         bool(s.set_index("month").loc[["2008-12", "2020-04"], "rec"].eq(1).all() and s.set_index("month").loc["2019-06", "rec"] == 0), None),
    ]
    for cid, desc, ok_, val in bench:
        check(cid, desc, bool(ok_), "" if val is None else f"value {val:.2f}")

    # Largest monthly changes in approval: should line up with known events
    ch = s[["month", "A", "admin"]].copy()
    ch["dA"] = ch["A"].diff()
    ch = ch[ch["admin"] == ch["admin"].shift()]  # ignore changes of president
    top = ch.reindex(ch["dA"].abs().sort_values(ascending=False).index).head(8)
    stats["largest_changes"] = [{"month": r.month, "dA": round(float(r.dA), 1), "admin": r.admin}
                                for r in top.itertuples()]
    stats["descriptives"] = s[["A", "S", "U", "pi", "W", "P", "G"]].describe().round(3).to_dict()
    return stats


# ---------------------------------------------------------------------------
# 8. Outputs
# ---------------------------------------------------------------------------

DICTIONARY = [
    ("date", "first day of the month (YYYY-MM-DD)", "", "constructed"),
    ("year", "calendar year", "", "constructed"),
    ("mon", "calendar month 1-12", "", "constructed"),
    ("month", "month as YYYY-MM", "", "constructed"),
    ("in_sample", "1 for 1978m1-2025m12 (T = 576); 0 for the 1977 lead-in year kept for lags", "0/1", "constructed"),
    ("t", "time index 1..576 within the sample", "", "constructed"),
    ("s", "linear trend t/T used in trend interactions", "", "constructed"),
    ("A", "Gallup presidential job approval, mean of polls whose midpoint falls in the month", "%", "Gallup via UCSB"),
    ("a", "logit of approval, ln(A/(100-A))", "", "constructed"),
    ("A_fill", "observed / interpolated / nearest: how A was obtained (see README step 3)", "", "constructed"),
    ("n_polls", "number of Gallup polls behind A (0 = filled)", "count", "Gallup via UCSB"),
    ("disapprove", "Gallup disapproval, monthly mean (not filled)", "%", "Gallup via UCSB"),
    ("S", "University of Michigan consumer sentiment", "index, 1966Q1=100", "FRED UMCSENT"),
    ("U", "civilian unemployment rate, seasonally adjusted", "%", "FRED UNRATE"),
    ("pi", "inflation, 100*ln(CPI_t/CPI_{t-12})", "%", "FRED CPIAUCSL"),
    ("W", "real wage growth, 100*ln(real_wage_t/real_wage_{t-12})", "%", "FRED AHETPI, CPIAUCSL"),
    ("CPI", "CPI-U all items, seasonally adjusted", "1982-84=100", "FRED CPIAUCSL"),
    ("AHE", "average hourly earnings, production and nonsupervisory employees, SA", "$", "FRED AHETPI"),
    ("real_wage", "AHE / CPI", "", "constructed"),
    ("rec", "NBER recession indicator", "0/1", "FRED USREC"),
    ("CPI_filled", "1 if CPI was missing at source and filled (2025m10)", "0/1", "constructed"),
    ("U_filled", "1 if U was missing at source and filled (2025m10)", "0/1", "constructed"),
    ("P", "elite polarisation: mean of House and Senate gaps between Republican and Democratic DW-NOMINATE dim-1 means", "NOMINATE units", "Voteview"),
    ("P_house", "House gap, Republican minus Democratic dim-1 mean", "NOMINATE units", "Voteview"),
    ("P_senate", "Senate gap, Republican minus Democratic dim-1 mean", "NOMINATE units", "Voteview"),
    ("congress", "Congress in session on the 15th of the month", "", "constructed"),
    ("era", "polarisation era 1/2/3 (terciles of P over the sample)", "", "constructed"),
    ("E1", "1 in Era 1", "0/1", "constructed"),
    ("E2", "1 in Era 2", "0/1", "constructed"),
    ("E3", "1 in Era 3", "0/1", "constructed"),
    ("G", "mass polarisation: in-party minus out-party approval", "pct points", "Gallup via UCSB"),
    ("G_lag12", "G lagged 12 months, as used in the model", "pct points", "constructed"),
    ("G_fill", "observed / interpolated / nearest: how the partisan values were obtained", "", "constructed"),
    ("in_party_app", "approval among identifiers of the president's party", "%", "Gallup via UCSB"),
    ("out_party_app", "approval among identifiers of the other party", "%", "Gallup via UCSB"),
    ("dem_app", "approval among Democrats", "%", "Gallup via UCSB"),
    ("ind_app", "approval among Independents", "%", "Gallup via UCSB"),
    ("rep_app", "approval among Republicans", "%", "Gallup via UCSB"),
    ("n_partisan", "number of Gallup polls with a party breakdown in the month", "count", "Gallup via UCSB"),
    ("admin", "administration id (ford, carter, ..., trump1, biden, trump2); use for fixed effects", "", "constructed"),
    ("pres_name", "president in office on the 15th of the month", "", "constructed"),
    ("pres_party", "D or R", "", "constructed"),
    ("pres_dem", "1 if the president is a Democrat", "0/1", "constructed"),
    ("admin_month", "months the administration has held (1 = first month assigned to it)", "count", "constructed"),
    ("second_term", "1 in a re-elected president's second term", "0/1", "constructed"),
    ("honeymoon", "1 in the first six months of a new administration", "0/1", "constructed"),
    ("inaug_month", "1 in January of an inauguration year (month assigned to the outgoing president)", "0/1", "constructed"),
    ("rally_gulf", "Gulf War, 1991m1-1991m3", "0/1", "constructed"),
    ("rally_911", "September 11, 2001m9-2002m3", "0/1", "constructed"),
    ("rally_iraq", "Iraq invasion, 2003m3-2003m4", "0/1", "constructed"),
    ("covid", "COVID onset, 2020m3-2020m5", "0/1", "constructed"),
]


def make_figure(d: pd.DataFrame) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    s = d[d["in_sample"] == 1].copy()
    x = pd.to_datetime(s["date"])
    fig, ax = plt.subplots(4, 2, figsize=(12, 11), sharex=True)
    series = [("A", "Approval A (%)"), ("G", "Partisan gap G (pts)"), ("S", "Consumer sentiment S"),
              ("U", "Unemployment U (%)"), ("pi", "Inflation pi (%)"), ("W", "Real wage growth W (%)"),
              ("P", "Elite polarisation P"), ("a", "Logit approval a")]
    for axi, (c, label) in zip(ax.flat, series):
        axi.plot(x, s[c], lw=1, color="#2a5d8f")
        if c == "A":
            f = s["A_fill"] != "observed"
            axi.scatter(x[f], s.loc[f, "A"], s=10, color="#c0392b", zorder=3, label="filled month")
            axi.legend(loc="lower left", fontsize=8, frameon=False)
        for b in ("1993-01-01", "2009-01-01"):
            axi.axvline(pd.Timestamp(b), color="grey", lw=0.8, ls="--")
        axi.set_title(label, fontsize=10)
        axi.grid(alpha=0.3)
    fig.suptitle("Project 2 monthly series, 1978m1-2025m12 (dashed lines: era boundaries)", fontsize=12)
    fig.tight_layout()
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / "overview.png", dpi=130)
    plt.close(fig)


def write_report(d: pd.DataFrame, polls: pd.DataFrame, stats: dict) -> None:
    n_pass = sum(c["passed"] for c in CHECKS)
    lines = [
        "# Project 2 data: quality-check report",
        "",
        "Generated by `code/build_dataset.py`. Do not edit by hand; re-run the script instead.",
        "",
        f"**Result: {n_pass} of {len(CHECKS)} checks passed.**",
        "",
        "## 1. Quality checks",
        "",
        "| ID | Check | Result | Detail |",
        "|---|---|---|---|",
    ]
    for c in CHECKS:
        det = c["detail"].replace("|", "/")
        lines.append(f"| {c['id']} | {c['check']} | {'PASS' if c['passed'] else '**FAIL**'} | {det} |")
    lines += ["", "## 2. Every change made to source values", "",
              "| Dataset | Issue | Rows | Action |", "|---|---|---|---|"]
    for f in FIXES:
        lines.append(f"| {f['dataset']} | {f['issue']} | {f['rows']} | {f['action']} |")
    lines += ["", "## 3. Polarisation eras", "", "| Era | First month | Last month | Months | Mean P |", "|---|---|---|---|---|"]
    for e, r in stats["eras"].items():
        lines.append(f"| {e} | {r['first']} | {r['last']} | {r['months']} | {r['mean_P']} |")
    lines += ["", "## 4. Largest month-on-month changes in approval (same president)", "",
              "These should match known events (rallies, scandals, shocks).", "",
              "| Month | Change (pts) | President |", "|---|---|---|"]
    for r in stats["largest_changes"]:
        lines.append(f"| {r['month']} | {r['dA']:+.1f} | {r['admin']} |")
    desc = pd.DataFrame(stats["descriptives"]).T
    lines += ["", "## 5. Descriptive statistics, 1978m1-2025m12", "",
              "| Variable | N | Mean | SD | Min | Max |", "|---|---|---|---|---|---|"]
    for v, r in desc.iterrows():
        lines.append(f"| {v} | {int(r['count'])} | {r['mean']:.2f} | {r['std']:.2f} | {r['min']:.2f} | {r['max']:.2f} |")
    lines += ["", "## 6. Poll counts", "", "| Administration | Polls used | With party breakdown |", "|---|---|---|"]
    for a, g in polls.groupby("admin", sort=False):
        lines.append(f"| {a} | {g['approve'].notna().sum()} | {g['in_party'].notna().sum()} |")
    lines.append("")
    (PROJECT_DIR / "data" / "QC_REPORT.md").write_text("\n".join(lines))
    (PROJECT_DIR / "data" / "qc_checks.json").write_text(json.dumps(
        {"checks": CHECKS, "fixes": FIXES, "eras": stats["eras"], "largest_changes": stats["largest_changes"]},
        indent=2, default=str))


def main() -> None:
    CLEAN.mkdir(parents=True, exist_ok=True)
    polls = build_polls()
    approval = build_monthly_approval(polls)
    fred = build_fred()
    pol = build_polarisation()
    d = assemble(approval, fred, pol)
    stats = run_checks(polls, d, pol)

    out_polls = polls.drop(columns=["raw_rows"]).copy()
    for c in ["start", "end", "mid"]:
        out_polls[c] = out_polls[c].dt.strftime("%Y-%m-%d")
    out_polls["month"] = out_polls["month"].astype(str)
    out_polls.to_csv(CLEAN / "approval_polls.csv", index=False)

    d.to_csv(CLEAN / "analysis_monthly.csv", index=False, float_format="%.6g")
    st = d.copy()
    st["tm"] = pd.to_datetime(st["date"])
    st["rec"] = st["rec"].astype(float)
    st = st.drop(columns=["date"])
    st.to_stata(CLEAN / "analysis_monthly.dta", write_index=False, version=118,
                convert_dates={"tm": "tm"},
                variable_labels={k: v[:80] for k, v, *_ in DICTIONARY if k in st.columns})
    pd.DataFrame(DICTIONARY, columns=["variable", "description", "unit", "source"]).to_csv(
        CLEAN / "data_dictionary.csv", index=False)
    make_figure(d)
    write_report(d, polls, stats)
    n_fail = sum(not c["passed"] for c in CHECKS)
    print(f"\nwrote data/clean/ ({len(d)} rows, {d['in_sample'].sum()} in sample); {n_fail} failed checks")


if __name__ == "__main__":
    main()
