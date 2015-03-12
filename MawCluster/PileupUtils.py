# cython: c_string_type=str, c_string_encoding=ascii
# cython: profile=True, cdivision=True, cdivision_warnings=True

import subprocess
import os.path
import shlex
import logging
import re
import operator

import numpy as np
import pysam
import cython
import numconv

from utilBMF.HTSUtils import ThisIsMadness
from utilBMF.HTSUtils import printlog as pl
from utilBMF.HTSUtils import PysamToChrDict
from utilBMF.HTSUtils import Base64ToInt
from utilBMF.HTSUtils import ToStr
from utilBMF import HTSUtils
import utilBMF


class pPileupRead:
    """
    Python container for the PileupRead proxy in pysam.
    """
    def __init__(self, PileupRead):
        self.alignment = PileupRead.alignment
        self.indel = PileupRead.indel
        self.is_del = PileupRead.is_del
        self.level = PileupRead.level
        self.query_position = PileupRead.query_position


class pPileupColumn:
    """
    Python container for the PileupColumn proxy in pysam.
    """
    def __init__(self, PileupColumn):
        self.nsegments = PileupColumn.nsegments
        self.reference_id = PileupColumn.reference_id
        self.reference_pos = PileupColumn.reference_pos
        self.pileups = [pPileupRead for i in PileupColumn.pileups]


"""
Contains various utilities for working with pileup generators
and preparing for variant calls.
"""


class PRInfo:

    """
    Created from a pysam.PileupRead object.
    Holds family size, SV tags, base quality, mapping quality, and base.
    If you want to query the FA attribute or the FractionAgreed Attribute,
    it is recommended that you run dir() on the PRInfo object for "FA" and
    "FractionAgreed".
    """

    def __init__(self, PileupRead):
        self.Pass = True
        try:
            self.FM = int(PileupRead.alignment.opt("FM"))
        except KeyError:
            self.FM = 1
        except ValueError:
            p = re.compile("\D")
            try:
                self.FM = int(p.sub("", PileupRead.alignment.opt("FM")))
            except ValueError:
                pl("Ain't nothing I can do. Something's wrong"
                   " with your FM tag: {}".format(p.sub(
                       "", PileupRead.alignment.opt("FM"))))
        try:
            self.SVTags = PileupRead.alignment.opt("SV").split(",")
        except KeyError:
            self.SVTags = "NF"
            # print("Warning: SV Tags unset.")
        self.BaseCall = PileupRead.alignment.query_sequence[
            PileupRead.query_position]
        self.BQ = PileupRead.alignment.query_qualities[
            PileupRead.query_position]
        self.MQ = PileupRead.alignment.mapq
        self.is_reverse = PileupRead.alignment.is_reverse
        self.is_proper_pair = PileupRead.alignment.is_proper_pair
        self.read = PileupRead.alignment
        self.ssString = "#".join(
            [str(i) for i in sorted(
                [self.read.reference_start, self.read.reference_end])])
        self.query_position = PileupRead.query_position
        if("FA" in dict(PileupRead.alignment.tags).keys()):
            self.FA_Array = np.array(
                PileupRead.alignment.opt("FA").split(",")).astype(int)
            self.FA = self.FA_Array[self.query_position]
            self.FractionAgreed = self.FA / float(self.FM)
        else:
            self.FA = None
            self.FractionAgreed = None
            self.FA_Array = None
        p = re.compile("[^0-9,]+")
        self.PV = None
        self.PV_Array = None
        self.PVFrac = None
        if("PV" in dict(PileupRead.alignment.tags).keys()):
            # If there are characters beside digits and commas, then it these
            # values must have been encoded in base 85.
            PVString = PileupRead.alignment.opt("PV")
            if(p.search(PVString) is not None):
                try:
                    self.PV_Array = map(Base64ToInt, PVString.split(','))
                    try:
                        assert len(self.PV_Array) == self.read.query_length
                    except AssertionError:
                        self.Pass = False
                    try:
                        self.PV = self.PV_Array[self.query_position]
                    except IndexError:
                        pl("PVString: {}".format(PVString),
                           level=logging.DEBUG)
                        pl("Len PV Array: {}".format(len(self.PV_Array)),
                           level=logging.DEBUG)
                        pl("QueryPos: {}".format(self.query_position),
                           level=logging.DEBUG)
                        pl("read.name {}.".format(self.read.qname),
                           level=logging.DEBUG)
                        pl("NOTE! Check the debug log for information"
                           " regarding potential corruption.")
                except ValueError:
                    self.PV_Array = None
                    self.PV = None
                    self.PVFrac = None
                    # Don't sweat it.
            else:
                try:
                    self.PV_Array = np.array(PVString.split(','),
                                             dtype=np.int64)
                except ValueError:
                    print("PVString = %s" % PVString)
                    raise ValueError("This PV String should only "
                                     "have digits and commas... ???")
                self.PV = self.PV_Array[self.query_position]
                self.PVFrac = float(self.PV) / np.max(self.PV_Array)


def is_reverse_to_str(boolean):
    if(boolean is True):
        return "reverse"
    elif(boolean is False):
        return "forward"
    else:
        return "unmapped"


