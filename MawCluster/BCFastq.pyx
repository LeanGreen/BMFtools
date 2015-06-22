# cython: c_string_type=str, c_string_encoding=ascii
from __future__ import division

"""
Contains various utilities for working with barcoded fastq files.
"""

import logging
import os
import shlex
import subprocess
from subprocess import check_output
from copy import copy as ccopy
import gzip
import sys
import collections
import time
import cStringIO
import operator
import uuid
from operator import (add as oadd, le as ole, ge as oge, div as odiv,
                      mul as omul, add as oadd, attrgetter as oag,
                      methodcaller as mc)
from subprocess import check_call
from array import array

import cython
import numpy as np
from numpy import (sum as nsum, amax as npamax, argmax as npargmax,
                   multiply as nmul, subtract as nsub, any as npany,
                   vstack as npvstack, greater as ngreater, less as nless,
                   divide as ndiv, char as npchar)
import pysam
from itertools import groupby

from utilBMF.HTSUtils import (SliceFastqProxy,
                              printlog as pl,
                              pFastqProxy, TrimExt, pFastqFile, getBS,
                              hamming_cousins)
from utilBMF import HTSUtils
from utilBMF.ErrorHandling import ThisIsMadness as Tim, FunctionCallException
try:
    from re2 import compile as regex_compile
except ImportError:
    pl("Note: re2 import failed. Fell back to re.", level=logging.DEBUG)
    from re import compile as regex_compile


def SortAndMarkFastqsCommand(Fq1, Fq2, IndexFq):
    return ("pr -mts <(cat %s | paste - - - -) <(cat %s | " % (Fq1, Fq2) +
            "paste - - - -) <(cat %s | paste - - - -) | awk" % IndexFq +
            "'BEGIN {{FS=OFS=\"\t\"}};{{BS=\"|BS=\"$10\"\"substr($2,"
            "0,2)\"\"substr($6,0,2); print $1\"\"BS, $2, $3, $4, $5\"\"BS, "
            "$6, $7, $8}}' | sort -t\"|\" -k2,2 -k1,1 | tr '\t' '\n'")


@cython.locals(checks=int,
               parallel=cython.bint, sortMem=cystr)
def BarcodeSortBoth(cystr inFq1, cystr inFq2,
                    cystr sortMem="6G", cython.bint parallel=False):
    cdef cystr outFq1, outFq2, highMemStr
    if(parallel is False):
        pl("Parallel barcode sorting is set to false. Performing serially.")
        return BarcodeSort(inFq1), BarcodeSort(inFq2)
    outFq1 = '.'.join(inFq1.split('.')[0:-1] + ["BS", "fastq"])
    outFq2 = '.'.join(inFq2.split('.')[0:-1] + ["BS", "fastq"])
    pl("Sorting {} and {} by barcode sequence.".format(inFq1, inFq2))
    highMemStr = "-S " + sortMem
    BSstring1 = getBarcodeSortStr(inFq1, outFastq=outFq1,
                                  mem=sortMem)
    BSstring2 = getBarcodeSortStr(inFq2, outFastq=outFq2,
                                  mem=sortMem)
    pl("Background calling barcode sorting "
       "for read 1. Command: {}".format(BSstring1))
    BSCall1 = subprocess.Popen(BSstring1, stderr=None, shell=True,
                               stdout=None, stdin=None, close_fds=True)
    check_call(BSstring2, shell=True)
    BSCall1.poll()
    checks = 0
    if(BSCall1.returncode == 0):
        return outFq1, outFq2
    elif(BSCall1.returncode is not None):
        raise subprocess.CalledProcessError("Barcode sort failed for read 1."
                                            " Call: {}".format(BSstring1))
    else:
        while checks < 300:
            checks = 0
            time.sleep(1)
            BSCall1.poll()
            if(BSCall1.returncode == 0):
                return outFq1, outFq2
            else:
                checks += 1
        raise subprocess.CalledProcessError("Barcode first sort didn't work, "
                                            "it seems - took more than 5 minu"
                                            "tes longer than the second barco"
                                            "de sort.")


@cython.locals(highMem=cython.bint)
def BarcodeSort(cystr inFastq, cystr outFastq="default",
                cystr mem="6G"):
    cdef cystr BSstring
    pl("Sorting {} by barcode sequence.".format(inFastq))
    BSstring = getBarcodeSortStr(inFastq, outFastq=outFastq, mem=mem)
    check_call(BSstring, shell=True)
    pl("Barcode Sort shell call: {}".format(BSstring))
    if(outFastq == "default"):  # Added for compatibility with getBSstr
        outFastq = '.'.join(inFastq.split('.')[0:-1] + ["BS", "fastq"])
    return outFastq


