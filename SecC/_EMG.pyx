# cython: boundscheck=False, wraparound=False
from itertools import groupby
from matplotlib.backends.backend_pdf import PdfPages
from MawCluster.BCFastq import GetDescTagValue
from sys import maxint
from utilBMF.ErrorHandling import ThisIsMadness, ImproperArgumentError
from utilBMF.HTSUtils import pFastqProxy, pFastqFile, getBS, RevCmp, TrimExt
import argparse
import matplotlib.pyplot as plt
import numpy as np
import operator
import pysam
import cython
# cimport pysam.calignmentfile
# ctypedef pysam.calignedsegment.AlignedSegment AlignedSegment_t


cdef errorTracker(AlignedSegment_t read,
                  ndarray[int64_t, ndim=3, mode="c"] readErr,
                  ndarray[int64_t, ndim=3, mode="c"] readObs):
    cdef int32_t index, start, end
    cdef cystr context
    cdef char base
    cdef int8_t phred_index
    cdef int16_t context_index
    cdef char * seq
    seq = read.query_sequence
    for index in xrange(read.qstart, read.qend):
        if(index < 1):
            # Don't sweat it
            continue
        context = read.query_sequence[index - 1: index + 1]
        context_index = CONTEXT_TO_ARRAY_POS(<char *>context)
        if(context_index < 0):
            # Don't sweat it - there was an N in the context
            continue
        phred_index = read.query_qualities[index] - 2
        readObs[index][phred_index][context_index] += 1
        base = <char>seq[index]
        # Note if/elses with same predicate --> switch
        if base == 61:
            continue
        elif base == 78:
            continue
        else:
            readErr[index][phred_index][context_index] += 1


def GetErrorArrays(args):

    cdef size_t rLen, index, read_index, qual_index, context_index
    cdef int64_t fam_range, qcfail, rc, fmc, FM
    cdef double_t read1mean, read2mean
    cdef ndarray[int64_t, ndim=3, mode="c"] read1error, read1obs
    cdef ndarray[int64_t, ndim=3, mode="c"] read2error, read2obs
    cdef ndarray[double_t, ndim=3, mode="c"] read1frac, read2frac
    cdef ndarray[double_t, ndim=1, mode="c"] read1cyclemeans, read2cyclemeans
    cdef ndarray[double_t, ndim=1, mode="c"] read1qualmeans, read2qualmeans
    cdef ndarray[double_t, ndim=1, mode="c"] read1contextmeans, read2contextmeans
    cdef AlignedSegment_t read
    cdef AlignmentFile_t mdBam

    from cPickle import dump
    from sys import stderr

    if(args.pickle_path is None):
        pickle_path = TrimExt(args.mdBam) + ".errorprofile.pyd"
    else:
        pickle_path = args.pickle_path
    if(args.table_prefix is None):
        table_prefix = TrimExt(args.mdBam)
    else:
        table_prefix = args.table_prefix
    table_prefix += ".out."

    rLen = pysam.AlignmentFile(args.mdBam).next().inferred_length
    read1error = np.zeros([rLen, 39, 16], dtype=np.int64)
    read1obs = np.zeros([rLen, 39, 16], dtype=np.int64)
    read2error = np.zeros([rLen, 39, 16], dtype=np.int64)
    read2obs = np.zeros([rLen, 39, 16], dtype=np.int64)

    qcfail = 0
    fmc = 0
    rc = 0

    minFM, maxFM = args.minFM, args.maxFM
    mdBam = pysam.AlignmentFile(args.mdBam, "rb")
    for read in mdBam:
        '''
        First if is equivalent to the following:
            if(read.is_secondary or read.is_supplementary or
               read.is_unmapped or read.is_qcfail):
        Second if is equivalent to not (read.is_proper_pair)
        '''
        if read.flag & 2820:
            qcfail += 1
            continue
        elif not (read.flag & 2):
            qcfail += 1
            continue
        FM = read.opt("FM")
        if(FM < minFM or FM > maxFM):
                fmc += 1
                continue
        if read.flag & 64:
            errorTracker(read, read1error, read1obs)
        elif read.flag & 128:
            errorTracker(read, read2error, read2obs)
        else:
            pass
        rc += 1
    stderr.write("Family Size Range: %i-%i\n" % (minFM, maxFM))
    stderr.write("Reads Analyzed: %i\n" % (rc))
    stderr.write("Reads QC Filtered: %i\n" % (qcfail))
    stderr.write("Reads Family Size Filtered: %i\n" % (fmc))
    read1frac = read1error / read1obs
    read2frac = read2error / read2obs
    with open(pickle_path, "wb") as pickleHandle:
        dump((read1frac, read2frac), pickleHandle)
    read1mean = np.mean(read1frac)
    read2mean = np.mean(read2frac)
    read1cyclemeans = np.mean(np.mean(read1frac, axis=2, dtype=np.float64),
                              axis=1, dtype=np.float64)
    read2cyclemeans = np.mean(np.mean(read2frac, axis=2, dtype=np.float64),
                              axis=1, dtype=np.float64)
    read1qualmeans = np.mean(np.mean(read1frac, axis=0, dtype=np.float64),
                              axis=1, dtype=np.float64)
    read2qualmeans = np.mean(np.mean(read2frac, axis=0, dtype=np.float64),
                              axis=1, dtype=np.float64)
    read1contextmeans = np.mean(np.mean(read1frac, axis=0, dtype=np.float64),
                             axis=0, dtype=np.float64)
    read2contextmeans = np.mean(np.mean(read2frac, axis=0, dtype=np.float64),
                             axis=0, dtype=np.float64)
    return {"r1cm": read1cyclemeans, "r2cm": read2cyclemeans,
            "r1qm": read1qualmeans, "r2qm": read2qualmeans,
            "r1conm": read1contextmeans, "r2conm": read2contextmeans,
            "r1f": read1frac, "r2f": read2frac, "r1m": read1mean,
            "r2m": read2mean, "r1e": read1error, "r2e": read2error}