class AlleleAggregateInfo:

    """
    Class which holds summary information for a given alt allele
    at a specific position. Meant to be used as part of the PCInfo
    class as values in the VariantDict.
    All alt alleles in this set of reads should be identical.
    recList must be a list of PRInfo objects.

    """

    @cython.locals(minFracAgreed=cython.float, minMQ=cython.long,
                   minBQ=cython.long, minFA=cython.long,
                   minPVFrac=cython.float)
    def __init__(self, recList, consensus="default",
                 mergedSize="default",
                 totalSize="default",
                 minMQ=0,
                 minBQ=0,
                 contig="default",
                 pos="default",
                 DOC="default",
                 DOCTotal="default",
                 NUMALT="default",
                 AABPSD="default", AAMBP="default",
                 minFracAgreed=0.0, minFA=0,
                 minPVFrac=0.666):
        import collections
        if(consensus == "default"):
            raise ThisIsMadness("A consensus nucleotide must be provided.")
        if(NUMALT == "default"):
            raise ThisIsMadness("Number of alternate alleles required.")
        else:
            self.NUMALT = NUMALT
        if(DOC == "default"):
            raise ThisIsMadness("Full depth of coverage must be provided.")
        else:
            self.DOC = int(DOC)
        if(DOCTotal != "default"):
            self.DOCTotal = int(DOCTotal)
        if(contig == "default"):
            raise ThisIsMadness("A contig must be provided (string).")
        else:
            self.contig = contig
        if(pos == "default"):
            raise ThisIsMadness("A position (0-based) must be provided (int).")
        else:
            self.pos = int(pos)
        if(mergedSize == "default"):
            raise ThisIsMadness(("mergedSize must be provided: number of "
                                 "PRInfo at given position."))
        if(totalSize == "default"):
            raise ThisIsMadness(("mergedSize must be provided: number of "
                                 "PRInfo at given position."))
        self.recList = [rec for rec in recList
                        if rec.MQ >= minMQ and rec.BQ >= minBQ]
        try:
            if("PVFrac" in dir(self.recList[0])):
                self.recList = [rec for rec in self.recList
                                if rec.PVFrac >= minPVFrac]
            if("FractionAgreed" in dir(self.recList[0])):
                self.recList = [rec for rec in self.recList
                                if rec.FractionAgreed >= minFracAgreed]
            if("FA" in dir(self.recList[0])):
                self.recList = [rec for rec in self.recList if rec.FA >= minFA]
        except IndexError:
            self.recList = []
        # Check that all alt alleles are identical
        try:
            assert(sum([rec.BaseCall == recList[
                0].BaseCall for rec in recList]) == len(recList))
        except AssertionError:
            # print("recList repr: {}".format(repr(recList)))
            print("Alt alleles: {}".format([i.BaseCall for i in recList]))
            raise ThisIsMadness(
                "AlleleAggregateInfo requires that all alt alleles agree.")
        self.TotalReads = np.sum(map(operator.attrgetter("FM"), recList))
        self.MergedReads = len(recList)
        self.ReverseMergedReads = np.sum(map(
            operator.attrgetter("is_reverse"), recList))
        self.ForwardMergedReads = self.MergedReads - self.ReverseMergedReads
        self.ReverseTotalReads = np.sum(map(
            operator.attrgetter("FM"),
            [rec for rec in recList if rec.is_reverse]))
        self.ForwardTotalReads = self.TotalReads - self.ReverseTotalReads
        self.AveFamSize = float(self.TotalReads) / self.MergedReads
        self.TotalAlleleDict = {"A": 0, "C": 0, "G": 0, "T": 0}
        self.SumBQScore = sum(map(operator.attrgetter("BQ"), recList))
        self.SumMQScore = sum(map(operator.attrgetter("MQ"), recList))
        try:
            self.AveMQ = float(self.SumMQScore) / len(self.recList)
        except ZeroDivisionError:
            self.AveMQ = 0
        try:
            self.AveBQ = float(self.SumBQScore) / len(self.recList)
        except ZeroDivisionError:
            self.AveBQ = 0
        self.ALT = recList[0].BaseCall
        self.consensus = consensus
        self.minMQ = minMQ
        self.minBQ = minBQ
        try:
            self.reverseStrandFraction = operator.div(self.ReverseMergedReads,
                                                      self.MergedReads)
        except ZeroDivisionError:
            self.reverseStrandFraction = -1
        self.MFractionAgreed = np.mean(map(
            operator.attrgetter("FractionAgreed"),  recList))
        self.minFrac = minFracAgreed
        self.minFA = minFA
        self.MFA = np.mean(map(operator.attrgetter("FA"), recList))

        # Dealing with transitions (e.g., A-T) and their strandedness
        self.transition = "->".join([consensus, self.ALT])
        self.strandedTransitions = {}
        self.strandedTransitionDict = collections.Counter(
            ["&&".join([self.transition, is_reverse_to_str(
                rec.is_reverse)]) for rec in self.recList])
        self.strandedTotalTransitionDict = collections.Counter(
            ["&&".join([self.transition, is_reverse_to_str(
                rec.is_reverse)]) for rec in self.recList] * rec.FM)
        self.strandedMergedTransitionDict = collections.Counter(
            ["&&".join([self.transition, is_reverse_to_str(
                rec.is_reverse)]) for rec in self.recList])
        self.StrandCountsDict = {}
        self.StrandCountsDict["reverse"] = sum([
            rec.is_reverse for rec in self.recList])
        self.StrandCountsDict["forward"] = sum([
            rec.is_reverse is False for rec in self.recList])
        self.StrandCountsTotalDict = {}
        self.StrandCountsTotalDict["reverse"] = sum(
            [rec.FM for rec in self.recList if rec.is_reverse is True])
        self.StrandCountsTotalDict["forward"] = sum(
            [rec.FM for rec in self.recList if rec.is_reverse is False])
        try:
            self.TotalAlleleFrequency = self.TotalReads / float(totalSize)
            self.MergedAlleleFrequency = self.MergedReads / float(mergedSize)
        except ZeroDivisionError:
            self.TotalAlleleFrequency = -1.0
            self.MergedAlleleFrequency = -1.0
        if(self.ReverseMergedReads != 0 and self.ForwardMergedReads != 0):
            self.BothStrandSupport = True
        else:
            self.BothStrandSupport = False
        if(AABPSD != "default"):
            self.AABPSD = AABPSD
        if(AAMBP != "default"):
            self.AAMBP = AAMBP

        # Check to see if a read pair supports a variant with both ends
        from collections import Counter
        ReadNameCounter = Counter([r.read.query_name for r in recList])
        ReadNameCounter = Counter(map(operator.attrgetter("query_name"),
                                      [r.read for r in recList]))
        self.NumberDuplexReads = sum([
            ReadNameCounter[key] > 1 for key in ReadNameCounter.keys()])
        query_positions = np.array(map(
            operator.attrgetter("query_position"), recList)).astype(float)
        self.MBP = np.mean(query_positions)
        self.BPSD = np.std(query_positions)
        self.minPVFrac = minPVFrac
        PVFArray = np.array(map(
            operator.attrgetter("PVFrac"), self.recList))
        self.MPF = np.mean(PVFArray)
        self.PFSD = np.std(PVFArray)