@cython.returns(cystr)
def getBarcodeSortStr(inFastq, outFastq="default", mem=""):
    if(mem != ""):
        mem = " -S " + mem
    if(outFastq == "default"):
        outFastq = '.'.join(inFastq.split('.')[0:-1] + ["BS", "fastq"])
    if(inFastq.endswith(".gz")):
        return ("zcat %s | paste - - - - | sort -t'|' -k3,3 -k1,1" % inFastq +
                " %s | tr '\t' '\n' > %s" % (mem, outFastq))
    else:
        return ("cat %s | paste - - - - | sort -t'|' -k3,3 -k1,1" % inFastq +
                " %s | tr '\t' '\n' > %s" % (mem, outFastq))


cpdef cystr QualArr2QualStr(ndarray[np_int32_t, ndim=1] qualArr):
    """
    cpdef wrapper for QualArr2QualStr

    Compared speed for a typed list comprehension against that for a map.
    Results:
    In [6]: %timeit QualArr2PVString(c)
    100000 loops, best of 3: 6.49 us per loop

    In [7]: %timeit QualArr2PVStringMap(c)
    100000 loops, best of 3: 8.9 us per loop

    """
    return cQualArr2QualStr(qualArr)


cdef cystr cQualArr2QualStr(ndarray[np_int32_t, ndim=1] qualArr):
    cdef np_int32_t tmpInt
    return "".join([ph2chrInline(tmpInt) for tmpInt in qualArr])


cpdef cystr QualArr2PVString(ndarray[np_int32_t, ndim=1] qualArr):
    return cQualArr2PVString(qualArr)


cdef cystr cQualArr2FAString(ndarray[np_int32_t, ndim=1] qualArr):
    cdef np_int32_t tmpInt
    return "|FA=%s" % (",".join([int2strInline(tmpInt) for
                                 tmpInt in qualArr]))


cdef cystr cQualArr2PVString(ndarray[np_int32_t, ndim=1] qualArr):
    cdef np_int32_t tmpInt = np.max(qualArr)
    if(tmpInt < 9001):
        return "|PV=%s" % (",".join([int2strInline(tmpInt) for
                                     tmpInt in qualArr]))
    else:
        return "|PV=%s" % ",".join(qualArr.astype(int))

cpdef cystr pCompareFqRecsFast(list R, cystr name=None):
    return cCompareFqRecsFast(R, name)


