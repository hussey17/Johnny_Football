#!/usr/bin/env python3
"""Build data/manual/governors_template.csv from the raw governor sources.

Inputs (all fetched by fetch_data.py; nothing is downloaded here):
  raw/governors/wikidata/governor_tenures.csv      who held office, exact dates
  raw/governors/wikipedia/<year>_gubernatorial_elections.json
                                                   incumbent status at each election
  raw/dataverse/klarner_governors/...xlsx          independent check, 1989-2011
  manual/governors_overrides.csv                   hand-researched fixes, with sources

Row unit: one governor x one term of office. A term ends at the next regular
(or vacancy-filling special) gubernatorial election; a governor re-elected at
that election starts a new row on the new term's inauguration day.

Usage: python build_governors.py
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import unicodedata
import warnings
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

CODE_DIR = Path(__file__).resolve().parent
DATA_DIR = CODE_DIR.parent / "data"
RAW = DATA_DIR / "raw"
MANUAL = DATA_DIR / "manual"
GOV_RAW = RAW / "governors"

sys.path.insert(0, str(CODE_DIR))
from fetch_data import STATES  # noqa: E402

STATE_NAMES = set(STATES.values())
WINDOW_START = date(1989, 1, 1)
SNAPSHOT = date(2026, 10, 5)  # day the sources were downloaded


# --------------------------------------------------------------------------
# Name helpers
# --------------------------------------------------------------------------

SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def strip_notes(text) -> str:
    """Drop footnote markers like [a] or [12] and annotations in parentheses."""
    text = "" if pd.isna(text) else str(text)
    text = re.sub(r"\[[^\]]*\]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def surname(name: str) -> str:
    name = re.sub(r"['\u02bb\u2019]", "", strip_notes(name))  # Waihe'e / Waiheʻe -> Waihee
    name = re.sub(r"-[DRI]\b.*$", "", name)  # Klarner "O'Bannon-D", "Davis-D then ..."
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = re.sub(r"\([^)]*\)", "", name)
    if "," in name:  # "Perry, Rick" (Klarner)
        name = name.split(",")[0]
    tokens = [t for t in re.split(r"[\s.]+", name.lower()) if t and t not in SUFFIXES]
    return tokens[-1] if tokens else ""


# --------------------------------------------------------------------------
# Elections (Wikipedia)
# --------------------------------------------------------------------------

def nov_election_day(year: int) -> date:
    """Tuesday after the first Monday in November."""
    d = date(year, 11, 2)
    while d.weekday() != 1:
        d += timedelta(days=1)
    return d


def _pick(cols: list[str], *names: str) -> str | None:
    for c in cols:
        base = strip_notes(c)
        if base in names:
            return c
    return None


def parse_election_year(year: int) -> list[dict]:
    path = GOV_RAW / "wikipedia" / f"{year}_gubernatorial_elections.json"
    page = json.loads(path.read_text(encoding="utf-8"))
    if "parse" not in page:
        return []
    html = page["parse"]["text"]
    tables = pd.read_html(io.StringIO(html))
    found: dict[str, dict] = {}
    for t in tables:
        if isinstance(t.columns, pd.MultiIndex):
            t.columns = [c[-1] for c in t.columns]
        cols = [str(c) for c in t.columns]
        t.columns = cols
        c_state = _pick(cols, "State", "States")
        c_inc = _pick(cols, "Incumbent", "Governor")
        c_party = _pick(cols, "Party")
        c_first = _pick(cols, "First elected")
        c_status = _pick(cols, "Result", "Status")
        if not (c_state and c_inc and c_status):
            continue
        is_summary = bool(c_party and c_first)  # the race-summary table, not ratings
        for _, r in t.iterrows():
            raw_state = strip_notes(r[c_state])
            state = re.sub(r"\s*\((special|recall)\)$", "", raw_state, flags=re.I).strip()
            if state not in STATE_NAMES:
                continue
            kind = "recall" if "recall" in raw_state.lower() else (
                "special" if "special" in raw_state.lower() else "regular")
            inc_raw = strip_notes(r[c_inc])
            rec = found.setdefault((state, kind), {
                "year": year, "state": state, "kind": kind, "incumbent": "", "party": "",
                "first_elected": "", "status": "", "ratings_note": ""})
            if is_summary:
                rec.update(incumbent=re.sub(r"\s*\(.*\)$", "", inc_raw), party=strip_notes(r[c_party]),
                           first_elected=strip_notes(r[c_first]), status=strip_notes(r[c_status]))
            else:
                # ratings tables annotate the incumbent, e.g. "Jan Brewer (term-limited)"
                m = re.search(r"\(([^)]*)\)\s*$", inc_raw)
                if not rec["incumbent"]:
                    rec["incumbent"] = re.sub(r"\s*\(.*\)$", "", inc_raw)
                if m:
                    rec["ratings_note"] = m.group(1)
    return list(found.values())


def classify(rec: dict) -> tuple[str, str]:
    """(term_limited, eligible) as '1'/'0'/'' from the election record's status text."""
    text = f"{rec['status']} {rec['ratings_note']}".lower()
    if not text.strip() or "tbd in" in text:
        return "", ""
    if "term-limited" in text or "term limited" in text:
        return "1", "0"
    for key in ("re-elected", "reelected", "retired", "retiring", "lost", "eligible", "running",
                "won", "defeated", "renomination", "renominated", "nominated", "elected to full term",
                "elected to a full term", "elected to finish", "incumbent elected",
                "eliminated in primary", "withdrew"):
        if key in text:
            return "0", "1"
    return "", ""


