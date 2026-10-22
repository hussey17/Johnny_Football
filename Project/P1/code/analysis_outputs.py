"""Auditable tables and graphics called explicitly by the analysis notebook."""
from pathlib import Path
import json, hashlib, platform, sys
import numpy as np
import pandas as pd
from scipy.stats import t as student_t
from scipy.special import ndtr
from selection_analysis import *

METHODS=['baseline_state_FE','probit_no_state_FE','heckprobit_COVI']

def load_inputs(root):
    root=Path(root)
    all_data=pd.read_csv(root/'data/prepared/ces_covi_2016_2020_2024.csv.gz',low_memory=False)
    prior=pd.read_csv(root/'data/analysis/prior_vote_2016_2024.csv.gz')
    d=all_data.loc[all_data.year.isin([2016,2024]) & all_data.sample_candidate.eq(1)].copy()
    d=d.merge(prior,on=['year','case_id'],how='left',validate='one_to_one').reset_index(drop=True)
    assert d.groupby('year').size().to_dict()=={2016:32453,2024:31484}
    assert d.loc[d.turnout_matched.eq(0),'republican_any'].isna().all()
    assert d.loc[d.turnout_matched.eq(1),'republican_any'].isin([0,1]).all()
    assert d.covi_final.notna().all() and d.state_postal.ne('DC').all()
    tables=root/'results/tables'; tables.mkdir(parents=True,exist_ok=True)
    rows=[]
    for y,a in all_data.groupby('year'):
        if y not in [2016,2024]: continue
        part=d[d.year.eq(y)]; w=part.weight_adult_post
        rows.append({'year':y,'original_n':len(a),'candidate_n':len(part),
            'voter_n':int(part.turnout_matched.sum()),'nonvoter_n':int(part.turnout_matched.eq(0).sum()),
            'weighted_sample_turnout':average(part.turnout_matched,w),'matched_raw_n':int(a.matched_file.sum()),
            'unmatched_raw_n':int(a.matched_file.eq(0).sum()),'choice_missing_voters_raw_n':int(a.choice_missing_if_voted.sum())})
    counts=pd.DataFrame(rows); save(counts,tables/'sample_counts.csv')
    rows=[]
    for (y,s),a in d.groupby(['year','state_postal']):
        nv=a[a.turnout_matched.eq(0)]
        rows.append({'year':y,'state_postal':s,'candidate_n':len(a),'voter_n':int(a.turnout_matched.sum()),
           'nonvoter_n':len(nv),'nonvoter_kish_n':kish(nv.weight_adult_post)})
    state_counts=pd.DataFrame(rows); save(state_counts,tables/'state_sample_counts.csv')
    return d,counts,state_counts

def run_election(d,year,tables):
    a=d[d.year.eq(year)].reset_index(drop=True); S=a.turnout_matched; selected=S.eq(1)
    x=design(a); xf=design(a,state=True); z=x.assign(COVI=a.covi_final.to_numpy())
    fits={}
    print(f'{year}: fitting turnout and baseline choice...',flush=True)
    fits['turnout_state_FE']=fit_probit(a,xf,S,name='turnout_state_FE')
    fits['turnout_COVI']=fit_probit(a,z,S,name='turnout_COVI')
    fits['baseline_state_FE']=fit_probit(a,xf,a.republican_any,selected,name='baseline_state_FE')
    fits['probit_no_state_FE']=fit_probit(a,x,a.republican_any,selected,name='probit_no_state_FE')
    print(f'{year}: joint selection likelihood, three starting correlations...',flush=True)
    fits['heckprobit_COVI']=selection(a,x,z,name='heckprobit_COVI')
    two=lecture_two_step(a,x,z,fits['turnout_COVI']); two['year']=year
    for fit in fits.values():
        fit.diagnostics['score_jacobian_asymmetry']=fit_derivative_check(fit)
    coef=pd.concat([fit.table().assign(year=year) for fit in fits.values()],ignore_index=True)
    save(coef,Path(tables)/f'coefficients_{year}.csv')
    print(f'{year}: rho={fits["heckprobit_COVI"].diagnostics["rho"]:.4f}',flush=True)
    return fits,two