class PCInfo:

    """
    Takes a pysam.PileupColumn covering one base in the reference
    and makes a new class which has "reference" (inferred from
    consensus) and a list of PRData (one for each read).
    The option "duplex required" determines whether or not variants must
    be supported by both reads in a pair for a proper call. Increases
    stringency, might lose some sensitivity for a given sequencing depth.
    """

    @cython.locals(reverseStrandFraction=cython.float)
    def __init__(self, PileupColumn, minBQ=0, minMQ=0,
                 requireDuplex=True,
                 minFracAgreed=0.0, minFA=0, minPVFrac=0.66):
        assert isinstance(PileupColumn, pPileupColumn)
        self.minMQ = int(minMQ)
        self.minBQ = int(minBQ)
        from collections import Counter
        self.contig = PysamToChrDict[PileupColumn.reference_id]
        self.pos = PileupColumn.reference_pos
        self.FailedBQReads = sum(
            [pileupRead.alignment.query_qualities
             [pileupRead.query_position] < self.minBQ
             for pileupRead in PileupColumn.pileups])
        self.FailedMQReads = sum(
            [pileupRead.alignment.mapping_quality < self.minMQ
             for pileupRead in PileupColumn.pileups])
        self.PCol = PileupColumn
        """
        if(self.FailedMQReads != 0):
            print("Mapping qualities of reads which failed: {}".format(
                  str([pu.alignment.mapping_quality
                      for pu in PileupColumn.pileups
                      if pu.alignment.mapping_quality >= self.minMQ])))
        print("Number of reads failed for BQ < {}: {}".format(self.minBQ,
              self.FailedBQReads))
        print("Number of reads failed for MQ < {}: {}".format(self.minMQ,
              self.FailedMQReads))
        """
        self.Records = [
            PRInfo(pileupRead) for pileupRead in PileupColumn.pileups
            if(pileupRead.alignment.mapq >= self.minMQ) and
            (pileupRead.alignment.query_qualities[
                pileupRead.query_position] >= self.minBQ)]
        self.Records = [rec for rec in self.Records if rec.Pass is True]
        try:
            self.reverseStrandFraction = len(
                [i for i in self.Records if i.read.is_reverse is
                 True]) / float(len(self.Records))
        except ZeroDivisionError:
            self.reverseStrandFraction = 0.
        self.MergedReads = len(self.Records)
        try:
            self.TotalReads = sum([rec.FM for rec in self.Records])
        except KeyError:
            self.TotalReads = self.MergedReads
        try:
            self.consensus = Counter(
                [rec.BaseCall for rec in self.Records]).most_common(1)[0][0]
        except IndexError:
            self.consensus = Counter([rec.BaseCall
                                      for rec in
                                      [PRInfo(pileupRead) for pileupRead in
                                       PileupColumn.pileups]]).most_common(
                1)[0][0]
        self.VariantDict = {}
        for alt in list(set([rec.BaseCall for rec in self.Records])):
            self.VariantDict[alt] = [
                rec for rec in self.Records if rec.BaseCall == alt]
        query_positions = [float(i.query_position) for i in self.Records]
        self.AAMBP = np.mean(query_positions)
        self.AABPSD = np.std(query_positions)

        self.AltAlleleData = [AlleleAggregateInfo(
                              self.VariantDict[key],
                              consensus=self.consensus,
                              mergedSize=self.MergedReads,
                              totalSize=self.TotalReads,
                              minMQ=self.minMQ,
                              minBQ=self.minBQ,
                              contig=self.contig,
                              pos=self.pos,
                              DOC=self.MergedReads,
                              DOCTotal=self.TotalReads,
                              NUMALT=len(self.VariantDict.keys()),
                              AAMBP=self.AAMBP, AABPSD=self.AABPSD,
                              minFracAgreed=minFracAgreed, minFA=minFA,
                              minPVFrac=minPVFrac)
                              for key in self.VariantDict.keys()]
        self.TotalFracDict = {"A": 0., "C": 0., "G": 0., "T": 0.}
        for alt in self.AltAlleleData:
            self.TotalFracDict[
                alt.ALT] = float(alt.TotalReads) / self.TotalReads
        self.TotalFracStr = ",".join(
            ["->".join([key, str(self.TotalFracDict[key])])
             for key in self.TotalFracDict.keys()])
        self.TotalCountDict = {"A": 0, "C": 0, "G": 0, "T": 0}
        for alt in self.AltAlleleData:
            self.TotalCountDict[
                alt.ALT] = alt.TotalReads
        self.TotalCountStr = ",".join(
            ["->".join([key, str(self.TotalCountDict[key])])
             for key in self.TotalCountDict.keys()])
        self.MergedFracDict = {"A": 0., "C": 0., "G": 0., "T": 0.}
        for alt in self.AltAlleleData:
            self.MergedFracDict[
                alt.ALT] = operator.div(float(alt.MergedReads),
                                        self.MergedReads)
        self.MergedFracStr = ",".join(
            ["->".join([key, str(self.MergedFracDict[key])])
             for key in self.MergedFracDict.keys()])
        self.MergedCountDict = {"A": 0, "C": 0, "G": 0, "T": 0}
        for alt in self.AltAlleleData:
            self.MergedCountDict[
                alt.ALT] = alt.MergedReads
        self.MergedCountStr = ",".join(
            ["->".join([key, str(self.MergedCountDict[key])])
             for key in self.MergedCountDict.keys()])
        # Generates statistics based on transitions, e.g. ref-->alt
        TransMergedCounts = {}
        for alt in self.AltAlleleData:
            try:
                TransMergedCounts[alt.transition] = operator.add(
                    TransMergedCounts[alt.transition], alt.MergedReads)
            except KeyError:
                TransMergedCounts[alt.transition] = alt.MergedReads
        self.TransMergedCounts = TransMergedCounts
        TransTotalCounts = {}
        for alt in self.AltAlleleData:
            try:
                TransTotalCounts[alt.transition] += alt.TotalReads
            except KeyError:
                TransTotalCounts[alt.transition] = alt.TotalReads
        self.TransTotalCounts = TransTotalCounts
        self.StrandedTransTotalCounts = {}
        for alt in self.AltAlleleData:
            for trans in alt.strandedTotalTransitionDict.keys():
                try:
                    self.StrandedTransTotalCounts[
                        trans] += alt.strandedTotalTransitionDict[trans]
                except KeyError:
                    self.StrandedTransTotalCounts[
                        trans] = alt.strandedTotalTransitionDict[trans]
        self.StrandedTransMergedCounts = {}
        for alt in self.AltAlleleData:
            for trans in alt.strandedMergedTransitionDict.keys():
                try:
                    self.StrandedTransMergedCounts[
                        trans] += alt.strandedMergedTransitionDict[trans]
                except KeyError:
                    self.StrandedTransMergedCounts[
                        trans] = alt.strandedMergedTransitionDict[trans]
        self.MergedAlleleDict = {"A": 0, "C": 0, "G": 0, "T": 0}
        self.TotalAlleleDict = {"A": 0, "C": 0, "G": 0, "T": 0}
        for alt in self.AltAlleleData:
            self.MergedAlleleDict[alt.ALT] = alt.MergedReads
            self.TotalAlleleDict[alt.ALT] = alt.TotalReads
        # Process allele frequencies, both by unique and unmerged reads
        self.MergedAlleleFreqDict = {"A": 0., "C": 0., "G": 0., "T": 0.}
        self.TotalAlleleFreqDict = {"A": 0., "C": 0., "G": 0., "T": 0.}
        try:
            for key in self.MergedAlleleDict:
                self.MergedAlleleFreqDict[key] = self.MergedAlleleDict[
                    key] / float(self.MergedReads)
                self.TotalAlleleFreqDict[key] = self.TotalAlleleDict[
                    key] / float(self.TotalReads)
        except ZeroDivisionError:
            for key in self.MergedAlleleDict:
                self.MergedAlleleFreqDict[key] = 0.
                self.TotalAlleleFreqDict[key] = 0.
        self.MergedAlleleCountStr = "\t".join(
            map(ToStr, [self.MergedAlleleDict["A"],
                        self.MergedAlleleDict["C"],
                        self.MergedAlleleDict["G"],
                        self.MergedAlleleDict["T"]]))
        self.TotalAlleleCountStr = "\t".join(
            map(ToStr, [self.TotalAlleleDict["A"],
                        self.TotalAlleleDict["C"],
                        self.TotalAlleleDict["G"],
                        self.TotalAlleleDict["T"]]))
        self.MergedAlleleFreqStr = "\t".join(
            map(ToStr, [self.MergedAlleleFreqDict["A"],
                        self.MergedAlleleFreqDict["C"],
                        self.MergedAlleleFreqDict["G"],
                        self.MergedAlleleFreqDict["T"]]))
        self.TotalAlleleFreqStr = "\t".join(
            map(ToStr, [self.TotalAlleleFreqDict["A"],
                        self.TotalAlleleFreqDict["C"],
                        self.TotalAlleleFreqDict["G"],
                        self.TotalAlleleFreqDict["T"]]))
        # MergedStrandednessRatioDict is the fraction of reverse reads
        # supporting an alternate allele.
        # E.g., if 5 support the alt, but 2 are mapped to the reverse
        # strand, the value is 0.4
        self.MergedStrandednessRatioDict = {"A": 0., "C": 0., "G": 0., "T": 0.}
        self.TotalStrandednessRatioDict = {"A": 0., "C": 0., "G": 0., "T": 0.}
        for alt in self.AltAlleleData:
            self.MergedStrandednessRatioDict[
                alt.ALT] = alt.ReverseMergedReads / float(alt.MergedReads)
            self.TotalStrandednessRatioDict[
                alt.ALT] = alt.ReverseTotalReads / float(alt.TotalReads)
        self.MergedStrandednessStr = "\t".join([
            str(self.MergedStrandednessRatioDict[
                key]) for key in self.MergedStrandednessRatioDict.keys()])
        self.TotalStrandednessStr = "\t".join([
            str(self.TotalStrandednessRatioDict[
                key]) for key in self.TotalStrandednessRatioDict.keys()])
        self.AlleleFreqStr = "\t".join(
            [str(i) for i in [self.contig,
                              self.pos,
                              self.consensus,
                              self.MergedReads,
                              self.TotalReads,
                              self.MergedAlleleCountStr,
                              self.TotalAlleleCountStr,
                              self.MergedAlleleFreqStr,
                              self.TotalAlleleFreqStr,
                              self.MergedStrandednessStr,
                              self.TotalStrandednessStr]])

    def ToString(self, header=False):
        outStr = ""
        if(header is True):
            outStr = ("#Chr\tPos (0-based)\tRef (Consensus)\tAlt\tTotal "
                      "Reads\tMerged Reads\tTotal Allele Frequency\tMerged "
                      "Allele Frequency\tReverse Total Reads\tForward Total"
                      " Reads\tReverse Merged Reads\tForward Merged Reads"
                      "\tFraction Of Total Reads\t"
                      "Fraction Of Merged Reads\tAverage "
                      "Family Size\t"
                      "BQ Sum\tBQ Mean\tMQ Sum\tMQ Mean\n")
        for alt in self.AltAlleleData:
            outStr += "\t".join(
                map(ToStr, [self.contig,
                            self.pos,
                            self.consensus,
                            alt.ALT,
                            alt.TotalReads,
                            alt.MergedReads,
                            alt.TotalAlleleFrequency,
                            alt.MergedAlleleFrequency,
                            alt.StrandCountsTotalDict["reverse"],
                            alt.StrandCountsTotalDict["forward"],
                            alt.StrandCountsDict["reverse"],
                            alt.StrandCountsDict["forward"],
                            self.TotalFracDict[alt.ALT],
                            self.MergedFracDict[alt.ALT],
                            alt.AveFamSize,
                            alt.SumBQScore,
                            alt.AveBQ,
                            alt.SumMQScore,
                            alt.AveMQ])) + "\n"
        self.str = outStr
        return self.str


