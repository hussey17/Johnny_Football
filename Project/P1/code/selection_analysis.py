"""Weighted probit/sample-selection estimators in Lecture 10 notation.

The lecture's continuous-outcome two-step is a teaching diagnostic here; the main
binary-outcome estimates use a bivariate probit likelihood. No nonvoter outcome is
filled in for estimation. Inference uses respondent-weighted scores summed by state.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json, hashlib, platform, sys, time
import numpy as np
import pandas as pd
from scipy.special import ndtr, log_ndtr, owens_t
from scipy.optimize import minimize
from scipy.stats import norm, t as student_t

PHI_CONST = 1 / np.sqrt(2 * np.pi)
CATS = ['education', 'income_group', 'pid7', 'ideology5', 'gender_group', 'race_h']
BASES = {'education':1,'income_group':1,'pid7':1,'ideology5':1,'gender_group':1,'race_h':1}
STATE_REGION = {s:i for i,ss in enumerate([
 'CT ME MA NH RI VT NJ NY PA',
 'IN IL MI OH WI IA KS MN MO NE ND SD',
 'DE FL GA MD NC SC VA DC WV AL KY MS TN AR LA OK TX',
 'AZ CO ID MT NV NM UT WY AK CA HI OR WA']) for s in ss.split()}

def phi(x): return PHI_CONST * np.exp(-np.asarray(x)**2 / 2)
def imr(a): return np.exp(-np.asarray(a)**2/2 - np.log(np.sqrt(2*np.pi)) - log_ndtr(a))
def average(x,w): return float(np.average(x,weights=w))
def kish(w): return float(np.sum(w)**2 / np.sum(np.asarray(w)**2)) if len(w) else 0.
def save(df,path):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    df.to_csv(path,index=False,float_format='%.10g')

def bvnorm(a,b,rho):
    """Deterministic bivariate normal CDF using Owen's T (no random integration).

    Handles exact zero indices separately. Checked against independent 1-D
    conditional-normal quadrature in numerical_checks().
    """
    a,b=np.broadcast_arrays(np.asarray(a,dtype=float),np.asarray(b,dtype=float))
    shape=a.shape; a=a.ravel(); b=b.ravel(); out=np.empty_like(a)
    r=float(rho); c=np.sqrt(1-r*r)
    az=np.abs(a)<1e-14; bz=np.abs(b)<1e-14
    both=az&bz; out[both]=.25+np.arcsin(r)/(2*np.pi)
    m=az&~bz; out[m]=.5*ndtr(b[m])-owens_t(b[m],-r/c)
    m=bz&~az; out[m]=.5*ndtr(a[m])-owens_t(a[m],-r/c)
    m=~az&~bz; h=a[m]; k=b[m]
    out[m]=.5*(ndtr(h)+ndtr(k))-owens_t(h,(k/h-r)/c)-owens_t(k,(h/k-r)/c)-(1-np.sign(h)*np.sign(k))/4
    # Tiny round-off outside Frechet bounds is numerical, not negative probability.
    lo=np.maximum(0,ndtr(a)+ndtr(b)-1); hi=np.minimum(ndtr(a),ndtr(b))
    return np.clip(out,lo,hi).reshape(shape)

def design(d,state=False,region=False):
    x=pd.DataFrame({'constant':np.ones(len(d)), 'age_10':(d.age.to_numpy()-50)/10},index=d.index)
    for c in CATS:
        for k in sorted(d[c].unique()):
            if k!=BASES[c]: x[f'{c}_{int(k)}']=(d[c]==k).astype(float)
    if state:
        for k in sorted(d.state_fips.unique())[1:]: x[f'state_{int(k):02d}']=(d.state_fips==k).astype(float)
    if region:
        r=d.state_postal.map(STATE_REGION)
        for k in [1,2,3]: x[f'region_{k}']=(r==k).astype(float)
    assert np.linalg.matrix_rank(x.to_numpy())==x.shape[1], 'Rank-deficient X'
    return x

def jacobian(fun,theta,step=2e-5):
    theta=np.asarray(theta); out=[]
    for j in range(len(theta)):
        h=step*max(1,abs(theta[j])); hi=theta.copy(); lo=theta.copy()
        hi[j]+=h; lo[j]-=h
        out.append((fun(hi)-fun(lo))/(2*h))
    return np.stack(out,axis=-1)

def cluster_sums(scores,groups):
    labels,inv=np.unique(groups,return_inverse=True)
    sums=np.zeros((len(labels),scores.shape[1])); np.add.at(sums,inv,scores)
    return labels,sums

@dataclass
class Fit:
    name: str
    theta: np.ndarray
    names: list
    score_function: object
    data: pd.DataFrame
    weights: np.ndarray
    predict_function: object
    diagnostics: dict
    def infer(self):
        scores=self.score_function(self.theta)
        H=-jacobian(lambda z:self.score_function(z).sum(axis=0),self.theta)
        H=(H+H.T)/2
        eig=np.linalg.eigvalsh(H)
        self.diagnostics.update(hessian_min_eigenvalue=float(eig.min()),hessian_condition=float(np.linalg.cond(H)))
        if eig.min()<=0: raise RuntimeError(f'{self.name}: non-positive likelihood/estimating-equation bread')
        self.bread=np.linalg.inv(H)
        self.cluster_labels,U=cluster_sums(scores,self.data.state_fips.to_numpy())
        self.cluster_scores=U; self.G=len(U); self.df=self.G-1
        self.correction=self.G/(self.G-1)*(len(self.data)-1)/(len(self.data)-len(self.theta))
        self.cov=self.correction*self.bread@U.T@U@self.bread.T
        self.cov=(self.cov+self.cov.T)/2
        return self
    def table(self):
        se=np.sqrt(np.maximum(0,np.diag(self.cov))); stat=self.theta/se
        crit=student_t.ppf(.975,self.df)
        return pd.DataFrame({'model':self.name,'term':self.names,'coefficient':self.theta,'cluster_se':se,
                             't':stat,'df':self.df,'p_value':2*student_t.sf(abs(stat),self.df),
                             'ci_low':self.theta-crit*se,'ci_high':self.theta+crit*se})
    def mean_prediction(self,mask,target='nonvoter'):
        mask=np.asarray(mask,dtype=bool); w=self.weights[mask]; denom=w.sum()
        fun=lambda z: average(self.predict_function(z,target)[mask],w)
        p=self.predict_function(self.theta,target); m=fun(self.theta)
        grad=jacobian(fun,self.theta).ravel()
        # Ratio-mean influence includes parameter fitting and observed covariate mix.
        composition=np.zeros(len(self.data)); composition[mask]=self.weights[mask]*(p[mask]-m)/denom
        _,C=cluster_sums(composition[:,None],self.data.state_fips.to_numpy())
        influence=self.cluster_scores@self.bread.T@grad+C[:,0]
        se=np.sqrt(self.correction*np.sum(influence**2)); crit=student_t.ppf(.975,self.df)
        # Fixed-covariate parameter-only SE is useful for small state targets; not
        # a CI for the state's unknown population composition or a state sample SE.
        se_fixed=np.sqrt(max(0,grad@self.cov@grad))
        return {'estimate':m,'cluster_se':se,'ci_low':m-crit*se,'ci_high':m+crit*se,
                'parameter_only_se':se_fixed,'n':int(mask.sum()),'kish_n':kish(w)}, dict(zip(self.cluster_labels,influence))

def probit(d,X,outcome,mask=None,name='probit'):
    n=len(d); y=np.asarray(outcome,dtype=float); X=np.asarray(X,dtype=float)
    mask=np.ones(n,dtype=bool) if mask is None else np.asarray(mask,dtype=bool)
    w=d.weight_adult_post.to_numpy(); w=w/w.mean(); ix=np.where(mask)[0]
    A=X[ix]; yy=y[ix]; ww=w[ix]
    sign=2*yy-1
    def score(z):
        a=sign*(A@z); v=sign*imr(a)
        out=np.zeros((n,X.shape[1])); out[ix]=(ww*v)[:,None]*A
        return out
    def objective(z):
        a=sign*(A@z)
        return -np.sum(ww*log_ndtr(a))/n,-score(z).sum(axis=0)/n
    init=np.zeros(X.shape[1]); init[0]=norm.ppf(np.clip(average(yy,ww),.01,.99))
    opt=minimize(objective,init,jac=True,method='BFGS',options={'gtol':2e-8,'maxiter':1000})
    sg=float(np.max(abs(score(opt.x).sum(axis=0)/n)))
    if sg>3e-6: raise RuntimeError(f'{name}: nonstationary fit: {sg}, {opt.message}')
    fit=Fit(name,opt.x,list(getattr(probit,'_names',range(X.shape[1]))),score,d,w,
            lambda z,target:ndtr(X@z),{'optimizer_success':bool(opt.success),'message':str(opt.message),
            'normalized_max_score':sg,'weighted_loglik':-float(opt.fun)*n,'n_selected':int(mask.sum())})
    return fit

def fit_probit(d,x,outcome,mask=None,name='probit'):
    probit._names=list(x.columns)
    return probit(d,x,outcome,mask,name).infer()

def selection(d,x,z,starts=(-.6,0,.6),name='heckprobit'):
    X=x.to_numpy(); Z=z.to_numpy(); S=d.turnout_matched.to_numpy().astype(int)
    Y=d.republican_any.to_numpy(); sel=S==1; sgn=2*Y[sel]-1
    w=d.weight_adult_post.to_numpy(); w=w/w.mean(); n=len(d); q=Z.shape[1]; p=X.shape[1]
    gamma=fit_probit(d,z,S,name=name+'_selection_start').theta
    beta=fit_probit(d,x,Y,sel,name=name+'_outcome_start').theta
    def probabilities(theta):
        a=Z@theta[:q]; b=X@theta[q:q+p]; r=np.tanh(theta[-1]); c=np.sqrt(1-r*r)
        aa=a[sel]; bb=sgn*b[sel]; rr=sgn*r
        # rho differs by the observed Y sign; avoid observationwise Python loops.
        pp=np.empty(len(aa))
        for t in [-1,1]:
            k=sgn==t; pp[k]=bvnorm(aa[k],bb[k],t*r)
        return a,b,r,c,pp
    def score(theta):
        a,b,r,c,pp=probabilities(theta)
        out=np.zeros((n,q+p+1)); out[~sel,:q]=-w[~sel,None]*imr(-a[~sel])[:,None]*Z[~sel]
        aa=a[sel]; bb=sgn*b[sel]; rr=sgn*r; prob=np.maximum(pp,1e-15)
        da=phi(aa)*ndtr((bb-rr*aa)/c)/prob
        db=sgn*phi(bb)*ndtr((aa-rr*bb)/c)/prob
        dr=sgn*np.exp(-(aa*aa-2*rr*aa*bb+bb*bb)/(2*c*c))/(2*np.pi*c)/prob*(1-r*r)
        out[sel,:q]=w[sel,None]*da[:,None]*Z[sel]
        out[sel,q:q+p]=w[sel,None]*db[:,None]*X[sel]
        out[sel,-1]=w[sel]*dr
        return out
    def objective(theta):
        a,b,r,c,pp=probabilities(theta)
        val=np.sum(w[~sel]*log_ndtr(-a[~sel]))+np.sum(w[sel]*np.log(np.maximum(pp,1e-15)))
        return -val/n,-score(theta).sum(axis=0)/n
    opts=[]; rows=[]
    for rho0 in starts:
        init=np.r_[gamma,beta,np.arctanh(rho0)]
        opt=minimize(objective,init,jac=True,method='BFGS',options={'gtol':3e-8,'maxiter':1200})
        sg=float(np.max(abs(score(opt.x).sum(axis=0)/n)))
        rows.append({'start_rho':rho0,'rho':float(np.tanh(opt.x[-1])),'negative_mean_loglik':float(opt.fun),
                     'normalized_max_score':sg,'optimizer_success':bool(opt.success),'message':str(opt.message)})
        opts.append(opt)
    valid=[o for o in opts if np.isfinite(o.fun) and np.max(abs(score(o.x).sum(axis=0)/n))<3e-6]
    if not valid: raise RuntimeError(f'{name}: no stationary solution: {rows}')
    opt=min(valid,key=lambda o:o.fun)
    if abs(np.tanh(opt.x[-1]))>.995: raise RuntimeError(f'{name}: rho is near boundary')
    def predict(theta,target):
        a=Z@theta[:q]; b=X@theta[q:q+p]; r=np.tanh(theta[-1])
        if target=='marginal': return ndtr(b)
        if target=='selected': return np.clip(bvnorm(a,b,r)/np.maximum(ndtr(a),1e-15),0,1)
        return np.clip(bvnorm(-a,b,-r)/np.maximum(ndtr(-a),1e-15),0,1)
    diagnostics={'weighted_loglik':-float(opt.fun)*n,'rho':float(np.tanh(opt.x[-1])),
       'normalized_max_score':float(np.max(abs(score(opt.x).sum(axis=0)/n))),
       'probability_floor_count':int(np.sum(probabilities(opt.x)[-1]<1e-15)),
       'multistart':rows,'q':q,'p':p}
    fit=Fit(name,opt.x,['gamma:'+a for a in z.columns]+['beta:'+a for a in x.columns]+['atanh_rho'],
            score,d,w,predict,diagnostics).infer()
    se_eta=np.sqrt(fit.cov[-1,-1]); crit=student_t.ppf(.975,fit.df)
    fit.diagnostics.update(rho_se_delta=float((1-np.tanh(opt.x[-1])**2)*se_eta),
        rho_ci_low=float(np.tanh(opt.x[-1]-crit*se_eta)),rho_ci_high=float(np.tanh(opt.x[-1]+crit*se_eta)),
        rho_wald_p=float(2*student_t.sf(abs(opt.x[-1]/se_eta),fit.df)))
    return fit

def lecture_two_step(d,x,z,first):
    """Literal weighted two-step LPM diagnostic, with stacked-equation inference.

    This does NOT turn the continuous-normal lecture model into a valid binary
    likelihood. Predictions and delta are pedagogical, not headline probabilities.
    """
    X=x.to_numpy(); Z=z.to_numpy(); S=d.turnout_matched.to_numpy().astype(int); sel=S==1
    Y=d.republican_any.to_numpy(); w=first.weights; q=Z.shape[1]
    lam=imr(Z@first.theta); A=np.column_stack([X,lam])
    b=np.linalg.lstsq(A[sel]*np.sqrt(w[sel,None]),Y[sel]*np.sqrt(w[sel]),rcond=None)[0]
    theta=np.r_[first.theta,b]
    def equations(v):
        g=v[:q]; bb=v[q:]; a=Z@g; l=imr(a); AA=np.column_stack([X,l])
        out=np.zeros((len(d),len(v))); out[:,:q]=first.score_function(g)
        residual=Y[sel]-AA[sel]@bb
        out[sel,q:]=w[sel,None]*residual[:,None]*AA[sel]
        return out
    B=-jacobian(lambda a:equations(a).sum(axis=0),theta)
    bread=np.linalg.inv(B)  # Asymmetric stacked Jacobian: DO NOT symmetrize it.
    labels,U=cluster_sums(equations(theta),d.state_fips.to_numpy()); G=len(labels)
    correction=G/(G-1)*(len(d)-1)/(len(d)-len(theta))
    cov=correction*bread@U.T@U@bread.T; se=np.sqrt(max(0,cov[-1,-1]))
    non=~sel; nv=X[non]@b[:-1]-b[-1]*imr(-(Z[non]@first.theta))
    return {'delta':b[-1],'delta_cluster_se':se,'delta_p':2*student_t.sf(abs(b[-1]/se),G-1),
        'nonvoter_linear_mean':average(nv,w[non]),'nonvoter_prediction_min':nv.min(),
        'nonvoter_prediction_max':nv.max(),'nonvoter_outside_0_1_fraction':float(np.mean((nv<0)|(nv>1))),
        'imr_r2_on_X':1-float(np.sum(w[sel]*(lam[sel]-X[sel]@np.linalg.lstsq(X[sel]*np.sqrt(w[sel,None]),lam[sel]*np.sqrt(w[sel]),rcond=None)[0])**2)/np.sum(w[sel]*(lam[sel]-average(lam[sel],w[sel]))**2))}

def numerical_checks():
    from scipy.integrate import quad
    rng=np.random.default_rng(438); errors=[]
    tests=[(0,0,.8),(0,1,-.8),(1,0,.8),(-3,-2,.9),(3,-4,-.9)]
    tests += [(float(a),float(b),float(r)) for a,b,r in zip(rng.normal(size=50)*2,rng.normal(size=50)*2,rng.uniform(-.95,.95,50))]
    for a,b,r in tests:
        expected=quad(lambda v:float(phi(v)*ndtr((b-r*v)/np.sqrt(1-r*r))),-np.inf,a,epsabs=1e-11)[0]
        errors.append(abs(float(bvnorm(a,b,r))-expected))
    assert max(errors)<2e-9, max(errors)
    return {'bivariate_cdf_max_absolute_error':max(errors),'reference':'independent 1D conditional-normal quadrature','test_points':len(tests)}

def fit_derivative_check(fit):
    n=len(fit.data); z=fit.theta.copy(); # Check a deliberately perturbed point, not just the optimum.
    z+=np.random.default_rng(438).normal(0,.02,len(z))
    # score Jacobian should be symmetric for genuine likelihood models.
    H=jacobian(lambda v:fit.score_function(v).sum(axis=0)/n,z)
    err=float(np.max(abs(H-H.T)))
    assert err<2e-5, (fit.name,err)
    return err