@cython.boundscheck(False)
@cython.wraparound(False)
cdef cystr cCompareFqRecsFast(list R,
                              cystr name=None):
    """
    TODO: Unit test for this function.
    Also, consider making a cpdef version!
    Calculates the most likely nucleotide
    at each position and returns the joined record string.
    """
    cdef int lenR, ND, lenSeq, tmpInt
    cdef cython.bint Success
    cdef cystr PVString, TagString, newSeq
    cdef cystr consolidatedFqStr
    # cdef char tmpChar
    cdef ndarray[np_int32_t, ndim=2] quals, qualA, qualC, qualG
    cdef ndarray[np_int32_t, ndim=2] qualT, qualAllSum
    cdef ndarray[np_int32_t, ndim=1] qualAFlat, qualCFlat, qualGFlat, FA
    cdef ndarray[np_int32_t, ndim=1] phredQuals, qualTFlat
    # cdef ndarray[char, ndim=1, mode = "c"] newSeq
    cdef pFastqProxy_t rec
    cdef char tmpChar
    if(name is None):
        name = R[0].name
    lenR = len(R)
    lenSeq = len(R[0].sequence)
    if lenR == 1:
        phredQuals = np.array(R[0].getQualArray(), dtype=np.int32)
        TagString = ("|FM=1|ND=0|FA=" + "1" + "".join([",1"] * (lenSeq - 1)) +
                     cQualArr2PVString(phredQuals))
        return "@%s %s%s\n%s\n+\n%s\n" % (name, R[0].comment,
                                          TagString, R[0].sequence,
                                          R[0].quality)
    Success = True
    stackArrays = tuple([np.char.array(rec.sequence, itemsize=1) for rec in R])
    seqArray = npvstack(stackArrays)

    quals = np.array([rec.getQualArray() for
                      rec in R], dtype=np.int32)
    # Qualities of 2 are placeholders and mean nothing in Illumina sequencing.
    # Let's turn them into what they should be: nothing.
    # quals[quals < 3] = 0
    # --- Actually ---,  it seems that the q scores of 2 are higher quality
    # than Illumina expects them to be, so let's keep them. They should also
    # ideally be recalibrated.
    qualA = ccopy(quals)
    qualC = ccopy(quals)
    qualG = ccopy(quals)
    qualT = ccopy(quals)
    qualA[seqArray != "A"] = 0
    qualAFlat = nsum(qualA, 0, dtype=np.int32)
    qualC[seqArray != "C"] = 0
    qualCFlat = nsum(qualC, 0, dtype=np.int32)
    qualG[seqArray != "G"] = 0
    qualGFlat = nsum(qualG, 0, dtype=np.int32)
    qualT[seqArray != "T"] = 0
    qualTFlat = nsum(qualT, 0, dtype=np.int32)
    qualAllSum = npvstack(
        [qualAFlat, qualCFlat, qualGFlat, qualTFlat])
    newSeq = np.char.array([Num2Nuc(tmpChar) for tmpChar in npargmax(qualAllSum, 0)]).tostring()
    phredQuals = npamax(qualAllSum, 0)  # Avoid calculating twice.
    FA = np.array([sum([rec.sequence[i] == newSeq[i] for
                        rec in R]) for
                  i in xrange(lenSeq)], dtype=np.int32)
    '''
    FA = np.array([sum([rec.sequence[i] == chrACGNTInline(newSeq[i]) for
                        rec in R]) for
                  i in xrange(lenSeq)], dtype=np.int32)
    '''
    # Sums the quality score for all bases, then scales it by the number of
    # agreed bases. There could be more informative ways to do so, but
    # this is primarily a placeholder.
    ND = lenR * lenSeq - nsum(FA)
    # newSeq[phredQuals == 0] = "N"
    phredQuals[phredQuals < 0] = 0
    PVString = cQualArr2PVString(phredQuals)
    phredQualsStr = cQualArr2QualStr(phredQuals)
    FAString = cQualArr2FAString(FA)
    TagString = "|FM=%s|ND=%s"  % (lenR, ND) +  FAString + PVString
    '''
    consolidatedFqStr = "@%s %s%s\n%s\n+\n%s\n" % (name, R[0].comment,
                                                   TagString,
                                                   newSeq,
                                                   phredQualsStr)
    In [67]: %timeit omgzwtf = "@%s %s%s\n%s\n+\n%s\n" % (name, b.comment,
                                                          TagString,
                                                          newSeq,
                                                          phredQualsStr)
    1000000 loops, best of 3: 585 ns per loop
    In [68]: %timeit omgzwtf = ("@" + name + " " + b.comment + TagString +
                                "\n" + newSeq + "\n+\n%s\n" % phredQualsStr)
    1000000 loops, best of 3: 512 ns per loop
    '''
    consolidatedFqStr = ("@" + name + " " + R[0].comment + TagString + "\n" +
                         newSeq + "\n+\n%s\n" % phredQualsStr)
    if(not Success):
        return consolidatedFqStr.replace("Pass", "Fail")
    return consolidatedFqStr


@cython.returns(cystr)
def CutadaptPaired(cystr fq1, cystr fq2,
                   p3Seq="default", p5Seq="default",
                   int overlapLen=6, cython.bint makeCall=True):
    """
    Returns a string which can be called for running cutadapt v.1.7.1
    for paired-end reads in a single call.
    """
    cdef cystr outfq1
    cdef cystr outfq2
    cdef cystr commandStr
    outfq1 = ".".join(fq1.split('.')[0:-1] + ["cutadapt", "fastq"])
    outfq2 = ".".join(fq2.split('.')[0:-1] + ["cutadapt", "fastq"])
    if(p3Seq == "default"):
        raise Tim("3-prime primer sequence required for cutadapt!")
    if(p5Seq == "default"):
        pl("No 5' sequence provided for cutadapt. Only trimming 3'.")
        commandStr = ("cutadapt --mask-adapter --match-read-wildcards"
                      "-a {} -o {} -p {} -O {} {} {}".format(p3Seq,
                                                             outfq1,
                                                             outfq2,
                                                             overlapLen,
                                                             fq1, fq2))
    else:
        commandStr = ("cutadapt --mask-adapter --match-read-wildcards -a "
                      "{} -g {} -o {} -p".format(p3Seq, p5Seq, outfq1) +
                      " {} -O {} {} {}".format(outfq2, overlapLen, fq1, fq2))
    pl("Cutadapt command string: {}".format(commandStr))
    if(makeCall):
        subprocess.check_call(shlex.split(commandStr))
        return outfq1, outfq2
    return commandStr


@cython.locals(overlapLen=int)
@cython.returns(cystr)
def CutadaptString(fq, p3Seq="default", p5Seq="default", overlapLen=6):
    """
    Returns a string which can be called for running cutadapt v.1.7.1.
    """
    outfq = ".".join(fq.split('.')[0:-1] + ["cutadapt", "fastq"])
    if(p3Seq == "default"):
        raise Tim("3-prime primer sequence required for cutadapt!")
    if(p5Seq == "default"):
        pl("No 5' sequence provided for cutadapt. Only trimming 3'.")
        commandStr = "cutadapt --mask-adapter {} -a {} -o {} -O {} {}".format(
            "--match-read-wildcards", p3Seq, outfq, overlapLen, fq)
    else:
        commandStr = ("cutadapt --mask-adapter --match-read-wildcards -a "
                      "{} -g {} -o {} -O {} {}".format(p3Seq, p5Seq, outfq,
                                                       overlapLen, fq))
    pl("Cutadapt command string: {}".format(commandStr))
    return commandStr, outfq