class PileupInterval:

    """
    Container for holding summary information over a given interval.
    Written for the pysam PileupColumn data structure.
    Contig should be in the pysam format (IE, a number, not a string)
    """

    def __init__(self, contig="default", start="default",
                 end="default"):
        self.contig = contig
        self.start = int(start)
        self.end = int(end)
        assert self.start < self.end  # Interval must be positive...
        self.TotalCoverage = 0
        self.UniqueCoverage = 0
        self.AvgTotalCoverage = 0
        self.AvgUniqueCoverage = 0
        self.str = self.ToString()

    def updateWithPileupColumn(self, PileupColumn):
        self.end += 1
        assert self.start < self.end  # Interval must be positive...
        try:
            self.TotalCoverage += sum([int(pu.alignment.opt(
                                      "FM")) for pu in PileupColumn.pileups])
        except KeyError:
            self.TotalCoverage = PileupColumn.nsegments
        self.UniqueCoverage += PileupColumn.nsegments
        self.AvgTotalCoverage = self.TotalCoverage / float(
            self.end - self.start)
        self.AvgUniqueCoverage = self.UniqueCoverage / float(
            self.end - self.start)

    def ToString(self):
        self.str = "\t".join([str(i) for i in [PysamToChrDict[self.contig],
                                               self.start,
                                               self.end,
                                               self.UniqueCoverage,
                                               self.TotalCoverage,
                                               self.AvgUniqueCoverage,
                                               self.AvgTotalCoverage]])
        return self.str


