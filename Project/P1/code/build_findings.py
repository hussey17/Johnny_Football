"""Build a concise two-page findings PDF and its Markdown source from saved results."""
from pathlib import Path
from html import escape
import json
import pandas as pd
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4

ROOT=Path(__file__).resolve().parents[1]; T=ROOT/'results/tables'; OUT=ROOT/'results'
p=pd.read_csv(T/'national_preferences.csv'); changes=pd.read_csv(T/'cross_year_contrasts.csv')
s=pd.read_csv(T/'blue_wall_preferences.csv'); th=pd.read_csv(T/'blue_wall_thresholds.csv')
tr=pd.read_csv(T/'prior_vote_transitions.csv'); robust=pd.read_csv(T/'selection_robustness.csv')
bench=pd.read_csv(T/'nonvoter_benchmarks.csv'); diag=json.loads((OUT/'model_diagnostics.json').read_text())

def row(year,model):return p[(p.year==year)&(p.model==model)].iloc[0]
def pct(v):return f'{100*v:.1f}%'
def estimate(year,model):
 r=row(year,model);return f'{pct(r.p_allocated_democratic)} ({100*r.allocated_d_ci_low:.1f}-{100*r.allocated_d_ci_high:.1f})'
def flow(year,status):return tr[(tr.year==year)&(tr.area=='National')&(tr.prior_group=='Prior Democrat')&(tr.current_status==status)].iloc[0].weighted_fraction_within_prior_group

def threshold(year,state,model,q=1):
 r=th[(th.year==year)&(th.state_postal==state)&(th.model==model)&(th.q_nonR_to_D==q)].iloc[0]
 return 'No net D gain' if pd.isna(r.minimum_additional_participants) else f'{int(r.minimum_additional_participants):,}'

basechange=changes[changes.model=='baseline_state_FE'].iloc[0]
r2016=next(r for r in diag if r['year']==2016 and r['model']=='heckprobit_COVI')
r2024=next(r for r in diag if r['year']==2024 and r['model']=='heckprobit_COVI')

national=[['Allocated Democratic preference','2016: estimate (95% CI)','2024: estimate (95% CI)'],
 ['Baseline, state controls',estimate(2016,'baseline_state_FE'),estimate(2024,'baseline_state_FE')],
 ['Joint binary selection, COVI',estimate(2016,'heckprobit_COVI'),estimate(2024,'heckprobit_COVI')]]
state_table=[['Year / state','Trump lead','Baseline: added voters','Selection: added voters','NV n / Kish n']]
for y in [2016,2024]:
 for st in ['MI','WI','PA']:
  a=th[(th.year==y)&(th.state_postal==st)&(th.model=='baseline_state_FE')&(th.q_nonR_to_D==1)].iloc[0]
  state_table.append([f'{y} / {st}',f'{int(a.rep_margin):,}',threshold(y,st,'baseline_state_FE'),threshold(y,st,'heckprobit_COVI'),f'{int(a.nonvoter_n)} / {a.kish_n:.1f}'])

key_points=[
 f'The baseline allocated Democratic share falls from {pct(row(2016,"baseline_state_FE").p_allocated_democratic)} to {pct(row(2024,"baseline_state_FE").p_allocated_democratic)}. The {100*basechange.r_change_2024_minus_2016:.2f} percentage-point decline is not significant at 5% (state-clustered p = {basechange.p_value:.3f}).',
 f'The selection model instead predicts {pct(row(2016,"heckprobit_COVI").p_allocated_democratic)} and {pct(row(2024,"heckprobit_COVI").p_allocated_democratic)}. Its cross-year change is also not significant (p = {changes[changes.model=="heckprobit_COVI"].iloc[0].p_value:.3f}); the 2016 interval is especially wide.',
 f'Among retained respondents reporting a previous Democratic vote, abstention versus a current Republican vote is {pct(flow(2016,"Abstained"))} versus {pct(flow(2016,"Republican"))} in 2016, and {pct(flow(2024,"Abstained"))} versus {pct(flow(2024,"Republican"))} in 2024. These are weighted within-sample descriptions, not national voter-flow totals.',
 'The data are more compatible with abstention exceeding defection among prior Democratic voters in 2016 than in 2024. They do not establish either mechanism as the cause of an election result.'
]
ident_points=[
 f'Error correlation: rho = {r2016["rho"]:.3f} in 2016 (p = {r2016["rho_wald_p"]:.3f}) and {r2024["rho"]:.3f} in 2024 (p = {r2024["rho_wald_p"]:.3f}). COVI turnout association: p = 0.001 in 2016; p = 0.128 in 2024. Exclusion validity remains assumed.',
 f'For 2024 nonvoters with a usable pre-election preference, {pct(bench[(bench.year==2024)&bench.benchmark.str.startswith("Pre")].iloc[0].stated_r_share)} stated Republican preference. On that same subset, baseline prediction is {pct(bench[(bench.year==2024)&bench.benchmark.str.startswith("Pre")].iloc[0].baseline_predicted_r_same_subset)} and selection prediction is {pct(bench[(bench.year==2024)&bench.benchmark.str.startswith("Pre")].iloc[0].heck_predicted_r_same_subset)}. The large selection adjustment conflicts with this survey benchmark.'
]
robust_points=[]
for y in [2016,2024]:
 vals=robust[robust.year==y]
 robust_points.append(f'{y}: alternative selection specifications imply allocated Democratic shares from {100*(1-vals.p_republican.max()):.1f}% to {100*(1-vals.p_republican.min()):.1f}% (remove COVI, exclude Utah, region controls; also active-only in 2016). Sample restrictions change the target group.')