@cython.locals(overlapLen=int)
def CutadaptSingle(fq, p3Seq="default", p5Seq="default", overlapLen=6):
    """
    Calls cutadapt to remove adapter sequence at either end of the reads.
    Written for v1.7.1 and single-end calls.
    """
    commandStr, outfq = CutadaptString(fq, p3Seq=p3Seq, p5Seq=p5Seq,
                                       overlapLen=overlapLen)
    subprocess.check_call(commandStr)
    return outfq


@cython.locals(overlapLap=int, numChecks=int)
def CallCutadaptBoth(fq1, fq2, p3Seq="default", p5Seq="default", overlapLen=6):
    fq1Str, outfq1 = CutadaptString(fq1, p3Seq=p3Seq, p5Seq=p5Seq,
                                    overlapLen=overlapLen)
    fq2Str, outfq2 = CutadaptString(fq2, p3Seq=p3Seq, p5Seq=p5Seq,
                                    overlapLen=overlapLen)
    pl("About to open a Popen instance for read 2. Command: {}".format(fq2Str))
    fq2Popen = subprocess.Popen(fq2Str, shell=True, stdin=None, stderr=None,
                                stdout=None, close_fds=True)
    pl("Cutadapt running in the background for read 2. Now calling for read "
       "1: {}".format(fq1Str))
    subprocess.check_call(fq1Str, shell=True)
    numChecks = 0
    while True:
        if(numChecks >= 300):
            raise subprocess.CalledProcessError(
                "Cutadapt took more than 5 minutes longer for read 2 than rea"
                "d 1. Did something go wrong?")
        if fq2Popen.poll() == 0:
            return outfq1, outfq2
        elif(fq2Popen.poll() is None):
            pl("Checking if cutadapt for read 2 is finished. Seconds elapsed ("
               "approximate): {}".format(numChecks))
            numChecks += 1
            time.sleep(1)
            continue
        else:
            raise subprocess.CalledProcessError(
                fq2Popen.returncode, fq2Str, "Cutadapt failed for read 2!")


@cython.locals(useGzip=cython.bint, hpLimit=int)
def FastqPairedShading(fq1, fq2, indexFq="default",
                       useGzip=False, SetSize=10,
                       int head=2):
    """
    TODO: Unit test for this function.
    Tags fastqs with barcodes from an index fastq.
    """
    #  C declarations
    cdef pFastqProxy_t read1
    cdef pFastqProxy_t read2
    cdef pysam.cfaidx.FastqProxy indexRead
    cdef cystr outfq1
    cdef cystr outfq2
    pl("Now beginning fastq marking: Pass/Fail and Barcode")
    if(indexFq == "default"):
        raise ValueError("For an i5/i7 index ")
    outfq1 = TrimExt(fq1).replace(".fastq",
                                  "").split("/")[-1] + ".shaded.fastq"
    outfq2 = TrimExt(fq2).replace(".fastq",
                                  "").split("/")[-1] + ".shaded.fastq"
    if(useGzip):
        outfq1 += ".gz"
        outfq2 += ".gz"
    pl("Output fastqs: {}, {}.".format(outfq1, outfq2))
    inFq1 = pFastqFile(fq1)
    inFq2 = pFastqFile(fq2)
    ifn2 = inFq2.next
    if useGzip is False:
        outFqHandle1 = open(outfq1, "w")
        outFqHandle2 = open(outfq2, "w")
        f1 = cStringIO.StringIO()
        f2 = cStringIO.StringIO()
    else:
        outFqHandle1 = open(outfq1, "wb")
        outFqHandle2 = open(outfq2, "wb")
        cString1 = cStringIO.StringIO()
        cString2 = cStringIO.StringIO()
        f1 = gzip.GzipFile(fileobj=cString1, mode="w")
        f2 = gzip.GzipFile(fileobj=cString2, mode="w")
    inIndex = pysam.FastqFile(indexFq)
    hpLimit = len(inIndex.next().sequence) * 5 // 6
    inIndex = pysam.FastqFile(indexFq)
    ifin = inIndex.next
    outFqSet1 = []
    outFqSet2 = []
    numWritten = 0
    ofh1w = outFqHandle1.write
    ofh2w = outFqHandle2.write
    for read1 in inFq1:
        if(numWritten >= SetSize):
            if(not useGzip):
                ofh1w(f1.getvalue())
                ofh2w(f2.getvalue())
                f1 = cStringIO.StringIO()
                f2 = cStringIO.StringIO()
            else:
                f1.flush()
                f2.flush()
                ofh1w(cString1.getvalue())
                ofh2w(cString2.getvalue())
                cString1 = cStringIO.StringIO()
                cString2 = cStringIO.StringIO()
                f1 = gzip.GzipFile(fileobj=cString1, mode="w")
                f2 = gzip.GzipFile(fileobj=cString2, mode="w")
            numWritten = 0
        read2 = ifn2()
        indexRead = ifin()
        tempBar = (read1.sequence[:head] + indexRead.sequence +
                   read2.sequence[:head])
        read1.comment = cMakeTagComment(tempBar, read1, hpLimit)
        read2.comment = cMakeTagComment(tempBar, read2, hpLimit)
        f1.write(str(read1))
        f2.write(str(read2))
        numWritten += 1
    if(useGzip is False):
        ofh1w(f1.getvalue())
        ofh2w(f2.getvalue())
    else:
        f1.close()
        f2.close()
        ofh1w(cString1.getvalue())
        ofh2w(cString2.getvalue())
    outFqHandle1.close()
    outFqHandle2.close()
    return outfq1, outfq2