def load_elections() -> pd.DataFrame:
    """One row per state and election year (regular or vacancy special).

    Recall elections are dropped: they are not part of the election calendar
    a governor plans around. A special election appears in the summary table
    under the plain state name and in the ratings table as "(special)", so the
    records for a state and year are merged.
    """
    recs = []
    for f in sorted((GOV_RAW / "wikipedia").glob("*_gubernatorial_elections.json")):
        recs.extend(parse_election_year(int(f.name[:4])))
    df = pd.DataFrame(recs)
    df.loc[df["ratings_note"].str.contains("recall", case=False), "kind"] = "recall"
    recalls = df[df["kind"] == "recall"]
    df = df[df["kind"] != "recall"]

    def merge(g: pd.DataFrame) -> pd.Series:
        first = lambda col: next((v for v in g[col] if v), "")
        return pd.Series({
            "kind": "special" if (g["kind"] == "special").any() else "regular",
            "incumbent": first("incumbent"), "party": first("party"),
            "first_elected": first("first_elected"), "status": first("status"),
            "ratings_note": first("ratings_note")})

    df = df.groupby(["state", "year"]).apply(merge).reset_index()
    df["election_date"] = [nov_election_day(y) for y in df["year"]]
    df[["term_limited", "eligible"]] = [classify(r) for r in df.to_dict("records")]
    df.attrs["recalls"] = recalls
    return df.sort_values(["state", "election_date"]).reset_index(drop=True)


# --------------------------------------------------------------------------
# Tenures (Wikidata)
# --------------------------------------------------------------------------

def load_tenures() -> pd.DataFrame:
    t = pd.read_csv(GOV_RAW / "wikidata" / "governor_tenures.csv")
    t["state"] = t["posLabel"].str.replace(r"^[Gg]overnor of ", "", regex=True)
    t["start"] = pd.to_datetime(t["start"], errors="coerce").dt.date
    t["end"] = pd.to_datetime(t["end"], errors="coerce").dt.date
    t = t[t["state"].isin(STATE_NAMES) & t["start"].notna()]
    t = (t.groupby(["state", "person", "start"], as_index=False)
          .agg(name=("personLabel", "first"), end=("end", "max"),
               end_cause=("endCauseLabel", lambda s: "; ".join(sorted(set(s.dropna()))))))
    t = t[t["end"].isna() | (t["end"] >= WINDOW_START)]
    return t.sort_values(["state", "start"]).reset_index(drop=True)