page2_points=[
 'Michigan 2024 is almost evenly divided in the baseline: allocated Democratic preference is 49.9%. Adding participants with that point-estimated mix does not overturn its Republican lead. The selection model gives a different scenario; all three states cannot be claimed to flip from the baseline estimates.',
 'Allocation sensitivity is consequential. In Pennsylvania 2016, the baseline needs more than 83.0% of non-Republicans to vote Democratic just to produce a positive Democratic net gain. Allocating only 80% produces no positive net gain there, however many participants are added.',
 'If all three states flipped, standard state allocations would give Democrats 278 electoral votes in 2016 (before faithless electors) and 270 in 2024, holding every other state fixed. These are arithmetic scenarios, not estimated probabilities of winning.',
 'The 2024 state nonvoter samples have Kish effective sizes of only about 13 (MI), 6 (WI) and 8 (PA). No state population confidence intervals or aligned state nonvoter population totals are available here. Thresholds are point scenarios, not proof of feasible mobilization.'
]

md=['# Abstention, selection and the Blue Wall: findings','',
'**Scope:** CES + COVI; separately fitted 2016 and 2024 cross sections. Samples: 32,453 and 31,484, including 5,539 and 2,185 matched nonvoters.',
'','**Allocation assumption:** Every predicted non-Republican preference is assigned to Democrats in the headline scenario. The model outcome remains Republican versus all other candidates. This is not measured Democratic support.','',
'## National findings','', '| '+' | '.join(national[0])+' |','|---|---|---|']
md += ['| '+' | '.join(r)+' |' for r in national[1:]]
md += ['','Intervals are model-based, with state-clustered fitting and covariate-mix uncertainty.']
md += ['']+['- '+t for t in key_points+ident_points]
md += ['','## State participation thresholds','',
'Additional participants required to exceed the Republican margin, with all existing votes fixed and all non-Republican preferences allocated to Democrats. These are expected-net-vote calculations, not actual additional ballots observed.','',
'| '+' | '.join(state_table[0])+' |','|---|---|---|---|---|']
md += ['| '+' | '.join(r)+' |' for r in state_table[1:]]
md += ['']+['- '+t for t in page2_points]+['','## Robustness and reporting','']+['- '+t for t in robust_points]
md += ['', '**Presentation claim:** Predicted nonvoter preferences and required participation are sensitive to selection and allocation assumptions. Abstention is a plausible electoral scenario; its causal role in both Trump victories is not established.','',
'**Completed executions:** weighted baselines; joint binary selection; lecture two-step diagnostic; generated-regressor and state-cluster inference; cross-year tests; benchmarks; prior-vote/Sanders descriptions; state thresholds/allocation sensitivity; exclusion, region, Utah and active-status robustness; independent CDF/gradient/simulation validation.','',
'**Sources:** [CES/COVI provenance](../README.md); [FEC 2016 returns](https://www.fec.gov/resources/cms-content/documents/federalelections2016.pdf); [FEC 2024 returns](https://www.fec.gov/documents/5644/2024presgeresults.pdf); [2016 EC](https://www.archives.gov/electoral-college/2016); [2024 EC](https://www.archives.gov/electoral-college/2024). Full tables and diagnostics are saved alongside this document.']
(OUT/'findings_2016_2024.md').write_text('\n'.join(md)+'\n')

styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='TitleP1',fontName='Helvetica-Bold',fontSize=18,leading=21,textColor=colors.HexColor('#16395C'),spaceAfter=9))
styles.add(ParagraphStyle(name='Deck',fontName='Helvetica',fontSize=9,leading=12,textColor=colors.HexColor('#4C5C6A'),spaceAfter=9))
styles.add(ParagraphStyle(name='HeadP1',fontName='Helvetica-Bold',fontSize=11,leading=14,textColor=colors.HexColor('#16395C'),spaceBefore=10,spaceAfter=6))
styles.add(ParagraphStyle(name='BodyP1',fontName='Helvetica',fontSize=9.1,leading=12.3,spaceAfter=6))
styles.add(ParagraphStyle(name='SmallP1',fontName='Helvetica',fontSize=7.7,leading=10,spaceAfter=5,textColor=colors.HexColor('#49535C')))
styles.add(ParagraphStyle(name='CellP1',fontName='Helvetica',fontSize=8.2,leading=10))
styles.add(ParagraphStyle(name='CellHeadP1',fontName='Helvetica-Bold',fontSize=8.2,leading=10,textColor=colors.white))
story=[]
def para(txt,style='BodyP1'):return Paragraph(escape(txt),styles[style])
def add(txt,style='BodyP1'):story.append(para(txt,style))
def bullet(txt):story.append(Paragraph('&#8226; '+escape(txt),styles['BodyP1']))
def table(rows,widths):
 cells=[[para(v,'CellHeadP1' if i==0 else 'CellP1') for v in row] for i,row in enumerate(rows)]
 t=Table(cells,colWidths=widths,repeatRows=1,hAlign='LEFT')
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#16395C')),('VALIGN',(0,0),(-1,-1),'TOP'),
    ('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7),
    ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#F1F5F8'),colors.white]),('LINEBELOW',(0,-1),(-1,-1),.5,colors.HexColor('#D5DFE6'))]))
 story.append(t);story.append(Spacer(1,6))
add('Abstention, selection and the Blue Wall','TitleP1')
add('2016 and 2024 | Executed findings | ECON 438 Project 1','Deck')
add('What the data support','HeadP1')
for txt in key_points:bullet(txt)
add('Predicted preference among retained nonvoters','HeadP1')
table(national,[192,156,156])
add('Headline allocation assigns all predicted non-Republican preferences to Democrats. These are scenario shares, not measured Democratic support. Parentheses show 95% intervals in percent.','SmallP1')
add('Selection estimates need a cautious interpretation','HeadP1')
for txt in ident_points:bullet(txt)
add('Samples: 32,453 respondents in 2016 and 31,484 in 2024, including 5,539 and 2,185 matched nonvoters. Results target the retained matched, complete-case sample. Only turnout is voter-file validated; prior and current candidate choices are survey reports.','SmallP1')
add('Course-project conclusion: use abstention as a testable electoral scenario. The current results do not establish that Democratic abstention caused both Trump victories.','BodyP1')
story.append(PageBreak())
add('Battleground thresholds and robustness','TitleP1')
add('Additional participants needed under the all-non-Republicans-to-Democrats allocation','Deck')
table(state_table,[62,65,131,134,112])
add('For each added participant, expected Democratic net gain = 1 - 2pR. Minimum participants = floor(Republican lead / net gain) + 1 when net gain is positive. Existing ballots and preferences are held fixed. NV n is the retained nonvoter count; Kish n measures weight concentration, not model precision.','SmallP1')
for txt in page2_points:bullet(txt)
add('Robustness: the adjustment changes across specifications','HeadP1')
for txt in robust_points:bullet(txt)
add('What is completed - and what remains','HeadP1')
add('Completed: baseline and selection estimation; clustered uncertainty and cross-year tests; lecture two-step diagnostic; prior-vote transitions and benchmarks; state threshold and allocation grids; specification and matching checks; numerical validation.','BodyP1')
add('A population full-turnout claim still needs aligned state nonvoter totals and a defensible extrapolation beyond matched CES respondents. These data cannot identify Gaza, moderation or Sanders support as causes of abstention.','BodyP1')
add('Sources: CES/COVI releases and provenance in Project/P1/README.md; official returns: FEC Federal Elections 2016 and FEC 2024 Presidential General Election Results; EC allocations: National Archives. Full source URLs, tables, code and execution diagnostics accompany this PDF in the repository.','SmallP1')

def footer(c,doc):
 c.setStrokeColor(colors.HexColor('#D5DFE6'));c.line(42,35,A4[0]-42,35)
 c.setFont('Helvetica',7);c.setFillColor(colors.HexColor('#687581'))
 c.drawString(42,23,'CES + COVI | Scenario estimates, not causal election attribution')
 c.drawRightString(A4[0]-42,23,str(doc.page))
path=OUT/'findings_2016_2024.pdf'
doc=SimpleDocTemplate(str(path),pagesize=A4,leftMargin=42,rightMargin=42,topMargin=36,bottomMargin=47,
 title='Abstention, selection and the Blue Wall: executed findings',author='ECON 438 Project 1')
doc.build(story,onFirstPage=footer,onLaterPages=footer)
print(path)
