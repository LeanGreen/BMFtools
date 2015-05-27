# cython: c_string_type=str, c_string_encoding=ascii
# cython: profile=True, cdivision=True, cdivision_warnings=True


import logging
import operator
from operator import add as oadd
from operator import sub as osub
from operator import div as odiv
from operator import mul as omul
import math
from math import pow as mpow
from math import sqrt as msqrt
from utilBMF.ErrorHandling import ThisIsMadness

import cython
import numpy as np
from numpy import array as nparray
from numpy import mean as nmean
from numpy import sum as nsum
from scipy.stats import binom
from scipy.misc import comb
from statsmodels.stats import proportion
from cytoolz import memoize
pconfint = proportion.proportion_confint


cimport numpy as np

"""
Contains probabilistic tools for accurately identifying somatic mutations.
"""

defaultPValue = 0.05

# PROTOCOLS is a list of lowered strings.
PROTOCOLS = ["ffpe", "amplicon", "cf", "other"]


@memoize
@cython.locals(DOC=cython.int, pVal=np.longdouble_t,
               AC=cython.int)
def ConfidenceIntervalAAF(AC, DOC, pVal=defaultPValue,
                          method="agresti_coull"):
    """
    Returns the confidence interval for an AAF given an observed AC
    and DOC.
    """
    if(method == "scipy"):
        return (nparray(binom.interval(1 - pVal, DOC,
                                       AC * 1. / DOC)) / DOC).tolist()
    try:
        return pconfint(AC, DOC, alpha=pVal, method=method)
    except NotImplementedError:
        raise ThisIsMadness("Confidence interval method `%s` not " % method +
                            "implemented! Check the docs for statsmodels."
                            "stats.proportion.")


@cython.returns(np.ndarray)
def ConfidenceIntervalAI(cython.int Allele1,
                         cython.int Allele2, np.longdouble_t pVal=defaultPValue,
                         cython.str method="agresti_coull"):
    """
    Returns the confidence interval for an allelic imbalance
    given counts for Allele1 and Allele2, where those are the most common
    alleles at a given position.
    """
    cdef np.longdouble_t ratio
    if(Allele1 < Allele2):
        ratio = 1. * Allele1 / Allele2
    else:
        ratio = 1. * Allele2 / Allele1
    if(method == "scipy"):
        return nparray(binom.interval(1 - pVal,
                                      Allele1 + Allele2, ratio),
                       dtype=np.longdouble)
    try:
        return nparray(pconfint(Allele1, Allele1 + Allele2,
                                alpha=pVal, method=method),
                       dtype=np.longdouble)
    except NotImplementedError:
        raise ThisIsMadness("Confidence interval method `%s` not" % method +
                            " implemented! Check the docs for statsmodels."
                            "stats.proportion.")


@cython.returns(tuple)
def MakeAICall(cython.int Allele1,
               cython.int Allele2,
               np.longdouble_t pVal=defaultPValue,
               cython.str method="agresti_coull"):
    """
    Gets confidence bounds, returns a call, a "minor" allele frequency,
    an observed allelic imbalance ratio (as defined by more common allele
    over less common allele), and a confidence interval
    """
    cdef np.longdouble_t minorAF
    cdef cython.bint call
    cdef np.longdouble_t allelicImbalanceRatio
    confInt = ConfidenceIntervalAI(Allele1, Allele2, pVal=defaultPValue,
                                   method=method)
    minorAF = nmean(confInt, dtype=np.longdouble)
    allelicImbalanceRatio = 1. * minorAF / (1 - minorAF)
    call = (minorAF < confInt[0] or minorAF > confInt[1])
    return call, allelicImbalanceRatio, confInt


@memoize
@cython.locals(n=cython.int, p=np.longdouble_t,
               pVal=np.longdouble_t)
@cython.returns(cython.int)
def GetCeiling(n, p=0.0, pVal=defaultPValue):
    """
    Returns the maximum fraction of events per sample with a p value of pVal,
    n samplings, and an assumed probability of p per sampling.
    """
    return binom.interval(1 - pVal, n, p)[1]


@memoize
@cython.locals(n=np.longdouble_t)
@cython.returns(np.longdouble_t)
def StirlingsApprox(n):
    """
    Stirling's Approximation is a continuous function which approximates
    factorials extremely accurately.
    n! ~ Sqrt(2*Pi*n) * (n / e)^n
    """
    return omul(mpow(odiv(n, np.e), n), msqrt(reduce(omul, [2, np.pi, n], 1)))


@memoize
@cython.locals(n=np.longdouble_t, k=np.longdouble_t)
@cython.returns(np.longdouble_t)
def StirlingsFact(n, k):
    """
    Stirling's Approximation is a continuous function which approximates
    factorials extremely accurately.
    n! ~ Sqrt(2*Pi*n) * (n / e)^n
    """
    return StirlingsApprox(n) / StirlingsApprox(k) / StirlingsApprox(
        osub(n, k))