def CustomPileupFullGenome(inputBAM,
                           PileupTsv="default",
                           TransitionTable="default",
                           StrandedTTable="default",
                           progRepInterval=10000,
                           minBQ=0,
                           minMQ=0):
    """
    A pileup tool for creating a tsv for each position in the bed file.
    Used for calling SNPs with high confidence.
    Also creates several tables:
    1. Counts for all consensus-->alt transitions (By Total and Merged reads)
    2. Counts for the above, specifying strandedness
    3. Number of Merged Reads supporting each allele
    """
    TransTotalDict = {}
    TransMergedDict = {}
    StrandedTransTotalDict = {}
    StrandedTransMergedDict = {}
    NumTransitionsTotal = 0
    NumTransitionsMerged = 0
    MergedReadsProcessed = 0
    TotalReadsProcessed = 0
    if(PileupTsv == "default"):
        PileupTsv = inputBAM[0:-4] + ".Pileup.tsv"
    if(TransitionTable == "default"):
        TransitionTable = inputBAM[0:-4] + ".Trans.tsv"
    if(StrandedTTable == "default"):
        StrandedTTable = inputBAM[0:-4] + ".StrandedTrans.tsv"
    subprocess.check_call(["samtools", "index", inputBAM])
    if(os.path.isfile(inputBAM + ".bai") is False):
        pl("Couldn\'t index BAM - coor sorting, then indexing!")
        inputBAM = HTSUtils.CoorSortAndIndexBam(inputBAM, uuid=True)
    NumProcessed = 0  # Number of processed positions in pileup
    bamHandle = pysam.AlignmentFile(inputBAM, "rb")
    PileupHandle = open(PileupTsv, "w")
    TransHandle = open(TransitionTable, "w")
    StrandedTransHandle = open(StrandedTTable, "w")
    FirstLine = True
    pileupIterator = bamHandle.pileup(max_depth=30000, multiple_iterators=True)
    p = pPileupColumn(next(pileupIterator))
    for pileupColumn in p.pileups:
        NumProcessed += 1
        if((NumProcessed) % progRepInterval == 0):
            pl("Number of positions processed: {}".format(
                NumProcessed))
            pl("Total reads processed: {}".format(TotalReadsProcessed))
            pl("Merged reads processed: {}".format(MergedReadsProcessed))
        PColSum = PCInfo(pileupColumn, minBQ=minBQ, minMQ=minMQ)
        MergedReadsProcessed += PColSum.MergedReads
        TotalReadsProcessed += PColSum.TotalReads
        if(FirstLine is True):
            PileupHandle.write(PColSum.ToString(header=True))
            FirstLine = False
        else:
            PileupHandle.write(PColSum.ToString())
        for key in PColSum.TransMergedCounts.keys():
            try:
                TransMergedDict[
                    key] += PColSum.TransMergedCounts[key]
            except KeyError:
                TransMergedDict[
                    key] = PColSum.TransMergedCounts[key]
            NumTransitionsMerged += PColSum.TransMergedCounts[
                key]
        for key in PColSum.TransTotalCounts.keys():
            try:
                TransTotalDict[
                    key] += PColSum.TransTotalCounts[key]
            except KeyError:
                TransTotalDict[
                    key] = PColSum.TransTotalCounts[key]
            NumTransitionsTotal += PColSum.TransTotalCounts[
                key]
        for key in PColSum.StrandedTransMergedCounts.keys():
            try:
                StrandedTransMergedDict[
                    key] += PColSum.StrandedTransMergedCounts[
                        key]
            except KeyError:
                StrandedTransMergedDict[
                    key] = PColSum.StrandedTransMergedCounts[
                        key]
        for key in PColSum.StrandedTransTotalCounts.keys():
            try:
                StrandedTransTotalDict[
                    key] += PColSum.StrandedTransTotalCounts[
                        key]
            except KeyError:
                StrandedTransTotalDict[
                    key] = PColSum.StrandedTransTotalCounts[
                        key]
    TransHandle.write(("Transition\tTotal Reads With Transition (Unflattened)"
                       "\tMerged Reads With Transition\tFraction Of Total "
                       "Transitions\tFraction Of Merged Transitions\n"))
    for key in TransTotalDict.keys():
        TransHandle.write("{}\t{}\t{}\n".format(key,
                                                TransTotalDict[key],
                                                TransMergedDict[key],
                                                TransTotalDict[key] / float(
                                                    NumTransitionsTotal),
                                                TransMergedDict[key] / float(
                                                    NumTransitionsMerged)))
    StrandedTransHandle.write(("Transition+Strandedness\tTotal Reads "
                               "(Unflattened)\tMergedReads With Transition\t"
                               "Fraction Of Total (Unflattened) Transitions"
                               "\tFraction of Merged Transitions\n"))
    for key in StrandedTransTotalDict.keys():
        StrandedTransHandle.write(
            "{}\t{}\t{}\n".format(
                key,
                StrandedTransTotalDict[key],
                StrandedTransMergedDict[key],
                StrandedTransTotalDict[key] /
                float(NumTransitionsTotal),
                StrandedTransMergedDict[key] /
                float(NumTransitionsMerged),
            ))
    pl("Transition Table: {}".format(TransitionTable))
    pl("Stranded Transition Table: {}".format(StrandedTTable))
    TransHandle.close()
    PileupHandle.close()
    return PileupTsv