def calculateError(args):

    cdef dict data
    from sys import stderr

    if(args.table_prefix is None):
        table_prefix = TrimExt(args.mdBam)
    else:
        table_prefix = args.table_prefix
    table_prefix += ".out."

    FullTableHandle = open(table_prefix + "full.tsv", "w")
    CycleTableHandle = open(table_prefix + "cycle.tsv", "w")
    PhredTableHandle = open(table_prefix + "phred.tsv", "w")
    ContextTableHandle = open(table_prefix + "context.tsv", "w")

    data = GetErrorArrays(args)
    '''
    CycleTableHandle.write("#Cycle\tRead1 mean error\tRead2 mean error\tread count\n")
    for index in xrange(1, rLen):
        CycleTableHandle.write(
            "%i\t%f\t%f\t%i\n" % (index+1, [index],
                                  read2cyclemeans[index], rc))
    CycleTableHandle.close()
    PhredTableHandle.write("#Quality Score\tread1 mean error\tread2 mean error\n")
    for index in xrange(39):
        PhredTableHandle.write(
            "%i\t%f\t%f\n" % (index+2, read1qualmeans[index],
                              read2qualmeans[index]))
    PhredTableHandle.close()
    ContextTableHandle.write("#Context ID\tRead 1 mean error\tRead 2 mean error\n")
    for index in xrange(16):
        ContextTableHandle.write(
            "%i\t%f\t%f\n" % (index, read1contextmeans[index],
                              read2contextmeans[index]))
    ContextTableHandle.close()
    FullTableHandle.write(
        "#Cycle\tQuality Score\tContext ID\tRead "
        "1 mean error\tRead 2 mean error\n")
    for read_index in xrange(rLen):
        for qual_index in xrange(39):
            for context_index in xrange(16):
                FullTableHandle.write(
                    "%i\t%i\t%i\t%f\t%f\n" % (read_index + 1, qual_index + 2, context_index,
                                              read1frac[read_index][qual_index][context_index],
                                              read2frac[read_index][qual_index][context_index]))
    FullTableHandle.close()
    '''
    return 0