def apply_overrides(ten: pd.DataFrame) -> pd.DataFrame:
    path = MANUAL / "governors_overrides.csv"
    if not path.exists():
        return ten
    ov = pd.read_csv(path, dtype=str).fillna("")
    ten = ten.copy()
    ten["override"] = ""
    d = lambda v: date.fromisoformat(v) if v else None
    for o in ov.itertuples():
        if o.action == "set_party":  # applied in finalize()
            continue
        if o.action == "add":
            ten = pd.concat([ten, pd.DataFrame([{
                "state": o.state, "person": "", "start": d(o.new_start), "name": o.governor,
                "end": d(o.new_end), "end_cause": "", "override": f"added from {o.source}"}])],
                ignore_index=True)
            continue
        hit = (ten["state"] == o.state) & (ten["name"] == o.governor) & (ten["start"] == d(o.match_start))
        if hit.sum() != 1:
            raise SystemExit(f"override matches {hit.sum()} tenures: {o}")
        if o.action == "drop":
            ten = ten[~hit]
        elif o.action == "set_end":
            ten.loc[hit, ["end", "override"]] = [d(o.new_end), f"end date from {o.source}"]
        elif o.action == "set_start":
            ten.loc[hit, ["start", "override"]] = [d(o.new_start), f"start date from {o.source}"]
        else:
            raise SystemExit(f"unknown override action {o.action}")
    return ten.sort_values(["state", "start"]).reset_index(drop=True)


def fill_labels(ten: pd.DataFrame, el: pd.DataFrame) -> pd.DataFrame:
    """Wikidata items without an English label come back as their Q-id; take
    the name from the Wikipedia election table for an election they faced."""
    for i, r in ten[ten["name"].str.fullmatch(r"Q\d+")].iterrows():
        cand = el[(el["state"] == r["state"]) & (el["election_date"] > r["start"])
                  & ((el["election_date"] <= r["end"]) if pd.notna(r["end"]) else True)]
        if len(cand):
            ten.loc[i, "name"] = cand.iloc[0]["incumbent"]
    return ten


# --------------------------------------------------------------------------
# Inauguration dates
# --------------------------------------------------------------------------

def _nth_weekday(d: date) -> tuple[int, int, int]:
    return d.month, d.weekday(), (d.day - 1) // 7 + 1


def _apply_rule(rule, year: int) -> date:
    kind, a, b, c = rule
    if kind == "fixed":
        return date(year, a, b)
    month, weekday, nth = a, b, c
    d = date(year, month, 1)
    while d.weekday() != weekday:
        d += timedelta(days=1)
    return d + timedelta(weeks=nth - 1)


def inauguration_dates(state: str, elections: pd.DataFrame, ten: pd.DataFrame) -> dict:
    """Inauguration date that follows each election in a state.

    Observed when a new governor took office within 120 days after the
    election; otherwise (incumbent re-elected) inferred from the state's
    observed dates as a fixed calendar day or an nth weekday of the month,
    whichever matches more observations."""
    starts = sorted(ten.loc[ten["state"] == state, "start"])
    observed, out = {}, {}
    for d in elections["election_date"]:
        nxt = [s for s in starts if d < s <= d + timedelta(days=120)]
        if nxt:
            # last start in the window: acting governors sometimes bridge the
            # gap before the elected governor is sworn in (e.g. Florida 1998)
            observed[d] = nxt[-1]
    pool = [v for v in observed.values()]
    rules = {}
    for v in pool:
        rules.setdefault(("fixed", v.month, v.day, 0), 0)
        rules.setdefault(("nth",) + _nth_weekday(v), 0)
    for rule in rules:
        rules[rule] = sum(_apply_rule(rule, v.year) == v for v in pool)
    best = max(rules, key=lambda r: (rules[r], r[0] == "nth")) if rules else None
    for d in elections["election_date"]:
        if d in observed:
            out[d] = (observed[d], "observed")
        elif best is not None:
            year = d.year if best[1] >= 11 else d.year + 1
            rule_txt = (f"{best[1]:02d}-{best[2]:02d}" if best[0] == "fixed" else
                        f"week {best[3]} {['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][best[2]]} of month {best[1]}")
            out[d] = (_apply_rule(best, year),
                      f"inferred ({rule_txt}; fits {rules[best]} of {len(pool)} observed inaugurations)")
        else:
            out[d] = (None, "unknown")
    return out