def CustomPileupToTsv(inputBAM,
                      PileupTsv="default",
                      TransitionTable="default",
                      StrandedTTable="default",
                      bedfile="default",
                      progRepInterval=1000,
                      CalcAlleleFreq=True,
                      minMQ=0,
                      minBQ=0):
    """
    A pileup tool for creating a tsv for each position in the bed file.
    Used for calling SNPs with high confidence.
    Also creates several tables:
    1. Counts for all consensus-->alt transitions (By Total and Merged reads)
    2. Counts for the above, specifying strandedness
    3. Number of Merged Reads supporting each allele
    """
    TransTotalDict = {}
    TransMergedDict = {}
    StrandedTransTotalDict = {}
    StrandedTransMergedDict = {}
    NumTransitionsTotal = 0
    NumTransitionsMerged = 0
    MergedReadsProcessed = 0
    TotalReadsProcessed = 0
    if(PileupTsv == "default"):
        PileupTsv = inputBAM[0:-4] + ".Pileup.tsv"
    if(TransitionTable == "default"):
        TransitionTable = inputBAM[0:-4] + ".Trans.tsv"
    if(StrandedTTable == "default"):
        StrandedTTable = inputBAM[0:-4] + ".StrandedTrans.tsv"
    if(bedfile == "default"):
        return CustomPileupFullGenome(inputBAM, PileupTsv=PileupTsv,
                                      TransitionTable=TransitionTable,
                                      StrandedTTable=StrandedTTable,
                                      progRepInterval=progRepInterval)
    bedlines = HTSUtils.ParseBed(bedfile)
    try:
        subprocess.check_call(["samtools", "index", inputBAM])
    except subprocess.CalledProcessError:
        pl("Couldn't index BAM - coor sorting, then indexing!")
        inputBAM = HTSUtils.CoorSortAndIndexBam(inputBAM, uuid=True)
    NumPos = sum([line[2] - line[1] for line in bedlines])
    NumProcessed = 0  # Number of processed positions in pileup
    pl("Number of positions in bed file: {}".format(NumPos))
    bamHandle = pysam.AlignmentFile(inputBAM, "rb")
    PileupHandle = open(PileupTsv, "w")
    TransHandle = open(TransitionTable, "w")
    StrandedTransHandle = open(StrandedTTable, "w")
    FirstLine = True
    for line in bedlines:
        pileupIterator = bamHandle.pileup(line[0], line[1], line[2],
                                          max_depth=30000)
        p = pPileupColumn(next(pileupIterator))
        for pileupColumn in p.pileups:
            NumProcessed += 1
            if((NumProcessed) % progRepInterval == 0):
                pl("Number of positions processed: {}".format(
                    NumProcessed + 1))
                pl("{:.1%} complete".format(NumProcessed / float(NumPos)))
                pl("Total reads processed: {}".format(TotalReadsProcessed))
                pl("Merged reads processed: {}".format(
                    MergedReadsProcessed))
            PColSum = PCInfo(pileupColumn, minMQ=minMQ, minBQ=minBQ)
            MergedReadsProcessed += PColSum.MergedReads
            TotalReadsProcessed += PColSum.TotalReads
            if(FirstLine is True):
                PileupHandle.write(PColSum.ToString(header=True))
                FirstLine = False
            else:
                PileupHandle.write(PColSum.ToString())
            for key in PColSum.TransMergedCounts.keys():
                try:
                    TransMergedDict[
                        key] += PColSum.TransMergedCounts[key]
                except KeyError:
                    TransMergedDict[
                        key] = PColSum.TransMergedCounts[key]
                NumTransitionsMerged += PColSum.TransMergedCounts[
                    key]
            for key in PColSum.TransTotalCounts.keys():
                try:
                    TransTotalDict[
                        key] += PColSum.TransTotalCounts[key]
                except KeyError:
                    TransTotalDict[
                        key] = PColSum.TransTotalCounts[key]
                NumTransitionsTotal += PColSum.TransTotalCounts[
                    key]
            for key in PColSum.StrandedTransMergedCounts.keys():
                try:
                    StrandedTransMergedDict[
                        key] += PColSum.StrandedTransMergedCounts[
                            key]
                except KeyError:
                    StrandedTransMergedDict[
                        key] = PColSum.StrandedTransMergedCounts[
                            key]
            for key in PColSum.StrandedTransTotalCounts.keys():
                try:
                    StrandedTransTotalDict[
                        key] += PColSum.StrandedTransTotalCounts[
                            key]
                except KeyError:
                    StrandedTransTotalDict[
                        key] = PColSum.StrandedTransTotalCounts[
                            key]
    TransHandle.write((
        "Transition\tTotal Reads With Transition (Unflatt"
        "ened)\tMerged Reads With Transition\tFraction Of Total "
        "Transitions\tFraction Of Merged Transitions\n"))
    for key in TransTotalDict.keys():
        if(key[0] != key[3]):
            TransHandle.write(
                "{}\t{}\t{}\n".format(
                    key,
                    TransTotalDict[key],
                    TransMergedDict[key],
                    TransTotalDict[key] /
                    float(NumTransitionsTotal),
                    TransMergedDict[key] /
                    float(NumTransitionsMerged)))
    StrandedTransHandle.write(("Transition+Strandedness\tTotal Reads "
                               "(Unflattened)\tMergedReads With Transition\t"
                               "Fraction Of Total (Unflattened) Transitions"
                               "\tFraction of Merged Transitions\n"))
    for key in StrandedTransTotalDict.keys():
        if(key.split("&&")[0].split("->")[0] != key.split(
                "&&")[0].split("->")[1]):
            StrandedTransHandle.write(
                "{}\t{}\t{}\t{}\t{}\n".format(
                    key,
                    StrandedTransTotalDict[key],
                    StrandedTransMergedDict[key],
                    StrandedTransTotalDict[key] /
                    float(NumTransitionsTotal),
                    StrandedTransMergedDict[key] /
                    float(NumTransitionsMerged),
                ))
    pl("Transition Table: {}".format(TransitionTable))
    pl("Stranded Transition Table: {}".format(StrandedTTable))
    TransHandle.close()
    PileupHandle.close()
    if(CalcAlleleFreq is True):
        AlleleFreqTsv = AlleleFrequenciesByBase(inputBAM,
                                                bedfile=bedfile,
                                                minMQ=minMQ,
                                                minBQ=minBQ)
        pl("Optional allele frequency table generated. Path: {}".format(
            AlleleFreqTsv))
    return PileupTsv