def FastqSingleShading(fq,
                       indexFq="default",
                       outfq="default",
                       cython.bint gzip=False,
                       int head=0):
    """
    Unit test done. Marks a single fastq with its index fq string.
    """
    cdef pysam.cfaidx.FastqProxy read1
    cdef pFastqProxy_t pRead1, pIndexRead
    cdef pysam.cfaidx.FastqFile inFq1, inIndex
    pl("Now beginning fastq marking: Pass/Fail and Barcode")
    if(indexFq == "default"):
        raise ValueError("For an i5/i7 index ")
    if(outfq == "default"):
        outfq = '.'.join(fq.split('.')[0:-1]) + '.shaded.fastq'
    inFq1 = pysam.FastqFile(fq)
    outFqHandle1 = open(outfq, "w")
    inIndex = pysam.FastqFile(indexFq)
    for read1 in inFq1:
        pIndexRead = pFastqProxy.fromFastqProxy(inIndex.next())
        pRead1 = pFastqProxy.fromFastqProxy(read1)
        if("N" in pRead1.pIndexRead.sequence):
            read1.comment += "|FP=IndexFail|BS=%" % (read1.sequence[:head] +
                                                     pIndexRead.sequence)
            outFqHandle1.write(str(read1))
        else:
            read1.comment += "|FP=IndexPass|BS=%s" % (read1.sequence[:head] +
                                                      pIndexRead.sequence)
            outFqHandle1.write(str(read1))
    outFqHandle1.close()
    if(gzip):
        check_call(['gzip', fq], shell=False)
    return


@cython.returns(cystr)
def GetDescTagValue(readDesc, tag="default"):
    """
    Gets the value associated with a given tag.
    of read description (string), then the seq
    attribute is used instead of the description.
    """
    if(tag == "default"):
        raise ValueError("A tag must be specified!")
    try:
        return GetDescriptionTagDict(readDesc)[tag]
    except KeyError:
        # pl("Tag {} is not available in the description.".format(tag))
        # pl("Description: {}".format(readDesc))
        raise KeyError("Invalid tag: %s" % tag)


def GetDescriptionTagDict(readDesc):
    """Returns a set of key/value pairs in a dictionary for """
    tagSetEntries = [i.strip().split("=") for i in readDesc.split("|")][1:]
    tagDict = {}
    try:
        for pair in tagSetEntries:
            tagDict[pair[0]] = pair[1].split(' ')[0]
    except IndexError:
        pl("A value is stored with the| tag which doesn't contain an =.")
        pl("tagSetEntries: {}".format(tagSetEntries))
        raise IndexError("Check that fastq description meets specifications.")
    # pl("Repr of tagDict is {}".format(tagDict))
    except TypeError:
        pl("tagSetEntries: {}".format(tagSetEntries))
        raise Tim("YOU HAVE NO CHANCE TO SURVIVE MAKE YOUR TIME")
    return tagDict