# --------------------------------------------------------------------------
# Term-limit rules
# --------------------------------------------------------------------------

def load_rules() -> pd.DataFrame:
    r = pd.read_csv(MANUAL / "term_limit_rules.csv", dtype=str).fillna("")
    r["from"] = pd.to_datetime(r["from"]).dt.date
    r["to"] = [date.fromisoformat(x) if x else date(9999, 1, 1) for x in r["to"]]
    return r


def rule_status(row: dict, person_rows: list[dict], rules: pd.DataFrame) -> tuple[str, str]:
    """term_limited ('1'/'0'/'') implied by the state's rule at the next election."""
    rec = row["_rec"]
    if rec is None:
        return "", "no next election on record"
    at = rec["election_date"]
    r = rules[(rules["state"] == row["state"]) & (rules["from"] <= at) & (at < rules["to"])]
    if len(r) != 1:
        return "", f"no rule for {row['state']} at {at}"
    r = r.iloc[0]
    rule, partial = r["rule"], r["partial_counts"] == "1"
    if rule == "none":
        return "0", "no term limit"
    if rule == "no_consecutive":
        return "1", "no consecutive terms"
    if rule == "unknown":
        return "", "term-limit rule in force not established"
    mine = sorted([p for p in person_rows if p["_start"] <= row["_start"]], key=lambda p: p["_start"])
    counts = lambda ps: sum(1 for p in ps if p["_elected"] or partial)
    if rule == "consec2":
        run = [mine[-1]]
        for p in reversed(mine[:-1]):
            if p["_end"] is not None and abs((run[0]["_start"] - p["_end"]).days) <= 7:
                run.insert(0, p)
            else:
                break
        n = counts(run)
        return ("1" if n >= 2 else "0"), f"two consecutive terms; {n} counted in current run"
    if rule == "lifetime2":
        n = counts([p for p in mine if p["_start"] >= r["from"]])
        return ("1" if n >= 2 else "0"), f"two terms in a lifetime; {n} counted since {r['from']}"
    if rule in ("eight_of_12", "eight_of_16"):
        span = 12 if rule == "eight_of_12" else 16
        end = row["_term_end"] or (at + timedelta(days=70))
        next_end = end + timedelta(days=4 * 365)
        window_start = next_end - timedelta(days=span * 365)
        served = 0
        for p in mine:
            s = max(p["_start"], window_start)
            e = end if p is mine[-1] else min(p["_end"] or end, end)
            served += max(0, (e - s).days)
        total = served + 4 * 365
        return ("1" if total > 8 * 365 + 60 else "0"), f"8 years in {span}; {served / 365:.1f} served in window"
    return "", f"unhandled rule {rule}"


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def klarner_check(rows: pd.DataFrame) -> pd.DataFrame:
    """Governor in office on 1 July of each year 1989-2011 vs Klarner govname1
    (Klarner names the governor inaugurated in January as that year's governor)."""
    f = sorted((RAW / "dataverse" / "klarner_governors").glob("StateElections_Gub*Public_Version.xlsx"))[0]
    k = pd.read_excel(f, usecols=["state", "year", "govname1"])
    k = k[(k["year"] >= 1989) & (k["year"] <= 2011)]
    out = []
    for r in k.itertuples():
        d = date(int(r.year), 7, 1)
        g = rows[(rows["state"] == r.state) & (rows["_start"] <= d) & (rows["_end"].isna() | (rows["_end"] > d))]
        ours = g["governor"].iloc[0] if len(g) else ""
        # Klarner sometimes names two people for a transition year ("A and then B")
        names = [surname(x.strip(" -")) for x in
                 re.split(r"\bthen\b|\band\b|\bfollowed by\b|[/;:]", str(r.govname1).replace("-,", ","))]
        out.append({"state": r.state, "year": int(r.year), "klarner": r.govname1, "ours": ours,
                    "agree": surname(ours) in names})
    return pd.DataFrame(out)