@cython.boundscheck(False)
@cython.wraparound(False)
cdef inline bint TEST_ERROR(char character) nogil:
    if character == 61:
        return 0
    elif character == 78:
        return 0
    else:
        return 1


cpdef errorFinder(AlignedSegment_t read,
                  ndarray[int64_t, ndim=1] readErr,
                  ndarray[int64_t, ndim=1] readObs):
    cdef size_t read_index
    cdef char base
    cdef char * seq
    cdef size_t offset_index
    cdef bint err

    seq = read.query_sequence
    for read_index in xrange(read.qstart, read.qend):
        readObs[read_index] += 1
        err = TEST_ERROR(<char>seq[read_index])
        if not err:
            # case "=" or "N"
            return
        else:
            readErr[read_index] += 1
            return


@cython.returns(dict)
def cCycleError(args):
    cdef size_t rLen, minFM, maxFM, qc, rc, fmc, index, FM
    cdef double_t read1mean, read2mean
    cdef ndarray[int64_t, ndim=1, mode="c"] read1error, read1obs
    cdef ndarray[int64_t, ndim=1, mode="c"] read2error, read2obs
    cdef ndarray[double_t, ndim=1, mode="c"] read1prop, read2prop
    cdef AlignedSegment_t read
    cdef AlignmentFile_t mdBam
    from sys import stdout, stderr
    if(args.family_size is None):
        minFM = 0
        maxFM = maxint
    else:
        minFM, maxFM = map(int(args.family_size.split(",")))
    rLen = pysam.AlignmentFile(args.mdBam).next().inferred_length
    read1error = np.zeros(rLen, dtype=np.int64)
    read1obs = np.zeros(rLen, dtype=np.int64)
    read2error = np.zeros(rLen, dtype=np.int64)
    read2obs = np.zeros(rLen, dtype=np.int64)
    qc = 0
    fmc = 0
    rc = 0
    mdBam = pysam.AlignmentFile(args.mdBam)
    for read in mdBam:
        if read.flag & 2820 or ~ read.flag & 2:
            qc += 1
            continue
        FM = read.opt("FM")
        if(FM < minFM or FM > maxFM):
                fmc += 1
                continue
        if read.flag & 64:
            errorFinder(read, read1error, read1obs)
        elif read.flag & 128:
            errorFinder(read, read2error, read2obs)
        else:
            pass
        rc += 1
    stdout.write("Family Size Range: %i-%i\n" % (minFM,
                                                     maxFM))
    stdout.write("Reads Analyzed: %i\n" % (rc))
    stdout.write("Reads QC Filtered: %i\n" % (qc))
    if args.family_size is not None:
        stdout.write("Reads Family Size Filtered: %i\n" % (fmc))
    read1prop = np.divide(read1error.astype(np.double), read1obs)
    read2prop = np.divide(read2error.astype(np.double), read2obs)
    read1mean = np.mean(read1prop)
    read2mean = np.mean(read2prop)
    stdout.write("cycle\tread1\tread2\tread count\n")
    for index in xrange(rLen):
        stdout.write("%i\t%f\t%f\t%i\n" % (index + 1,
                                           read1prop[index],
                                           read2prop[index], rc))
    stdout.write("%i\t%f\t%f\t%i\n" % (maxFM, read1mean, read2mean,
                                       rc))
    if args.cycleheat is not None:
        cycleHeater(read1prop, read2prop, rLen)
    return {"r1e": read1error, "r1o": read1obs, "r2e": read2error,
            "r2o": read2obs, "r1p": read1prop, "r2p": read2prop,
            "r1m": read1mean, "r2m": read2mean}


def cycleHeater(read1prop, read2prop, rLen):
    fig, ax = plt.subplots()
    data = np.array([read1prop, read2prop])
    heatmap = ax.pcolor(data, cmap=plt.cm.Reds)
    colorb = plt.colorbar(heatmap)
    plt.show()