@memoize
@cython.locals(p=np.longdouble_t, k=cython.int, n=cython.int)
@cython.returns(np.longdouble_t)
def SamplingFrac(n, p=0., k=1):
    """
    Given a fixed probability of an event with n samplings, returns
    the probability moment (IE, unnormalized) that precisely "k" events
    have occurred.
    If you want speed, use SamplingFrac_, which uses Stirling's Approximation.
    """
    assert 0. < p < 1.
    return reduce(omul, [mpow(osub(1, p), osub(n, k)),
                  mpow(p, k), comb(n + 1, k)], 1)


@memoize
@cython.locals(p=np.longdouble_t, k=cython.int, n=cython.int)
@cython.returns(np.longdouble_t)
def SamplingFrac_(n, p=0., k=1):
    """
    Given a fixed probability of an event with n samplings, returns
    the probability moment (IE, unnormalized) that precisely "k" events
    Uses Stirling's Approximation for speed.
    """
    assert 0. < p < 1.
    return reduce(omul, [mpow(osub(1, p), osub(n, k)), mpow(p, k),
                  StirlingsFact(n + 1, k)], 1)


@memoize
@cython.locals(p=np.longdouble_t, k=cython.int, n=cython.int)
@cython.returns(np.ndarray)
def GetUnscaledProbs(n, p=0.):
    """
    Calculates the probability moments for k in xrange(n + 1).
    This uses a factorial, primarily for
    speed, but it's also definitely good enough.
    """
    return nparray([SamplingFrac(n, p=p, k=k) for k in xrange(n + 1)],
                   dtype=np.longdouble)


@memoize
@cython.locals(p=np.longdouble_t, k=cython.int, n=cython.int)
@cython.returns(np.ndarray)
def GetUnscaledProbs_(n, p=0.):
    """
    Calculates the probability moments for k in xrange(n + 1).
    This uses Stirling's approximation instead of factorial, primarily for
    speed, but it's also definitely good enough.
    """
    return nparray([SamplingFrac_(n, p=p, k=k) for k in xrange(n + 1)],
                   dtype=np.longdouble)


@memoize
@cython.locals(p=np.longdouble_t, k=cython.int, n=cython.int)
@cython.returns(np.longdouble_t)
def PartitionFunction(n, p=0.1):
    return nsum(GetUnscaledProbs(n, p=p), 0)


@memoize
@cython.locals(p=np.longdouble_t, k=cython.int, n=cython.int)
@cython.returns(np.longdouble_t)
def PartitionFunction_(n, p=0.1):
    return nsum(GetUnscaledProbs_(n, p=p), 0)


@memoize
@cython.locals(p=np.longdouble_t, n=cython.int, k=cython.int)
@cython.returns(np.ndarray)
def SamplingProbDist(n, p=0.):
    """
    Given a fixed probability of an event with n samplings, returns
    the probability that precisely "K" events have occurred.
    """
    assert 0. < p < 1.
    cdef np.ndarray[np.longdouble_t, ndim = 1] ProbDist
    cdef np.ndarray[np.longdouble_t, ndim = 1] UnscaledProbs
    UnscaledProbs = GetUnscaledProbs(n, p=p)
    PartitionFn = nsum(UnscaledProbs, 0)
    ProbDist = UnscaledProbs / PartitionFn
    return ProbDist


@memoize
@cython.locals(p=np.longdouble_t, n=cython.int, k=cython.int)
@cython.returns(np.ndarray)
def SamplingProbDist_(n, p=0.):
    """
    Given a fixed probability of an event with n samplings, returns
    the probability that precisely "K" events have occurred.
    """
    assert 0. < p < 1.
    cdef np.ndarray[np.longdouble_t, ndim = 1] ProbDist
    cdef np.ndarray[np.longdouble_t, ndim = 1] UnscaledProbs
    UnscaledProbs = GetUnscaledProbs_(n, p=p)
    PartitionFn = nsum(UnscaledProbs, 0)
    ProbDist = UnscaledProbs / PartitionFn
    return ProbDist


@memoize
@cython.locals(p=np.longdouble_t, n=cython.int, k=cython.int,
               PartitionFn=np.longdouble_t)
def SamplingProbMoments(n, p=0.):
    """
    Given a fixed probability of an event with n samplings, returns
    the probability that precisely "K" events have occurred.
    """
    assert 0. < p < 1.
    cdef np.ndarray[np.longdouble_t, ndim = 1] UnscaledProbs
    UnscaledProbs = GetUnscaledProbs(n, p=p)
    PartitionFn = nsum(UnscaledProbs, 0, dtype=np.longdouble)
    return UnscaledProbs, PartitionFn


@memoize
@cython.locals(p=np.longdouble_t, n=cython.int, k=cython.int,
               PartitionFn=np.longdouble_t)
def SamplingProbMoments_(n, p=0.):
    """
    Given a fixed probability of an event with n samplings, returns
    the probability that precisely "K" events have occurred.
    """
    assert 0. < p < 1.
    cdef np.ndarray[np.longdouble_t, ndim = 1] UnscaledProbs
    UnscaledProbs = GetUnscaledProbs_(n, p=p)
    PartitionFn = nsum(UnscaledProbs, 0, dtype=np.longdouble)
    return UnscaledProbs, PartitionFn