def AlleleFrequenciesByBase(inputBAM,
                            outputTsv="default",
                            progRepInterval=10000,
                            minMQ=0,
                            minBQ=0,
                            bedfile="default"):
    """
    Creates a tsv file with counts and frequencies for each allele at
    each position. I should expand this to include strandedness information.
    """
    pl(("Command required to reproduce results: "
        "AlleleFrequenciesByBase(inputBAM=\"{}\",".format(inputBAM) +
        " outputTsv=\"{}\", progRepInterval=".format(outputTsv) +
        "\"{}\", minMQ=\"{}\", )".format(progRepInterval, minMQ) +
        "minBQ=\"{}\"".format(minBQ)))
    if(outputTsv == "default"):
        outputTsv = inputBAM[0:-4] + ".allele.freq.tsv"
    try:
        subprocess.check_call(["samtools", "index", inputBAM])
    except subprocess.CalledProcessError:
        pl("Couldn't index BAM - coor sorting, then indexing!")
        inputBAM = HTSUtils.CoorSortAndIndexBam(inputBAM, uuid=True)
    NumProcessed = 0  # Number of processed positions in pileup
    inHandle = pysam.AlignmentFile(inputBAM, "rb")
    outHandle = open(outputTsv, "w")
    outHandle.write("\t".join(["#Contig",
                               "Position (0-based)",
                               "Consensus Base",
                               "Merged DOC",
                               "Total DOC",
                               "Merged Count: A",
                               "Merged Count: C",
                               "Merged Count: G",
                               "Merged Count: T",
                               "Total Count: A",
                               "Total Count: C",
                               "Total Count: G",
                               "Total Count: T",
                               "Merged Freq: A",
                               "Merged Freq: C",
                               "Merged Freq: G",
                               "Merged Freq: T",
                               "Total Freq: A",
                               "Total Freq: C",
                               "Total Freq: G",
                               "Total Freq: T",
                               "Merged Reverse fraction: A",
                               "Merged Reverse fraction: C",
                               "Merged Reverse fraction: G",
                               "Merged Reverse fraction: T",
                               "Total Reverse fraction: A",
                               "Total Reverse fraction: C",
                               "Total Reverse fraction: G",
                               "Total Reverse fraction: T",
                               ]) + "\n")
    if(bedfile == "default"):
        pileupIterator = inHandle.pileup(max_depth=30000)
        p = pPileupColumn(next(pileupIterator))
        for pileup in p.pileups:
            NumProcessed += 1
            if(NumProcessed % progRepInterval == 0):
                pl("Number of base positions processed: {}".format(
                    NumProcessed))
            PColInfo = PCInfo(pileup, minMQ=minMQ, minBQ=minBQ)
            outHandle.write(PColInfo.AlleleFreqStr + "\n")
    else:
        bedLines = HTSUtils.ParseBed(bedfile)
        for line in bedLines:
            # print("Now running through the bedLine: {}".format(line))
            puIterator = inHandle.pileup(reference=line[0], start=line[1],
                                         end=line[2],
                                         max_depth=30000)
            p = pPileupColumn(next(puIterator))
            for pileup in p.pileups:
                NumProcessed += 1
                if(NumProcessed % progRepInterval == 0):
                    pl("Number of base positions processed: {}".format(
                        NumProcessed))
                outHandle.write(PCInfo(pileup,
                                       minMQ=minMQ,
                                       minBQ=minBQ).AlleleFreqStr + "\n")
    inHandle.close()
    outHandle.close()
    return outputTsv


def BamToCoverageBed(inBAM, outbed="default", mincov=5, minMQ=0, minBQ=0):
    """
    Takes a bam file and creates a bed file containing each position
    """
    pl(("Command required to reproduce this call: "
        "BamToCoverageBed(\"{}\", outbed=".format(inBAM) +
        "\"{}\", mincov={})".format(outbed, mincov)))
    pl(("WARNING: Coverage counts for this script"
        " are wrong. Fix in the works!"
        " It seems to only show up for very long regions."))
    if(outbed == "default"):
        outbed = inBAM[0:-4] + ".doc.bed"
    subprocess.check_call(shlex.split("samtools index {}".format(inBAM)),
                          shell=False)
    if(os.path.isfile(inBAM + ".bai") is False):
        pl("Bam index file was not created. Sorting and indexing.")
        inBAM = HTSUtils.CoorSortAndIndexBam(inBAM)
        pl("Sorted BAM Location: {}".format(inBAM))
    inHandle = pysam.AlignmentFile(inBAM, "rb")
    outHandle = open(outbed, "w")
    workingChr = 0
    workingPos = 0
    outHandle.write("\t".join(["#Chr", "Start", "End",
                               "Number Of Merged Mapped Bases",
                               "Number of Unmerged Mapped Bases",
                               "Avg Merged Coverage",
                               "Avg Total Coverage"]) + "\n")
    pl("Beginning PileupToBed.")
    pileupIterator = inHandle.pileup(max_depth=30000)
    ChrToPysamDict = utilBMF.HTSUtils.GetRefIdDicts()["chrtoid"]
    while True:
        try:
            p = pPileupColumn(next(pileupIterator))
        except StopIteration:
            pl("Stopping iterations.")
        PC = PCInfo(p)
        if("Interval" not in locals()):
            if(PC.MergedReads >= mincov):
                Interval = PileupInterval(contig=PC.PCol.reference_id,
                                          start=PC.PCol.reference_pos,
                                          end=PC.PCol.reference_pos + 1)
                try:
                    Interval.updateWithPileupColumn(PC.PCol)
                except AssertionError:
                    del Interval
                workingChr = PC.contig
                workingPos = PC.pos
            continue
        else:
            if(workingChr ==
               PC.PCol.reference_id and PC.PCol.nsegments >= mincov):
                if(PC.PCol.reference_pos - workingPos == 1):
                    try:
                        Interval.updateWithPileupColumn(PC.PCol)
                        workingPos += 1
                    except AssertionError:
                        del Interval
                else:
                    outHandle.write(Interval.ToString() + "\n")
                    if(PC.PCol.nsegments >= mincov):
                        Interval = PileupInterval(
                            contig=PC.PCol.reference_id,
                            start=PC.PCol.reference_pos,
                            end=PC.PCol.reference_pos + 1)
                        workingChr = PC.PCol.reference_id
                        workingPos = PC.PCol.reference_pos
                        Interval.updateWithPileupColumn(PC.PCol)
                    else:
                        del Interval
            else:
                try:
                    Interval.updateWithPileupColumn(PC.PCol)
                    outHandle.write(Interval.ToString() + "\n")
                except AssertionError:
                    del Interval
                if(PC.PCol.nsegments >= mincov):
                    Interval = PileupInterval(contig=PC.PCol.reference_id,
                                              start=PC.PCol.reference_pos,
                                              end=PC.PCol.reference_pos + 1)
                    workingChr = PC.PCol.reference_id
                    workingPos = PC.PCol.reference_pos
                    Interval.updateWithPileupColumn(PC.PCol)
                else:
                    del Interval
    inHandle.close()
    outHandle.close()
    pass