def pairedFastqConsolidate(fq1, fq2, float stringency=0.9,
                           int SetSize=100, bint parallel=True):
    """
    TODO: Unit test for this function.
    Also, it would be nice to do a groupby() that separates read 1 and read
    2 records so that it's more pythonic, but that's a hassle.
    """
    cdef cystr outFq1, outFq2
    cdef cython.int checks
    pl("Now running pairedFastqConsolidate on {} and {}.".format(fq1, fq2))
    pl("(What that really means is that I'm running "
       "singleFastqConsolidate twice")
    if(not parallel):
        outFq1 = singleFastqConsolidate(fq1, stringency=stringency,
                                        SetSize=SetSize)
        outFq2 = singleFastqConsolidate(fq2, stringency=stringency,
                                        SetSize=SetSize)
    else:
        # Make background process command string
        cStr = ("python -c 'from MawCluster.BCFastq import singleFastqConsoli"
                "date;singleFastqConsolidate(\"%s\", stringency=" % fq2 +
                "%s, SetSize=%s);import sys;sys.exit(0)'" % (stringency,
                                                             SetSize))
        # Submit
        PFC_Call = subprocess.Popen(cStr, stderr=None, shell=True,
                                    stdout=None, stdin=None, close_fds=True)
        # Run foreground job on other read
        outFq1 = singleFastqConsolidate(fq1, stringency=stringency,
                                        SetSize=SetSize)
        checks = 0
        # Have the other process wait until it's finished.
        while PFC_Call.poll() is None and checks < 3600:
            time.sleep(1)
            checks += 1
        if(PFC_Call.returncode == 0):
            return outFq1, TrimExt(fq2) + ".cons.fastq"
        elif(PFC_Call.returncode is not None):
            raise FunctionCallException(
                cStr, ("Background singleFastqConsolidate "
                       "returned non-zero exit status."),
                shell=True)
        else:
            raise FunctionCallException(
                cStr, ("Background singleFastqConsolidate took more than an"
                       "hour longer than the other read fastq. Giving up!"),
                shell=True)
    return outFq1, outFq2


def singleFastqConsolidate(cystr fq, float stringency=0.9,
                           int SetSize=100,
                           cython.bint onlyNumpy=True,
                           cython.bint skipFails=False):
    cdef cystr outFq, bc4fq, ffq
    cdef pFastqFile_t inFq
    cdef list StringList
    cdef int numProc, TotalCount, MergedCount
    cdef list pFqPrxList
    outFq = TrimExt(fq) + ".cons.fastq"
    pl("Now running singleFastqConsolidate on {}.".format(fq))
    inFq = pFastqFile(fq)
    outputHandle = open(outFq, 'w')
    StringList = []
    workingBarcode = ""
    numProc = 0
    TotalCount = 0
    ohw = outputHandle.write
    sla = StringList.append
    for bc4fq, fqRecGen in groupby(inFq, key=getBS):
        pFqPrxList = list(fqRecGen)
        ffq = cCompareFqRecsFast(pFqPrxList, bc4fq)
        sla(ffq)
        numProc += 1
        TotalCount += len(pFqPrxList)
        MergedCount += 1
        if (numProc == SetSize):
            ohw("".join(StringList))
            StringList = []
            sla = StringList.append
            numProc = 0
            continue
    ohw("".join(StringList))
    outputHandle.flush()
    inFq.close()
    outputHandle.close()
    if("SampleMetrics" in globals()):
        globals()['SampleMetrics']['TotalReadCount'] = TotalCount
        globals()['SampleMetrics']['MergedReadCount'] = MergedCount
    print("Consolidation a success for inFq: %s!" % fq)
    return outFq


def TrimHomingSingle(
        fq,
        cystr homing=None,
        cystr trimfq=None,
        int bcLen=12,
        cystr trim_err=None,
        int start_trim=1):
    """
    TODO: Unit test for this function.
    """
    cdef pysam.cfaidx.FastqProxy read
    cdef int HomingLen, TotalTrim
    pl("TrimHoming: \"{}\" from {}.".format(homing, fq))
    if(trim_err is None):
        trim_err = TrimExt(fq) + '.err.fastq'
    if(trimfq is None):
        trimfq = TrimExt(fq) + ".trim.fastq"
    trimHandle = open(trimfq, "w")
    errHandle = open(trim_err, "w")
    InFastq = pysam.FastqFile(fq)
    HomingLen = len(homing)
    TotalTrim = HomingLen + bcLen + start_trim
    tw = trimHandle.write
    ew = errHandle.write
    for read in InFastq:
        homingLoc = read.sequence[bcLen:bcLen + HomingLen]
        if homing not in homingLoc:
            pl("Homing sequence not in tag. Writing to error file.",
               level=logging.DEBUG)
            ew(str(pFastqProxy.fromFastqProxy(read)))
            continue
        tw(SliceFastqProxy(read, firstBase=TotalTrim,
                              addString="|BS=" + read.sequence[0:bcLen]))
    trimHandle.close()
    errHandle.close()
    return trimfq


