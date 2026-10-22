"""Independent numerical and simulated-data checks for the custom estimator."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from scipy.special import log_ndtr
from scipy.optimize._numdiff import approx_derivative
from selection_analysis import selection, bvnorm, numerical_checks

def validate():
    result=numerical_checks()
    rng=np.random.default_rng(438); n=12000
    x=rng.normal(size=n); excluded=rng.normal(size=n)
    X=np.column_stack([np.ones(n),x]); Z=np.column_stack([X,excluded])
    beta=np.array([-.15,.65]); gamma=np.array([.25,.45,-.7]); rho=.45
    errors=rng.multivariate_normal([0,0],[[1,rho],[rho,1]],size=n)
    Y=(X@beta+errors[:,0]>0).astype(float); S=(Z@gamma+errors[:,1]>0).astype(int)
    d=pd.DataFrame({'turnout_matched':S,'republican_any':np.where(S,Y,np.nan),
        'weight_adult_post':np.ones(n),'state_fips':rng.integers(1,51,size=n)})
    xf=pd.DataFrame(X,columns=['constant','x']); zf=pd.DataFrame(Z,columns=['constant','x','excluded'])
    fit=selection(d,xf,zf,starts=(-.5,0,.5),name='simulation_validation')
    theta=fit.theta; q=3; p=2
    assert abs(fit.diagnostics['rho']-rho)<.12, fit.diagnostics
    assert np.max(abs(theta[q:q+p]-beta))<.15,theta
    # Separate scalar likelihood reconstruction; compare its finite-difference
    # derivative with the estimator's analytical weighted score away from optimum.
    def nll(t):
        a=Z@t[:q]; b=X@t[q:q+p]; r=np.tanh(t[-1]); v=S==1
        k1=v&(Y==1); k0=v&(Y==0)
        return -(log_ndtr(-a[~v]).sum()+np.log(bvnorm(a[k1],b[k1],r)).sum()+np.log(bvnorm(a[k0],-b[k0],-r)).sum())/n
    perturbed=theta+rng.normal(0,.03,len(theta))
    numeric=approx_derivative(lambda t:np.array([nll(t)]),perturbed,method='3-point').ravel()
    analytic=-fit.score_function(perturbed).sum(axis=0)/n
    error=float(np.max(abs(numeric-analytic)))
    assert error<1e-6,error
    result.update(simulated_n=n,simulated_true_rho=rho,simulated_fitted_rho=fit.diagnostics['rho'],
       simulated_true_beta=beta.tolist(),simulated_fitted_beta=theta[q:q+p].tolist(),
       likelihood_gradient_max_absolute_error=error,
       multistart_max_nll_difference=float(np.ptp([v['negative_mean_loglik'] for v in fit.diagnostics['multistart']])),
       simulated_model_max_score=fit.diagnostics['normalized_max_score'])
    return result

if __name__=='__main__':
    out=Path(__file__).resolve().parents[1]/'results/estimator_validation.json'
    result=validate();out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