def preference_results(fits_by_year,tables):
    rows=[]; influences={}; state_rows=[]; diagnostics=[]
    for year,fits in fits_by_year.items():
        for name,fit in fits.items():
            if name not in METHODS: continue
            non=fit.data.turnout_matched.eq(0).to_numpy()
            res,IF=fit.mean_prediction(non)
            influences[(year,name)]=IF
            rows.append({'year':year,'model':name,'p_republican':res['estimate'],
                'p_allocated_democratic':1-res['estimate'],'cluster_se':res['cluster_se'],
                'r_ci_low':res['ci_low'],'r_ci_high':res['ci_high'],
                'allocated_d_ci_low':1-res['ci_high'],'allocated_d_ci_high':1-res['ci_low'],
                'nonvoter_n':res['n'],'kish_n':res['kish_n']})
            if name=='heckprobit_COVI':
                marginal,_=fit.mean_prediction(non,'marginal')
                rows[-1]['marginal_r_different_target']=marginal['estimate']
            for state in ['MI','WI','PA']:
                mask=non & fit.data.state_postal.eq(state).to_numpy()
                st,_=fit.mean_prediction(mask)
                state_rows.append({'year':year,'state_postal':state,'model':name,
                    'p_republican':st['estimate'],'p_allocated_democratic':1-st['estimate'],
                    'parameter_only_se':st['parameter_only_se'],'nonvoter_n':st['n'],'kish_n':st['kish_n'],
                    'state_population_ci_available':False})
        for name,fit in fits.items():
            diag={'year':year,'model':name,**fit.diagnostics}; diagnostics.append(diag)
    prefs=pd.DataFrame(rows); states=pd.DataFrame(state_rows)
    save(prefs,Path(tables)/'national_preferences.csv'); save(states,Path(tables)/'blue_wall_preferences.csv')
    contrasts=[]
    for name in METHODS:
        before=prefs[(prefs.year==2016)&(prefs.model==name)].iloc[0]
        after=prefs[(prefs.year==2024)&(prefs.model==name)].iloc[0]
        labels=set(influences[(2016,name)])|set(influences[(2024,name)])
        diff=np.array([influences[(2024,name)].get(k,0)-influences[(2016,name)].get(k,0) for k in labels])
        G=len(labels); # Cluster the cross-election contrast by the same state.
        # Each year already uses its model's finite-sample multiplier.
        f0=fits_by_year[2016][name].correction; f1=fits_by_year[2024][name].correction
        diff=np.array([np.sqrt(f1)*influences[(2024,name)].get(k,0)-np.sqrt(f0)*influences[(2016,name)].get(k,0) for k in labels])
        se=np.sqrt(np.sum(diff**2)); delta=after.p_republican-before.p_republican
        crit=student_t.ppf(.975,G-1)
        contrasts.append({'model':name,'r_change_2024_minus_2016':delta,'cluster_se':se,
             'ci_low':delta-crit*se,'ci_high':delta+crit*se,'p_value':2*student_t.sf(abs(delta/se),G-1),
             'clusters':G,'assumption':'arbitrary dependence within state across years; covariate-mix plus fit uncertainty'})
    save(pd.DataFrame(contrasts),Path(tables)/'cross_year_contrasts.csv')
    (Path(tables).parent/'model_diagnostics.json').write_text(json.dumps(diagnostics,indent=2,default=float)+'\n')
    return prefs,states,pd.DataFrame(contrasts),diagnostics