def TrimHomingPaired(inFq1, inFq2, int bcLen=12,
                     cystr homing=None, cystr trimfq1=None,
                     cystr trimfq2=None, int start_trim=1):
    """
    TODO: Unit test for this function.
    """
    cdef pysam.cfaidx.FastqProxy read1, read2
    cdef int HomingLen, TotalTrim
    pl("Getting inline barcodes for files %s, %s with homing %s." % (inFq1,
                                                                     inFq2,
                                                                     homing))
    trim_err = TrimExt(inFq1) + '.err.fastq'
    if(trimfq1 is None):
        trimfq1 = TrimExt(inFq1) + ".trim.fastq"
    if(trimfq2 is None):
        trimfq2 = TrimExt(inFq2) + ".trim.fastq"
    trimHandle1 = open(trimfq1, "w")
    trimHandle2 = open(trimfq2, "w")
    errHandle = open(trim_err, "w")
    InFastq1 = pysam.FastqFile(inFq1)
    InFastq2 = pysam.FastqFile(inFq2)
    fqNext = InFastq1.next
    HomingLen = len(homing)
    TotalTrim = HomingLen + bcLen + start_trim
    pl("Homing length: %s. TotalTrim: %s" % (HomingLen, TotalTrim))
    tw1 = trimHandle1.write
    tw2 = trimHandle2.write
    ew = errHandle.write
    for read1 in InFastq1:
        read2 = fqNext()
        if homing not in read1.sequence[bcLen:bcLen + HomingLen]:
            ew(str(pFastqProxy.fromFastqProxy(read1)))
            ew(str(pFastqProxy.fromFastqProxy(read2)))
            continue
        if homing not in read2.sequence[bcLen:bcLen + HomingLen]:
            ew(str(pFastqProxy.fromFastqProxy(read1)))
            ew(str(pFastqProxy.fromFastqProxy(read2)))
            continue
        barcode = read1.sequence[0:bcLen] + read2.sequence[0:bcLen]
        tw1(SliceFastqProxy(read1, firstBase=TotalTrim,
                               addString="|BS=%s" % barcode))
        tw2(SliceFastqProxy(read2, firstBase=TotalTrim,
                               addString="|BS=%s" % barcode))
    trimHandle1.close()
    trimHandle2.close()
    errHandle.close()
    return trimfq1, trimfq2


@cython.locals(asDict=cython.bint)
@cython.returns(cystr)
def CalcFamUtils(inFq, asDict=False):
    """
    Uses bioawk to get summary statistics on a fastq file quickly.
    """
    commandStr = ("bioawk -c fastx {{n=split($comment,array," ");k=array[4];n="
                  "split(k,array,\"=\"); len += 1; sum += array[2]; if(array[2"
                  "] == 1) {{singletons += 1}};if(array[2] >= 2) {{realFams +="
                  " 1; readFmSum += array[2]}}}};END {{print \"MFS=\"sum /len"
                  "\";NumRealFams=\"realFams\";ReadFamSum=\"readFmSum/realFams"
                  "\";NumSingletons=\"singletons}}' %s" % inFq)
    strOut = subprocess.check_output(shlex.split(commandStr)).strip()
    if(asDict):
        return dict([i.split("=") for i in strOut.split(";")])
    return strOut


@cython.returns(tuple)
def BarcodeRescueDicts(cystr indexFqPath, int minFam=10, int n=1,
                       cystr tmpFile=None):
    """Returns two dictionaries.
    1. rescueHistDict maps random barcodes to the central barcode they
    should have been.
    2. TrueFamDict's keys are all "True family" barcodes with the value set
    to None. It's just O(1) to check for a hashmap key's membership vs. O(n)
    for checking a list's membership.
    """
    cdef list histList
    cdef dict histDict, rescueHistDict, TrueFamDict
    cdef cystr h, y, x
    cdef int y1
    cStr = ("zcat %s | paste - - - - | cut -f2 | sort | " % indexFqPath +
            "uniq -c | awk 'BEGIN {{OFS=\"\t\"}};{{print $1, $2}}'")
    pl("Calling cStr: %s" % cStr)
    if tmpFile is None:
        histList = [tuple(tmpStr.split("\t")) for tmpStr in
                    check_output(cStr,
                                 shell=True).split("\n") if tmpStr != ""]
    else:
        check_call(cStr + " > %s" % tmpFile, shell=True)
        histList = [tuple(tmpStr.split("\t")) for tmpStr in
                    open(tmpFile, "r").read().split("\n") if tmpStr != ""]
    histDict = {y: int(x) for x, y in histList}
    TrueFamDict = {x: None for x, y1 in histDict.iteritems() if y1 >= minFam}
    if(len(TrueFamDict) == 0):
        rescueHistDict = {}
    else:
        rescueHistDict = {h: y for y in TrueFamDict.iterkeys() for
                          h in hamming_cousins(y, n=n)}
    if(tmpFile is not None):
        check_call(["rm", tmpFile])
    return rescueHistDict, TrueFamDict


