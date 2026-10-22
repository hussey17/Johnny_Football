"""Optionally recreate the small prior-vote supplement from original CES Stata files.

The supplement is versioned, so running the notebook does not require the large
raw files. Source candidate choices are survey reports, not validated ballots.
Official FEC state returns are separately versioned as a manually transcribed,
source-linked six-row table; that table is deliberately not overwritten here.
"""
from pathlib import Path
import argparse, hashlib, json
import pandas as pd
root=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--ces-dir',type=Path,default=root/'data/CES')
args=p.parse_args()
parts=[];provenance=[]
for year,variables in [(2016,['V101','CC16_326','CC16_327','CC16_328']),(2024,['caseid','presvote20post'])]:
    paths=list((args.ces_dir/str(year)).glob('*.dta'))
    if len(paths)!=1: raise SystemExit(f'Expected one original Stata file in {args.ces_dir / str(year)}, found {len(paths)}')
    path=paths[0]
    d=pd.read_stata(path,columns=variables,convert_categoricals=False)
    d=d.rename(columns={variables[0]:'case_id',variables[1]:'prior_vote_raw',
                        'CC16_327':'primary_participation_raw','CC16_328':'primary_candidate_raw'})
    d.insert(0,'year',year);parts.append(d)
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    provenance.append({'year':year,'source_file':path.name,'columns':variables,'source_sha256':digest})
out=root/'data/analysis';out.mkdir(parents=True,exist_ok=True)
d=pd.concat(parts,ignore_index=True)
assert len(d)==124600 and not d.duplicated(['year','case_id']).any()
d.to_csv(out/'prior_vote_2016_2024.csv.gz',index=False,compression={'method':'gzip','mtime':0})
(out/'prior_vote_provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
print('Prepared',len(d),'prior-vote records')