def counterfactuals(states,returns,tables):
    m=states.merge(returns,on=['year','state_postal'],validate='many_to_one'); rows=[]; scenarios=[]
    for r in m.itertuples():
        for q in [1.,.9,.8,2/3,.5]:
            # q allocates the non-Republican bloc; q=1 is the headline scenario.
            net=q*(1-r.p_republican)-r.p_republican
            need=np.floor(r.rep_margin/net)+1 if net>0 else np.nan
            row={'year':r.year,'state_postal':r.state_postal,'model':r.model,'q_nonR_to_D':q,
                 'p_republican':r.p_republican,'net_dem_votes_per_added_participant':net,
                 'rep_margin':r.rep_margin,'minimum_additional_participants':need,
                 'nonvoter_n':r.nonvoter_n,'kish_n':r.kish_n,
                 'q_break_even':r.p_republican/(1-r.p_republican)}
            rows.append(row)
            for added in [25000,50000,100000,250000,500000]:
                scenarios.append({**row,'hypothetical_added_participants':added,
                    'expected_dem_net_gain':added*net,'expected_margin_overturned':added*net>r.rep_margin})
    thresholds=pd.DataFrame(rows); save(thresholds,Path(tables)/'blue_wall_thresholds.csv')
    save(pd.DataFrame(scenarios),Path(tables)/'participation_scenarios.csv')
    # All three state changes are required for these illustrated EC totals.
    save(pd.DataFrame([
      {'year':2016,'dem_ec_before_faithless':232,'rep_ec_before_faithless':306,'ev_reallocated_if_all_three_flip':46,
       'dem_ec_if_all_three_flip':278,'rep_ec_if_all_three_flip':260,'note':'Standard state allocations before faithless electors; hold all other states fixed.'},
      {'year':2024,'dem_ec_before_faithless':226,'rep_ec_before_faithless':312,'ev_reallocated_if_all_three_flip':44,
       'dem_ec_if_all_three_flip':270,'rep_ec_if_all_three_flip':268,'note':'Hold all other states fixed.'}]),Path(tables)/'electoral_college_arithmetic.csv')
    return thresholds

def transition_tables(d,tables):
    rows=[]; coverage=[]; sanders=[]
    for year,a in d.groupby('year'):
        prior=a.prior_vote_raw.map({1:'Prior Democrat',2:'Prior Republican',3:'Prior other',4:'Prior nonvoter'} if year==2016 else
                                   {1:'Prior Democrat',2:'Prior Republican',3:'Prior other',4:'Prior other',5:'Prior other',6:'Prior nonvoter'})
        current=np.where(a.turnout_matched.eq(0),'Abstained',np.where(a.republican_any.eq(1),'Republican',
                         np.where(a.reported_major_party.eq(1),'Democrat','Other candidate')))
        for area,mask in [('National',np.ones(len(a),bool))]+[(s,a.state_postal.eq(s).to_numpy()) for s in ['MI','WI','PA']]:
            g=a.loc[mask]; pp=prior.loc[mask]; cc=current[mask]; w=g.weight_adult_post
            coverage.append({'year':year,'area':area,'sample_n':len(g),'known_prior_vote_n':int(pp.notna().sum()),
                'weighted_known_prior_fraction':average(pp.notna(),w)})
            for origin in ['Prior Democrat','Prior Republican','Prior other','Prior nonvoter']:
                sub=pp.eq(origin).to_numpy(); den=w.to_numpy()[sub].sum()
                if den<=0: continue
                for dest in ['Democrat','Republican','Other candidate','Abstained']:
                    target=sub&(cc==dest)
                    rows.append({'year':year,'area':area,'prior_group':origin,'current_status':dest,
                      'prior_group_n':int(sub.sum()),'cell_n':int(target.sum()),
                      'weighted_fraction_within_prior_group':float(w.to_numpy()[target].sum()/den),
                      'prior_group_kish_n':kish(w.to_numpy()[sub])})
        if year==2016:
            sg=a.primary_candidate_raw.eq(2)&a.primary_participation_raw.eq(1)
            for dest in ['Democrat','Republican','Other candidate','Abstained']:
                sanders.append({'year':year,'group':'Self-reported Sanders primary voters','current_status':dest,
                   'group_n':int(sg.sum()),'cell_n':int((sg&(current==dest)).sum()),
                   'weighted_fraction':average(current[sg]==dest,a.loc[sg,'weight_adult_post'])})
    tr=pd.DataFrame(rows); save(tr,Path(tables)/'prior_vote_transitions.csv')
    save(pd.DataFrame(coverage),Path(tables)/'prior_vote_coverage.csv')
    save(pd.DataFrame(sanders),Path(tables)/'sanders_descriptive_transitions.csv')
    return tr