def RescueShadingWrapper(cystr inFq1, cystr inFq2, cystr indexFq=None,
                         int minFam=10, int mm=1, int head=2):
    cdef dict rescueDict, TrueFamDict
    cdef cystr tmpFilename
    tmpFilename = str(uuid.uuid4().get_hex()[0:8]) + ".tmp"
    pl("Calling RescueShadingWrapper.")
    if(indexFq is None):
        raise Tim("Index Fq must be set to rescue barcodes.")
    pl("About to do a rescue step for barcodes for %s and %s." % (inFq1,
                                                                  inFq2))
    rescueDict, TrueFamDict = BarcodeRescueDicts(indexFq, n=mm, minFam=minFam,
                                                 tmpFile=tmpFilename)
    pl("Dictionaries filled!")
    return RescuePairedFastqShading(inFq1, inFq2, indexFq,
                                    rescueDict=rescueDict,
                                    TrueFamDict=TrueFamDict, head=head)


@cython.returns(tuple)
def RescuePairedFastqShading(cystr inFq1, cystr inFq2,
                             cystr indexFq,
                             dict rescueDict=None, dict TrueFamDict=None,
                             cystr outFq1=None, cystr outFq2=None,
                             int head=2):
    """Rescues orphans from a barcode rescue.
    Works under the assumption that the number of random nucleotides used
    as molecular barcodes is sufficiently high that any read "family" with
    size below the minFam used to create the rescueDict object can be safely
    considered to be a sequencer error.
    """
    cdef cystr tmpBS, saltedBS, tagStr
    cdef pFastqFile_t inHandle1, inHandle2, indexHandle
    cdef pFastqProxy_t rec1, rec2, index_read
    cdef int bLen, hpLimit
    if(outFq1 is None):
        outFq1 = TrimExt(inFq1) + ".rescued.shaded.fastq"
    if(outFq2 is None):
        outFq2 = TrimExt(inFq2) + ".rescued.shaded.fastq"
    if(TrueFamDict is None or rescueDict is None):
        raise Tim("TrueFamDict and rescueDict must not be None! Reprs! "
                  "TFD: %s. Rescue: %s." % (repr(TrueFamDict),
                                            repr(rescueDict)))
    print("Beginning RescuePairedFastqShading. Outfqs: %s, %s." % (outFq1,
                                                                   outFq2))
    inHandle1 = pFastqFile(inFq1)
    inHandle2 = pFastqFile(inFq2)
    indexHandle = pFastqFile(indexFq)
    outHandle1 = open(outFq1, "w")
    outHandle2 = open(outFq2, "w")
    ohw1 = outHandle1.write
    ohw2 = outHandle2.write
    ih2n = inHandle2.next
    bLen = len(indexHandle.next().sequence) + 2 * head
    hpLimit = bLen * 5 // 6  # Homopolymer limit
    indexHandle = pFastqFile(indexFq)
    ihn = indexHandle.next
    for rec1 in inHandle1:
        try:
            index_read = ihn()
            rec2 = ih2n()
        except StopIteration:
            raise Tim("Index fastq and read fastqs have different sizes. "
                      "Abort!")
        try:
            TrueFamDict[index_read.sequence]
            saltedBS = (rec1.sequence[:head] + index_read.sequence +
                        rec2.sequence[:head])
            rec1.comment = cMakeTagComment(saltedBS, rec1, hpLimit)
            rec2.comment = cMakeTagComment(saltedBS, rec2, hpLimit)
            ohw1(str(rec1))
            ohw2(str(rec2))
            continue
        except KeyError:
            pass
        try:
            saltedBS = (rec1.sequence[:head] +
                        rescueDict[index_read.sequence] +
                        rec2.sequence[:head])
            rec1.comment = cMakeTagComment(saltedBS, rec1, hpLimit)
            rec2.comment = cMakeTagComment(saltedBS, rec2, hpLimit)
            ohw1(str(rec1))
            ohw2(str(rec2))
            continue
        except KeyError:
            # This isn't in a true family. Blech!
            saltedBS = (rec1.sequence[:head] + index_read.sequence +
                        rec2.sequence[:head])
            rec1.comment = cMakeTagComment(saltedBS, rec1, hpLimit)
            rec2.comment = cMakeTagComment(saltedBS, rec2, hpLimit)
            ohw1(str(rec1))
            ohw2(str(rec2))
            continue
    outHandle1.close()
    outHandle2.close()
    return outFq1, outFq2


cpdef cystr MakeTagComment(cystr saltedBS, pFastqProxy_t rec, int hpLimit):
    """
    Python-visible MakeTagComment.
    """
    return cMakeTagComment(saltedBS, rec, hpLimit)
