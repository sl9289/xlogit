# -*- coding: utf-8 -*-
import numpy as np
import pytest
from xlogit import MixedLogit
from xlogit import device
device.disable_gpu_acceleration()

# Setup data used for tests
X = np.array([[2, 1], [1, 3], [3, 1], [2, 4], [2, 1], [2, 4]])
y = np.array([0, 1, 0, 1, 0, 1])
ids = np.array([1, 1, 2, 2, 3, 3])
alts = np.array([1, 2, 1, 2, 1, 2])
panels = np.array([1, 1, 1, 1, 2, 2])
varnames = ["a", "b"]
randvars = {'a': 'n', 'b': 'n'}
N, J, K, R = 3, 2, 2, 5

MIN_COMP_ZERO = 1e-300
MAX_COMP_EXP = 700

def test__balance_panels():
    """
    Ensures that unbalanced panels are properly balanced when required
    """
    X_, y_ = X.reshape(N, J, K), y.reshape(N, J, 1)
    model = MixedLogit()
    X_, y_, panel_info = model._balance_panels(X_, y_, panels)

    assert np.array_equal(panel_info, np.array([[1, 1], [1, 0]]))
    assert X_.shape == (4, 2, 2)


def test_log_likelihood():
    """
    Computes the log-likelihood "by hand" for a simple example and ensures
    that the one returned by xlogit is the same
    """
    P = 1  # Without panel data
    betas = np.array([.1, .1, .1, .1])
    X_, y_ = X.reshape(N, P, J, K), y.reshape(N, P, J, 1)

    # Compute log likelihood using xlogit
    model = MixedLogit()
    model._rvidx,  model._rvdist = np.array([True, True]), np.array(['n', 'n'])
    draws = model._get_halton_draws(N, R, K)  # (N,Kr,R)
    panel_info = np.ones((N, P))
    obtained_loglik, _ = model._loglik_gradient(betas, X_, y_, panel_info,
                                                draws, None, None, R)

    # Compute expected log likelihood "by hand"
    Br = betas[None, [0, 1], None] + draws*betas[None, [2, 3], None]
    eXB = np.exp(np.einsum('npjk,nkr -> npjr', X_, Br))
    p = eXB/np.sum(eXB, axis=2, keepdims=True)
    expected_loglik = -np.sum(np.log(
        (y_*p).sum(axis=2).prod(axis=1).mean(axis=1)))

    assert pytest.approx(expected_loglik, obtained_loglik)


def test__transform_betas():
    """
    Check that betas are properly transformed to random draws

    """
    betas = np.array([.1, .1, .1, .1])

    # Compute log likelihood using xlogit
    model = MixedLogit()
    model._rvidx,  model._rvdist = np.array([True, True]), np.array(['n', 'n'])
    draws = model._get_halton_draws(N, R, K)  # (N,Kr,R)
    expected_betas = betas[None, [0, 1], None] + \
        draws*betas[None, [2, 3], None]
    _, obtained_betas = model._transform_betas(betas, draws)

    assert np.allclose(expected_betas, obtained_betas)


def test_fit():
    """
    Ensures the log-likelihood works for multiple iterations with the default
    initial coefficients. The value of -1.794 was computed by hand for
    comparison purposes
    """
    # There is no need to initialize a random seed as the halton draws produce
    # reproducible results
    model = MixedLogit()
    model.fit(X, y, varnames, alts, ids, randvars, n_draws=10, panels=panels,
              maxiter=0, verbose=0, halton=True)

    assert pytest.approx(model.loglikelihood, -1.79451632)
    
def test_predict():
    """
    Ensures that returned choice probabilities are consistent.
    """
    # There is no need to initialize a random seed as the halton draws produce
    # reproducible results
    P = 1  # Without panel data
    betas = np.array([.1, .1, .1, .1])
    X_ = X.reshape(N, P, J, K)
    
    model = MixedLogit()
    model._rvidx,  model._rvdist = np.array([True, True]), np.array(['n', 'n'])
    model.alternatives =  np.array([1, 2])
    model.coeff_ = betas
    model.randvars = randvars
    model._isvars, model._asvars, model._varnames = [], varnames, varnames
    model._fit_intercept = False
    model.coeff_names = np.array(["a", "b", "sd.a", "sd.b"])
    
    #model.fit(X, y, varnames, alts, ids, randvars, verbose=0, halton=True)
    y_pred, proba, freq = model.predict(X, varnames, alts, ids,
                                          n_draws=R, return_proba=True,
                                          return_freq=True)
    
    # Compute choice probabilities by hand
    draws = model._get_halton_draws(N, R, K)  # (N,Kr,R)
    Br = betas[None, [0, 1], None] + draws*betas[None, [2, 3], None]
    V = np.einsum('npjk,nkr -> npjr', X_, Br)
    V[V > MAX_COMP_EXP] = MAX_COMP_EXP
    eV = np.exp(V)
    e_proba = eV/np.sum(eV, axis=2, keepdims=True)
    expec_proba = e_proba.prod(axis=1).mean(axis=-1) 
    expec_ypred = model.alternatives[np.argmax(expec_proba, axis=1)]
    alt_list, counts = np.unique(expec_ypred, return_counts=True)
    expec_freq = dict(zip(list(alt_list),
                          list(np.round(counts/np.sum(counts), 3))))
    

    assert np.array_equal(expec_ypred, y_pred) 
    assert expec_freq == freq


def test_validate_inputs():
    """
    Covers potential mistakes in parameters of the fit method that xlogit
    should be able to identify
    """
    model = MixedLogit()
    with pytest.raises(ValueError):  # wrong distribution
        model.fit(X, y, varnames=varnames, alts=alts, ids=ids, n_draws=10,
                  maxiter=0, verbose=0, halton=True, randvars={'a': 'fake'})

    with pytest.raises(ValueError):  # wrong var name
        model.fit(X, y, varnames=varnames, alts=alts, ids=ids, n_draws=10,
                  maxiter=0, verbose=0, halton=True, randvars={'fake': 'n'})


def test_gpu_not_available():
    """
    Ensures that xlogit detects that GPU is not available based on CuPy's
    installation status

    """
    assert not MixedLogit.check_if_gpu_available()