def benchmark_tables(fits,tables):
    rows=[]
    for year,models in fits.items():
        fit=models['baseline_state_FE']; a=fit.data; non=a.turnout_matched.eq(0)
        for label,v in [('Pre-election stated preference',a.pre_republican_any),
                        ('Post-election hypothetical nonvoter preference',a.post_nonvoter_pref_raw)]:
            if label.startswith('Post'):
                valid=[1,2,3,4,5,8] if year==2016 else [1,2,3,4,5,6,8]
                v=v.where(v.isin(valid)); v=v.map(lambda z:float(z==(1 if year==2016 else 2)) if pd.notna(z) else np.nan)
            mask=non&v.notna()
            rows.append({'year':year,'benchmark':label,'available_nonvoter_n':int(mask.sum()),
               'weighted_coverage_among_nonvoters':average(v[non].notna(),a.loc[non,'weight_adult_post']),
               'stated_r_share':average(v[mask],a.loc[mask,'weight_adult_post']),
               'baseline_predicted_r_same_subset':average(fit.predict_function(fit.theta,'nonvoter')[mask],fit.weights[mask]),
               'heck_predicted_r_same_subset':average(models['heckprobit_COVI'].predict_function(models['heckprobit_COVI'].theta,'nonvoter')[mask],fit.weights[mask])})
    out=pd.DataFrame(rows); save(out,Path(tables)/'nonvoter_benchmarks.csv'); return out

def robustness(d,tables):
    rows=[]; coeff=[]
    for year in [2016,2024]:
        a=d[d.year.eq(year)].reset_index(drop=True)
        for variant in ['no_exclusion','exclude_Utah','active_file_only','region_controls']:
            if variant=='active_file_only' and year==2024: continue # Already all active.
            g=a.loc[a.state_postal.ne('UT')].copy() if variant=='exclude_Utah' else a.loc[a.active_file.eq(1)].copy() if variant=='active_file_only' else a.copy()
            g=g.reset_index(drop=True); x=design(g,region=variant=='region_controls')
            z=x.copy() if variant=='no_exclusion' else x.assign(COVI=g.covi_final.to_numpy())
            print(f'{year}: robustness {variant}...',flush=True)
            fit=selection(g,x,z,starts=(0,.6),name=variant)
            res,_=fit.mean_prediction(g.turnout_matched.eq(0))
            rows.append({'year':year,'variant':variant,'n':len(g),'nonvoter_n':res['n'],'p_republican':res['estimate'],
                'r_ci_low':res['ci_low'],'r_ci_high':res['ci_high'],'rho':fit.diagnostics['rho'],
                'rho_ci_low':fit.diagnostics['rho_ci_low'],'rho_ci_high':fit.diagnostics['rho_ci_high'],
                'rho_p':fit.diagnostics['rho_wald_p'],'max_score':fit.diagnostics['normalized_max_score']})
            coeff.append(fit.table().assign(year=year))
            save(pd.DataFrame(rows),Path(tables)/'selection_robustness.csv')
    save(pd.concat(coeff,ignore_index=True),Path(tables)/'robustness_coefficients.csv')
    return pd.DataFrame(rows)

def partial_effects(fits,tables):
    # Weighted average probability contrasts among retained nonvoters. For the
    # baseline model only; age is a derivative and categories are discrete changes.
    rows=[]
    for year,models in fits.items():
        fit=models['baseline_state_FE']; d=fit.data; x=design(d,state=True).to_numpy(); non=d.turnout_matched.eq(0).to_numpy()
        w=fit.weights[non]; cols=fit.names
        def contrast(theta,var,k=None):
            if var=='age_10': return average(phi((x@theta)[non])*theta[cols.index(var)]/10,w)
            high=x.copy(); low=x.copy()
            for j,c in enumerate(cols):
                if c.startswith(var+'_'):
                    low[:,j]=0; high[:,j]=float(c==f'{var}_{k}')
            return average((ndtr(high@theta)-ndtr(low@theta))[non],w)
        for var,k,label in [('age_10',None,'Age +1 year (derivative)'),('education',5,'Four-year degree vs no HS'),
              ('education',6,'Postgraduate vs no HS'),('gender_group',2,'Female/woman vs male/man'),('race_h',2,'Black vs White'),
              ('race_h',3,'Hispanic vs White')]:
            fn=lambda v:contrast(v,var,k); estimate=fn(fit.theta); grad=jacobian(fn,fit.theta).ravel()
            se=np.sqrt(max(0,grad@fit.cov@grad)); crit=student_t.ppf(.975,fit.df)
            rows.append({'year':year,'contrast':label,'r_probability_change':estimate,'parameter_only_cluster_se':se,
               'ci_low':estimate-crit*se,'ci_high':estimate+crit*se,'target':'retained nonvoter covariate distribution, held fixed'})
    out=pd.DataFrame(rows); save(out,Path(tables)/'baseline_average_partial_effects.csv'); return out

