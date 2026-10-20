#!/usr/bin/env python3
"""Build auditable CES extracts and a respondent-level CES/COVI staging file.

Run from any directory: python code/prepare_data.py
Original source files are never changed. No observations are dropped or models fit.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
DOCS = ROOT / 'docs'
YEARS = (2016, 2020, 2024)
EXPECTED = {2016: 64600, 2020: 61000, 2024: 60000}
# These are Census FIPS codes. COVI's statenu is an alphabetical ordinal, NOT FIPS.
FIPS_POSTAL = dict(zip(
    [1,2,4,5,6,8,9,10,11,12,13,15,16,17,18,19,20,21,22,23,24,25,26,27,
     28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,44,45,46,47,48,49,50,51,53,54,55,56],
    'AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split()
))
STATES = set(FIPS_POSTAL.values()) - {'DC'}
POSTAL_FIPS = {v:k for k,v in FIPS_POSTAL.items()}

SOURCES = {
    2016: {'id':'V101','turnout':'CL_E2016GVM','match':'CL_matched',
           'status':'CL_voterstatus','file_state':'CL_state','gender':'gender',
           'income':'faminc','post_vote':'CC16_410a','pre_early':'CC16_364b',
           'pre_pref':'CC16_364c','post_nv':'CC16_410a_nv',
           'self_turnout':'CC16_401','w_pre':'commonweight_vv',
           'w_post':'commonweight_vv_post'},
    2020: {'id':'caseid','turnout':'CL_2020gvm','match':'CL_voter_status',
           'status':'CL_voter_status','file_state':'CL_state','gender':'gender',
           'income':'faminc_new','post_vote':'CC20_410','pre_early':'CC20_364a',
           'pre_pref':'CC20_364b','post_nv':'CC20_410a_nv',
           'self_turnout':'CC20_401','w_pre':'commonweight',
           'w_post':'commonpostweight'},
    2024: {'id':'caseid','turnout':'TS_g2024','match':'TS_voterstatus',
           'status':'TS_voterstatus','file_state':'TS_state','gender':'gender4',
           'income':'faminc_new','post_vote':'CC24_410','pre_early':'CC24_364a',
           'pre_pref':'CC24_364b','post_nv':'CC24_410_nv',
           'self_turnout':'CC24_401','w_pre':'commonweight',
           'w_post':'commonpostweight'},
}

def json_write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, default=str)+'\n')

def save_csv(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # A fixed mtime makes compressed extracts deterministic across rebuilds.
    compression = {'method':'gzip', 'mtime':0} if str(path).endswith('.gz') else None
    df.to_csv(path, index=False, compression=compression)

def prepare_covi():
    raw = DATA/'COVI/raw'
    df = pd.read_excel(raw/'COVI Values 1996-2024 website.xlsx')
    df = df.loc[df.year.isin(YEARS)].copy()
    df = df.rename(columns={'state':'state_postal','statenu':'covi_state_ordinal',
                            'FinalCOVI':'covi_final','FinalRank':'covi_final_rank',
                            'InitialCOVI':'covi_initial','InitialRank':'covi_initial_rank',
                            'COVIDCOVI':'covi_covid','COVIDRank':'covi_covid_rank',
                            'COVI2022_IRT':'covi_2022_irt','COVI2022_IRTrank':'covi_2022_irt_rank'})
    df['state_fips'] = df.state_postal.map(POSTAL_FIPS)
    df['year'] = df.year.astype(int)
    assert len(df)==150 and not df.duplicated(['state_postal','year']).any()
    assert df.covi_final.notna().all() and df.state_fips.notna().all()
    checks = {'rows':len(df),'years':{},'policy_rows_removed':{}}
    for year in YEARS:
        part = df.loc[df.year.eq(year)].copy()
        assert len(part)==50 and set(part.state_postal)==STATES
        assert part.covi_final_rank.nunique()==50
        out = DATA/'COVI'/str(year)
        save_csv(part, out/f'covi_{year}.csv')
        policies = pd.read_excel(raw/'Master 1996 2024 Election voting requirements.xlsx', sheet_name=str(year))
        nraw = len(policies)
        policies = policies.loc[policies.State.isin(STATES) & pd.to_numeric(policies.Year,errors='coerce').eq(year)].copy()
        assert len(policies)==50 and not policies.State.duplicated().any()
        save_csv(policies, out/f'policy_components_{year}.csv')
        checks['years'][year] = {'states':50,'final_index_missing':int(part.covi_final.isna().sum()),
                                'covid_index_available':int(part.covi_covid.notna().sum())}
        checks['policy_rows_removed'][year] = nraw-len(policies)
    policies = pd.read_excel(raw/'Master 1996 2024 Election voting requirements.xlsx',sheet_name='2020CCOVI')
    policies = policies.loc[policies.State.isin(STATES) & policies.Year.eq(2020)]
    assert len(policies)==50
    save_csv(policies, DATA/'COVI/2020/policy_components_2020_covid.csv')
    save_csv(df, DATA/'COVI/covi_state_year_2016_2020_2024.csv')
    wide = df.pivot(index='state_postal',columns='year',values='covi_final')
    checks['states_with_final_index_change'] = int(wide.nunique(axis=1).gt(1).sum())
    return df,checks

def prepare_ces(year):
    cfg = SOURCES[year]
    source_dir = DATA/'CES'/str(year)
    paths = list(source_dir.glob('*.dta'))
    assert len(paths)==1, paths
    with pd.io.stata.StataReader(paths[0],convert_categoricals=False) as reader:
        variable_labels = reader.variable_labels()
        value_labels = reader.value_labels()
        raw_names = list(variable_labels)
        label_names = reader._lbllist
        metadata = {}
        for name, label_name in zip(raw_names,label_names):
            metadata[name] = {'variable_label':variable_labels[name],
                              'value_labels':{str(k):str(v) for k,v in value_labels.get(label_name,{}).items()}}
        required = set(cfg.values()) | {'inputstate','inputstate_post','birthyr','educ','race',
                                        'hispanic','pid7','ideo5','immstat','tookpost','votereg_post'}
        optional = {'vvweight','vvweight_post'}
        assert required.issubset(raw_names), required-set(raw_names)
        columns = [c for c in raw_names if c in required|optional]
        df = reader.read(columns=columns, convert_categoricals=False)
    assert len(df)==EXPECTED[year] and df[cfg['id']].notna().all()
    assert df[cfg['id']].is_unique
    json_write(source_dir/'metadata/variable_labels.json',metadata)
    save_csv(pd.DataFrame([{'source_variable':k, 'variable_label':v} for k,v in variable_labels.items()]),
             source_dir/'metadata/variable_dictionary.csv')
    crosswalk = [{'year':year,'role':role,'source_variable':source,
                  'source_label':variable_labels[source]} for role,source in cfg.items()]
    for source in ['inputstate','inputstate_post','birthyr','educ','race','hispanic','pid7',
                   'ideo5','immstat','tookpost','votereg_post']:
        crosswalk.append({'year':year,'role':source,'source_variable':source,'source_label':variable_labels[source]})
    def describe(source):
        vals=metadata[source]['value_labels']
        if not vals:return df[source].fillna('').astype(str)
        mapped={float(k):v for k,v in vals.items()}
        return df[source].map(mapped).fillna('')
    out=pd.DataFrame({'year':year,'case_id':df[cfg['id']].astype('int64')})
    out['state_fips']=df.inputstate
    out['state_postal']=df.inputstate.map(FIPS_POSTAL)
    out['state_post_fips']=df.inputstate_post
    out['file_state']=df[cfg['file_state']].fillna('').astype(str)
    out['moved_state_pre_post']=np.where(df.inputstate_post.notna(),
                                         df.inputstate.ne(df.inputstate_post).astype(float),np.nan)
    assert out.state_postal.notna().all()
    out['birth_year']=df.birthyr
    out['age']=year-df.birthyr
    out['citizenship_raw']=df.immstat
    out['citizen']=df.immstat.map({1:1,2:0,3:1,4:1,5:1})
    out['adult_citizen']=np.where(out.citizen.notna() & out.age.notna(),
                                  (out.citizen.eq(1)&out.age.ge(18)).astype(float),np.nan)
    out['gender_raw']=df[cfg['gender']]
    out['gender_label']=describe(cfg['gender'])
    out['gender_group']=df[cfg['gender']].where(df[cfg['gender']].isin([1,2,3,4] if year==2024 else [1,2]))
    out['education_raw']=df.educ
    out['education']=df.educ.where(df.educ.isin(range(1,7)))
    out['race_raw']=df.race
    out['hispanic_raw']=df.hispanic
    out['race_h']=df.race.where(df.race.isin(range(1,9)))
    out.loc[df.race.eq(3)|df.hispanic.eq(1),'race_h']=3
    out['income_raw']=df[cfg['income']]
    income_map={1:1,2:1,3:1,4:2,5:2,6:3,7:3,8:3,9:3,10:4,11:4,12:5,13:5,14:5,15:5,16:5}
    if year==2016:income_map[31]=5
    out['income_group']=df[cfg['income']].map(income_map)
    out['pid7_raw']=df.pid7
    out['pid7']=df.pid7.where(df.pid7.isin(range(1,8)))
    out['ideology_raw']=df.ideo5
    out['ideology5']=df.ideo5.where(df.ideo5.isin(range(1,6)))
    assert df.tookpost.isin([0,1] if year==2016 else [1,2]).all()
    out['took_post']=df.tookpost.eq(1 if year==2016 else 2).astype(int)
    out['weight_adult_pre']=df[cfg['w_pre']]
    out['weight_adult_post']=df[cfg['w_post']]
    out['weight_reg_pre']=df.vvweight if 'vvweight' in df else np.nan
    out['weight_reg_post']=df.vvweight_post if 'vvweight_post' in df else np.nan
    out['file_status_label']=describe(cfg['status'])
    out['turnout_raw']=df[cfg['turnout']]
    if year==2016:
        assert df.CL_matched.isin(['Y','N']).all()
        assert set(df[cfg['turnout']].dropna().unique()) <= {'','absentee','earlyVote','mail','polling','unknown'}
        matched=df.CL_matched.eq('Y')
        voted=df[cfg['turnout']].isin(['absentee','earlyVote','mail','polling','unknown'])
        active=df.CL_voterstatus.eq('active')
    elif year==2020:
        assert df[cfg['turnout']].dropna().isin([1,2,3,4,5]).all()
        matched=df.CL_voter_status.notna()
        voted=df.CL_2020gvm.isin([1,2,3,4,5])
        active=df.CL_voter_status.eq(1)
    else:
        assert df.TS_g2024.dropna().isin(range(1,8)).all()
        matched=df.TS_voterstatus.notna()
        voted=df.TS_g2024.isin(range(1,7))
        active=df.TS_voterstatus.eq(1)
        assert matched.equals(df.TS_g2024.notna())
    assert not (voted & ~matched).any()
    out['matched_file']=matched.astype(int)
    out['active_file']=active.astype(int)
    out['turnout_matched']=np.where(matched,voted.astype(float),np.nan)
    out['turnout_unmatched_zero']=voted.astype(int)
    out['self_turnout_raw']=df[cfg['self_turnout']]
    out['self_turnout']=df[cfg['self_turnout']].map({1:0,2:0,3:0,4:0,5:1})
    out['votereg_post_raw']=df.votereg_post
    vote=df[cfg['post_vote']]
    out['post_choice_raw']=vote
    out['post_choice_label']=describe(cfg['post_vote'])
    valid={2016:[1,2,3,4,5,8],2020:[1,2,4],2024:[1,2,3,4,5,6,8]}[year]
    rep=1 if year==2016 else 2
    dem=2 if year==2016 else 1
    out['reported_candidate']=vote.isin(valid).astype(int)
    out['reported_major_party']=vote.isin([rep,dem]).astype(int)
    out['republican_any']=np.where(voted&vote.isin(valid),vote.eq(rep).astype(float),np.nan)
    out['republican_2party']=np.where(voted&vote.isin([rep,dem]),vote.eq(rep).astype(float),np.nan)
    out['choice_missing_if_voted']=(voted&~vote.isin(valid)).astype(int)
    out['candidate_without_valid_vote']=(~voted&vote.isin(valid)).astype(int)
    out['pre_early_choice_raw']=df[cfg['pre_early']]
    out['pre_pref_choice_raw']=df[cfg['pre_pref']]
    # Code 1 is Trump in 2016 and 2020 PRE questions, but Harris in 2024.
    pre_rep=2 if year==2024 else 1
    valid_pre=[1,2,3,4,5] if year==2016 else [1,2,3]
    e=df[cfg['pre_early']].where(df[cfg['pre_early']].isin(valid_pre))
    p=df[cfg['pre_pref']].where(df[cfg['pre_pref']].isin(valid_pre))
    pre=e.combine_first(p)
    out['pre_republican_any']=np.where(pre.notna(),pre.eq(pre_rep).astype(float),np.nan)
    out['post_nonvoter_pref_raw']=df[cfg['post_nv']]
    out['post_nonvoter_pref_label']=describe(cfg['post_nv'])
    # Stata needs a common type across years: 2016 validation methods are strings.
    out['turnout_raw']=out.turnout_raw.fillna('').astype(str)
    controls=['age','gender_group','education','race_h','income_group','pid7','ideology5']
    out['controls_complete']=out[controls].notna().all(axis=1).astype(int)
    assert out.loc[out.turnout_matched.ne(1),'republican_any'].isna().all()
    assert out.loc[out.took_post.eq(0),'republican_any'].isna().all()
    assert out.turnout_matched.dropna().isin([0,1]).all()
    save_csv(out,source_dir/f'ces_core_{year}.csv.gz')
    counts={'raw_rows':len(out),'raw_variables':len(raw_names),'unique_case_ids':out.case_id.nunique(),
            'post_wave':int(out.took_post.sum()),'matched_file':int(matched.sum()),
            'unmatched_file':int((~matched).sum()),'validated_voters':int(voted.sum()),
            'matched_nonvoters':int((matched&~voted).sum()),
            'voters_without_usable_choice':int(out.choice_missing_if_voted.sum()),
            'validated_voters_with_choice':int(out.republican_any.notna().sum()),
            'matched_nonvoters_with_pre_pref':int((out.turnout_matched.eq(0)&out.pre_republican_any.notna()).sum()),
            'post_hypothetical_pref_nonmissing':int(out.post_nonvoter_pref_raw.notna().sum()),
            'state_pre_post_changes':int(out.moved_state_pre_post.eq(1).sum())}
    json_write(source_dir/'metadata/core_checks.json',counts)
    return out,counts,crosswalk

def export_stata(merged, path):
    st=merged.copy()
    for c in st:
        assert len(c)<=32,c
        if st[c].dtype==object or isinstance(st[c].dtype,pd.StringDtype):st[c]=st[c].fillna('').astype(object)
    st.to_stata(path,write_index=False,version=118,
                data_label='CES COVI staging 2016 2020 2024 all respondents')
    back=pd.read_stata(path,columns=['year','case_id','turnout_matched','republican_any','covi_final'],
                       convert_categoricals=False)
    assert len(back)==185600 and not back.duplicated(['year','case_id']).any()
    for c in back:assert np.allclose(back[c],merged[c],equal_nan=True),c

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore-stata',action='store_true',
                        help='Recreate only the Stata file from the small staged CSV.gz; raw sources not required')
    args=parser.parse_args()
    if args.restore_stata:
        prepared=DATA/'prepared'
        merged=pd.read_csv(prepared/'ces_covi_2016_2020_2024.csv.gz',low_memory=False,
                           dtype={'turnout_raw':'str'})
        export_stata(merged,prepared/'ces_covi_2016_2020_2024.dta')
        print('Restored Stata file from staged CSV.gz; key/outcome round-trip passed',flush=True)
        return
    DOCS.mkdir(parents=True,exist_ok=True)
    covi,covi_checks=prepare_covi()
    rows=[];checks={};crosswalk=[]
    for year in YEARS:
        df,audit,cw=prepare_ces(year)
        rows.append(df);checks[year]=audit;crosswalk.extend(cw)
        print(year,json.dumps(audit),flush=True)
    all_ces=pd.concat(rows,ignore_index=True)
    assert len(all_ces)==185600 and not all_ces.duplicated(['year','case_id']).any()
    merged=all_ces.merge(covi,on=['year','state_postal','state_fips'],how='left',validate='many_to_one',indicator=True)
    assert len(merged)==185600
    merged['covi_merge_ok']=merged['_merge'].eq('both').astype(int)
    unmatched=merged.loc[merged._merge.ne('both')]
    assert set(unmatched.state_postal.unique()) <= {'DC'}
    save_csv(unmatched.groupby(['year','state_postal'],dropna=False).size().rename('rows').reset_index(),
             DOCS/'unmatched_state_years.csv')
    merged=merged.drop(columns=['_merge'])
    # This is a transparent candidate sample, NOT an instructor-approved final model sample.
    merged['sample_candidate']= (
        merged.adult_citizen.eq(1)&merged.matched_file.eq(1)&merged.covi_merge_ok.eq(1)&
        merged.controls_complete.eq(1)&merged.took_post.eq(1)&
        merged.weight_adult_post.gt(0)&
        (merged.turnout_matched.eq(0)|(merged.turnout_matched.eq(1)&merged.republican_any.notna()))
    ).astype(int)
    prepared=DATA/'prepared';prepared.mkdir(parents=True,exist_ok=True)
    save_csv(merged,prepared/'ces_covi_2016_2020_2024.csv.gz')
    # Export ordinary numeric codes and labels as separate string columns. No hidden recodes.
    # Round-trip meaningful key/merge/outcome invariants in the exported Stata file.
    export_stata(merged,prepared/'ces_covi_2016_2020_2024.dta')
    for year in YEARS:
        m=merged.loc[merged.year.eq(year)]
        checks[year]['covi_matched']=int(m.covi_merge_ok.sum())
        checks[year]['covi_unmatched_dc']=int(m.covi_merge_ok.eq(0).sum())
        checks[year]['candidate_sample']=int(m.sample_candidate.sum())
        checks[year]['candidate_sample_nonvoters']=int((m.sample_candidate.eq(1)&m.turnout_matched.eq(0)).sum())
    json_write(DOCS/'validation_report.json',{'ces':checks,'covi':covi_checks,
                                             'pooled_rows':len(merged),'pooled_columns':len(merged.columns),
                                             'duplicate_year_case_id':0,'export_roundtrip':'passed'})
    save_csv(pd.DataFrame(crosswalk),DOCS/'variable_crosswalk.csv')
    save_csv(pd.DataFrame(checks).T.rename_axis('year').reset_index(),DOCS/'sample_counts.csv')
    dictionary={
        'turnout_matched':'1 validated voter; 0 matched with no voting record; missing unmatched. 2024 TS_g2024=7 is a NONVOTER.',
        'turnout_unmatched_zero':'Sensitivity: 1 validated voter; 0 everybody else, including unmatched.',
        'republican_any':'Only validated voters with usable post choice: 1 Republican; 0 other reported candidate, including Other.',
        'republican_2party':'Only validated voters reporting Republican or Democrat. Third-party and other records remain missing.',
        'pre_republican_any':'Coalesced usable pre-wave early vote and candidate preference. Hold out from model controls if used for validation.',
        'post_nonvoter_pref_raw':'Hypothetical post-election preference, routed by SELF-reported nonvoting; not an observed ballot.',
        'gender_group':'2016/2020: 1 Male, 2 Female. 2024: 1 Man, 2 Woman, 3 Non-binary, 4 Other. Measure changes over time.',
        'income_group':'Nominal annual household income: 1 <30k; 2 30k-49,999; 3 50k-99,999; 4 100k-149,999; 5 >=150k.',
        'race_h':'Original race 1-8, overriding to 3 Hispanic if race=3 OR hispanic=1. Retains raw inputs.',
        'education':'1 No HS; 2 HS graduate; 3 Some college; 4 2-year; 5 4-year; 6 Post-grad. Nonanswers missing.',
        'pid7':'1 Strong Democrat through 7 Strong Republican. Not sure/dont know/nonanswers missing; raw codes retained.',
        'ideology5':'1 Very liberal through 5 Very conservative. Nonanswers missing; raw codes retained.',
        'sample_candidate':'Convenience flag: matched adult citizen, 50 states, post-wave, positive adult post weight, full controls, and known choice if voter. Not the finalized model sample.',
        'state_fips':'PRE-election inputstate, mapped to postal abbreviation. Post-wave and later voter-file state retained separately.',
        'weight_adult_pre':'2016 commonweight_vv; 2020/2024 commonweight.',
        'weight_adult_post':'2016 commonweight_vv_post; 2020/2024 commonpostweight.',
        'weight_reg_pre':'2020/2024 vvweight for ACTIVE registered adults only. Missing by design in 2016 extract.',
        'weight_reg_post':'2020/2024 vvweight_post for ACTIVE registered post-wave adults only. Missing by design in 2016.',
        'covi_final':'Published revised FinalCOVI, no rescaling/re-estimation. Higher means higher voting costs.',
        'covi_covid':'Published COVIDCOVI for 2020 only; missing outside 2020 is intentional.',
        'covi_state_ordinal':'COVI statenu retained for provenance. It is NOT Census state FIPS.'
    }
    json_write(DOCS/'harmonized_variable_notes.json',dictionary)
    print('POOLED',len(merged),'rows',len(merged.columns),'columns; exports and checks passed',flush=True)

if __name__=='__main__':main()