def build() -> tuple[pd.DataFrame, dict]:
    el = load_elections()
    ten = fill_labels(apply_overrides(load_tenures()), el)
    rows = []
    for state in sorted(STATE_NAMES):
        E = el[(el["state"] == state)].sort_values("election_date").reset_index(drop=True)
        inaug = inauguration_dates(state, E, ten)
        # slot k runs from the inauguration after election k-1 to the one after election k
        bounds = [(inaug[d][0], inaug[d][1], d) for d in E["election_date"] if inaug[d][0]]
        T = ten[ten["state"] == state].sort_values("start")
        for t in T.itertuples():
            end = t.end if pd.notna(t.end) else None
            if end is not None and end < WINDOW_START:
                continue
            cuts = [b for b in bounds if t.start < b[0] and (end is None or b[0] < end)
                    and b[0] <= SNAPSHOT]
            seg_starts = [(t.start, "took office")] + [(b[0], f"new term ({b[1]})") for b in cuts]
            for i, (s, why) in enumerate(seg_starts):
                e = seg_starts[i + 1][0] if i + 1 < len(seg_starts) else end
                if e is not None and e < WINDOW_START:
                    continue
                # election deciding this term: first election after the inauguration
                # that opened the slot containing s
                prior = [b for b in bounds if b[0] <= s]
                slot_open = prior[-1][2] if prior else date(1900, 1, 1)
                nxt = E[E["election_date"] > slot_open].head(1)
                rec = nxt.iloc[0].to_dict() if len(nxt) else None
                if rec is None and len(E):
                    # no Wikipedia page for that year yet: next regular election by the 4-year cycle
                    y = int(E["year"].max()) + 4
                    rec = {"year": y, "state": state, "kind": "regular", "incumbent": t.name,
                           "party": "", "first_elected": "", "status": "", "ratings_note": "",
                           "election_date": nov_election_day(y), "term_limited": "", "eligible": "",
                           "_scheduled": True}
                # an elected term starts on an inauguration day; anything else is a succession
                elected = any(b[0] == s for b in bounds)
                term_end = next((b[0] for b in bounds if rec is not None and b[2] == rec["election_date"]), None)
                rows.append({"state": state, "governor": t.name, "_start": s, "_end": e,
                             "_why": why, "_rec": rec, "_override": t.override,
                             "_end_cause": t.end_cause, "_elected": elected,
                             "_term_end": term_end})
    df = pd.DataFrame(rows)
    return df, {"elections": el, "tenures": ten}


def klarner_party() -> dict:
    f = sorted((RAW / "dataverse" / "klarner_governors").glob("StateElections_Gub*Public_Version.xlsx"))[0]
    k = pd.read_excel(f, usecols=["state", "year", "govname1", "govparty_a"]).dropna()
    return {(r.state, surname(r.govname1)): {1.0: "D", 0.0: "R"}.get(r.govparty_a, "")
            for r in k.itertuples() if r.govparty_a in (0.0, 1.0)}