def CalcWithinBedCoverage(inBAM, bed="default", minMQ=0, minBQ=0,
                          outbed="default"):
    """
    Calculates DOC and creates a bed file containing coverage information
    for each position in a provided bed, only counting reads with
    a given minimum mapping quality or base quality.
    """
    if(outbed == "default"):
        outbed = inBAM[0:-4] + ".doc.bed"
    pl(("Command required to reproduce this call: "
        "CalcWithinBedCoverage(\"{}\", bed=".format(inBAM) +
        "\"{}\", minMQ=\"{}\", minBQ=".format(bed, minMQ) +
        "\"{}\", outbed=\"{}\")".format(minBQ, outbed)))
    if(bed == "default"):
        pl("Bed file required for CalcWithinBedCoverage")
        raise ThisIsMadness("Bedfile required for calculating coverage.")
    bedLines = HTSUtils.ParseBed(bed)
    subprocess.check_call(shlex.split("samtools index {}".format(inBAM)),
                          shell=False)
    if(os.path.isfile(inBAM + ".bai") is False):
        pl("Bam index file could not be created. Sorting and indexing.")
        inBAM = HTSUtils.CoorSortAndIndexBam(inBAM)
        pl("Sorted BAM Location: {}".format(inBAM))
    inHandle = pysam.AlignmentFile(inBAM, "rb")
    outHandle = open(outbed, "w")
    outHandle.write("\t".join(["#Chr", "Start", "End",
                               "Number Of Merged Mapped Bases",
                               "Number of Unmerged Mapped Bases",
                               "Avg Merged Coverage",
                               "Avg Total Coverage"]) + "\n")
    for line in bedLines:
        TotalReads = 0
        MergedReads = 0
        pileupIterator = inHandle.pileup(line[0],
                                         line[1],
                                         line[2],
                                         max_depth=30000)
        while True:
            try:
                PC = PCInfo(pPileupColumn(next(pileupIterator)))
            except StopIteration:
                pl("Stopping iteration for bed line: {}".format(line),
                   level=logging.DEBUG)
                continue
            TotalReads += PC.TotalReads
            MergedReads += PC.MergedReads
        outHandle.write(
            "\t".join(
                [str(i)
                 for i in
                 [line[0],
                  line[1],
                  line[2],
                  MergedReads, TotalReads, MergedReads /
                  float(line[2] - line[1]),
                  TotalReads / float(line[2] - line[1])]]) + "\n")
    inHandle.close()
    outHandle.close()
    return outbed


def CalcWithoutBedCoverage(inBAM, bed="default", minMQ=0, minBQ=0,
                           outbed="default"):
    """
    Calculates DOC and creates a bed file containing each position
    not in provided bed, only counting reads with a given minimum mapping
    quality or base quality.
    """
    if(outbed == "default"):
        outbed = inBAM[0:-4] + ".doc.SBI.bed"
    pl(("Command required to reproduce this call: "
        "CalcWithoutBedCoverage(\"{}\", bed=".format(inBAM) +
        "\"{}\", minMQ=\"{}\", minBQ=".format(bed, minMQ) +
        "\"{}\", outbed={})".format(minBQ, outbed)))
    if(bed == "default"):
        pl("Bed file required for CalcWithoutBedCoverage")
        raise ThisIsMadness("Bedfile required for calculating coverage.")
    bedLines = HTSUtils.ParseBed(bed)
    subprocess.check_call(shlex.split("samtools index {}".format(inBAM)),
                          shell=False)
    if(os.path.isfile(inBAM + ".bai") is False):
        pl("Bam index file could not be created. Sorting and indexing.")
        inBAM = HTSUtils.CoorSortAndIndexBam(inBAM)
        pl("Sorted BAM Location: {}".format(inBAM))
    inHandle = pysam.AlignmentFile(inBAM, "rb")
    outHandle = open(outbed, "w")
    outHandle.write("\t".join(["#Chr", "Start", "End",
                               "Number Of Merged Mapped Bases",
                               "Number of Unmerged Mapped Bases"]) + "\n")
    pileupIterator = inHandle.pileup(max_depth=30000, multiple_iterators=True)
    while True:
        try:
            p = pPileupColumn(next(pileupIterator))
        except StopIteration:
            pl("Finished iterations. (CalcWithoutBedCoverage)")
        PC = PCInfo(p, minMQ=minMQ, minBQ=minBQ)
        if HTSUtils.PosContainedInBed(PC.contig, PC.pos, bedLines):
            continue
        outHandle.write("\t".join(
            [str(i)
             for i in [PC.contig, PC.pos, PC.pos + 1,
                       PC.MergedReads, PC.TotalReads]]) + "\n")
    inHandle.close()
    outHandle.close()
    pass