def make_figures(prefs,states,thresholds,root):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    out=Path(root)/'results/figures'; out.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(figsize=(8,4.2)); colors=['#28528b','#7894b5','#ac3b36']
    labels=['Baseline: state controls','Probit: no state controls','Joint selection: COVI']
    for j,(name,label,color) in enumerate(zip(METHODS,labels,colors)):
        p=prefs[prefs.model.eq(name)].sort_values('year'); x=np.array([0,1])+(j-1)*.16
        y=100*p.p_allocated_democratic.to_numpy(); lo=100*p.allocated_d_ci_low.to_numpy(); hi=100*p.allocated_d_ci_high.to_numpy()
        ax.errorbar(x,y,yerr=np.vstack([y-lo,hi-y]),fmt='o',capsize=4,label=label,color=color)
    ax.axhline(50,color='gray',lw=.8,ls='--'); ax.set_xticks([0,1],['2016','2024']); ax.set_ylabel('Allocated Democratic preference (%)')
    ax.set_title('Retained nonvoters: estimates depend on selection assumptions',loc='left',fontweight='bold',pad=12)
    ax.legend(frameon=False,fontsize=9); ax.set_ylim(35,100)
    fig.text(.12,.015,'All non-Republican preferences allocated to Democrats; 95% state-cluster intervals.',fontsize=8)
    fig.tight_layout(rect=[0,.04,1,1]); fig.savefig(out/'national_preferences.png',dpi=180); plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(9,4.2),sharey=True)
    grid=np.linspace(.5,1,100)
    for ax,year in zip(axes,[2016,2024]):
        for state,color in zip(['MI','WI','PA'],['#28528b','#ac3b36','#657b46']):
            r=states[(states.year==year)&(states.state_postal==state)&(states.model=='baseline_state_FE')].iloc[0]
            margin=thresholds[(thresholds.year==year)&(thresholds.state_postal==state)&(thresholds.model=='baseline_state_FE')].rep_margin.iloc[0]
            net=grid*(1-r.p_republican)-r.p_republican; vals=np.where(net>0,margin/np.maximum(net,1e-15)/1000,np.nan)
            ax.plot(grid,vals,label=state,color=color)
        ax.set_title(str(year)); ax.set_xlabel('Fraction of non-Republicans allocated to Democrats'); ax.set_ylim(0,1000); ax.legend(frameon=False)
    axes[0].set_ylabel('Additional participants needed (thousands)')
    fig.suptitle('Baseline state thresholds rise as the allocation assumption weakens',x=.08,ha='left',fontweight='bold')
    fig.text(.08,.01,'Point estimates; existing ballots fixed. Gaps indicate no net Democratic gain; values above 1 million are clipped.',fontsize=8)
    fig.tight_layout(rect=[0,.05,1,.94]); fig.savefig(out/'state_threshold_sensitivity.png',dpi=180); plt.close(fig)


def write_manifest(root,checks):
    root=Path(root); files=['data/prepared/ces_covi_2016_2020_2024.csv.gz','data/analysis/prior_vote_2016_2024.csv.gz','data/analysis/official_blue_wall_returns.csv','code/selection_analysis.py','code/analysis_outputs.py']
    import scipy,nbformat,nbclient
    manifest={'python':sys.version,'platform':platform.platform(),'versions':{'numpy':np.__version__,'pandas':pd.__version__,'scipy':scipy.__version__,'nbformat':nbformat.__version__,'nbclient':nbclient.__version__},
       'input_and_code_sha256':{f:hashlib.sha256((root/f).read_bytes()).hexdigest() for f in files},'checks':checks,
       'inference':'state-cluster score sandwich; t(G-1); probability means include covariate-composition influence; cross-year changes clustered jointly by state',
       'scope':'Separate 2016 and 2024 cross sections; 2020 available but not fitted; no state population nonvoter totals assumed.'}
    (root/'results/run_manifest.json').write_text(json.dumps(manifest,indent=2,default=float)+'\n')