def finalize(df: pd.DataFrame, ctx: dict) -> pd.DataFrame:
    el, rules, kparty = ctx["elections"], load_rules(), klarner_party()
    ov = pd.read_csv(MANUAL / "governors_overrides.csv", dtype=str).fillna("")
    party_override = {(o.state, o.governor): (o.new_start, o.source)
                      for o in ov.itertuples() if o.action == "set_party"}
    recs = df.to_dict("records")
    by_person: dict = {}
    for r in recs:
        by_person.setdefault((r["state"], r["governor"]), []).append(r)
    party_of = {}
    for e in el.itertuples():
        p = {"Democratic": "D", "Republican": "R", "Independent": "I"}.get(e.party, e.party)
        if p:
            party_of[(e.state, surname(e.incumbent))] = p
    out = []
    for r in recs:
        rec = r["_rec"]
        notes, sources, verified = [], ["wikidata"], 0
        tl = el_ok = nxt = ""
        key = (r["state"], surname(r["governor"]))
        party = ""
        if rec is not None:
            nxt = rec["election_date"].isoformat()
            if rec.get("_scheduled"):
                notes.append("next_election_date from the 4-year cycle (no election page yet)")
            if rec["kind"] == "special":
                notes.append("next election is a special election")
            same = surname(rec["incumbent"]) == surname(r["governor"]) and not rec.get("_scheduled")
            tl_rule, why = rule_status(r, by_person[(r["state"], r["governor"])], rules)
            if same and rec["term_limited"] != "":
                tl, el_ok = rec["term_limited"], rec["eligible"]
                party = {"Democratic": "D", "Republican": "R", "Independent": "I"}.get(rec["party"], rec["party"])
                sources.append(f"wikipedia {rec['year']} elections")
                if tl_rule in ("", tl):
                    verified = 1
                else:
                    notes.append(f"state rule suggests term_limited={tl_rule} ({why}); election page kept")
            else:
                days = ((r["_end"] or SNAPSHOT) - r["_start"]).days
                if not same and not r["_elected"] and days < 120 and r["_end"] is not None:
                    notes.append("acting/caretaker governor; term-limit fields not applicable")
                elif tl_rule != "":
                    tl, el_ok = tl_rule, ("0" if tl_rule == "1" else "1")
                    sources.append("term_limit_rules.csv")
                    notes.append(f"term_limited derived from state rule ({why})")
                else:
                    notes.append(f"term_limited unknown ({why})")
                if not same and not rec.get("_scheduled"):
                    notes.append(f"left office before the {rec['year']} election")
        if not party:
            party = party_of.get(key, "") or kparty.get(key, "")
        if not party and (r["state"], r["governor"]) in party_override:
            party, src = party_override[(r["state"], r["governor"])]
            notes.append(f"party from {src}")
        if r["_why"].startswith("new term (inferred"):
            notes.append("term_start " + r["_why"][10:-1])
        if r["_override"]:
            notes.append(r["_override"])
        out.append({
            "state": r["state"], "governor": r["governor"], "party": party,
            "term_start": r["_start"].isoformat(),
            "term_end": r["_end"].isoformat() if r["_end"] else "",
            "term_limited": tl, "eligible_next_election": el_ok, "next_election_date": nxt,
            "source": "; ".join(sources), "verified": verified, "notes": "; ".join(notes),
            "_start": r["_start"], "_end": r["_end"]})
    return pd.DataFrame(out)


def write_template() -> dict:
    df, ctx = build()
    g = finalize(df, ctx)
    k = klarner_check(g)
    cols = ["state", "governor", "party", "term_start", "term_end", "term_limited",
            "eligible_next_election", "next_election_date", "source", "verified", "notes"]
    g[cols].to_csv(MANUAL / "governors_template.csv", index=False)
    stats = {"rows": len(g), "verified": int(g.verified.sum()),
             "term_limited_blank": int((g.term_limited == "").sum()),
             "party_blank": int((g.party == "").sum()),
             "klarner_agreement": round(float(k.agree.mean()), 4), "klarner_years": len(k)}
    return stats


if __name__ == "__main__":
    print(write_template())
