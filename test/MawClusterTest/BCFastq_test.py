#!/usr/bin/env python
import shlex
import subprocess
import sys
import unittest

from BMFMain.Workflow import pairedFastqShades
from utilBMF.HTSUtils import pFastqFile
from MawCluster.BCFastq import (pCompareFqRecsFast as cCompareFqRecsFast,
                                pairedFastqConsolidate, singleFastqConsolidate)

__author__ = 'dnephi'


class MyTestCase(unittest.TestCase):
    """
    TODO: Add a unit test to assert that the sum of the sizes of merged
    families equals the number of pre-merged reads.
    """

    def tearDown(self):
        for filename in self.filenames:
            subprocess.check_call(["rm", filename])

    def setUp(self):
        self.handle = pFastqFile("../data/lambda_test_R1.fastq.gz")
        self.prefastqs = [i for i in self.handle]
        self.filenames = []

    def test_compareFqRecs(self):
        tmpStr = cCompareFqRecsFast(self.prefastqs)
        pass_test = (tmpStr == (
            "@NS500690:24:H5W73BGXX:1:11101:17000:1039 1:N:0:NCAGAGCC|FM=1000|"
            "ND=107584|FA=278,280,261,268,279,211,287,256,263,259,262,279,259,"
            "258,264,275,261,278,259,285,266,255,280,266,259,261,256,265,265,2"
            "81,264,266,268,263,281,267,263,276,284,291,260,263,263,270,264,25"
            "2,258,244,274,246,250,266,245,257,257,259,274,264,264,255,250,254"
            ",261,264,266,266,283,270,255,284,272,267,264,253,260,268,276,263,"
            "269,270,259,271,256,254,265,255,261,252,268,248,258,252,250,256,2"
            "51,270,257,266,265,243,254,249,268,254,242,248,264,250,246,262,26"
            "6,281,256,269,273,254,253,237,242,267,274,265,275,261,289,258,262"
            ",252,245,276,259,260,274,246,271,272,271,269,271,275,264,248,250,"
            "279,284,275|PV=8646,9194,8830,8928,9386,7729,10377,9150,9641,9488"
            ",9604,10178,9372,9433,9659,9974,9519,10073,9414,10231,9591,9276,1"
            "0153,9692,9353,9510,9311,9615,9604,10252,9575,9437,9673,9610,1015"
            "7,9739,9490,9942,10199,10616,9392,9494,9609,9744,9643,9107,9325,8"
            "895,10039,8954,9055,9585,8895,9269,9200,9285,9722,9595,9480,9075,"
            "9091,9154,9385,9450,9557,9704,10092,9601,9257,10156,9754,9650,942"
            "2,9066,9204,9392,9849,9266,9653,9474,9188,9753,9185,9169,9514,904"
            "2,9253,9002,9353,8885,9153,8688,8911,8956,8964,9558,9127,9422,935"
            "5,8693,9007,8771,9349,9023,8512,8679,9229,8895,8741,9036,9331,969"
            "5,9047,9297,9675,8978,8971,8470,8543,9053,9655,9014,9782,9110,100"
            "38,8870,9072,8873,8581,9553,8926,8800,9450,8288,9386,9300,9406,92"
            "20,9273,9658,9042,8558,8614,9488,9618,8473\nGGCAGGAATCGTACTCCACTT"
            "AATTTCAATTAATACAAACCAGATCGGTGCGCTAAATGCTGTCTTCAGGAGAGAAAAGAAGGTTC"
            "TGATGAGCGAAGGGTTGTCCATGAGAGAGGGTGAGAGGGGGGGGGGGAGGGGGGGGGGGG\n+\n"
            "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"
            "~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~"
            "~~~~~~~~~~~~~~~~\n"))
        if not pass_test:
            raise AssertionError(
                "Str: '%s' does not match unit test. Abort!" % tmpStr)

    def test_pfc(self):
        pairedFastqShades("../data/TinyDemo_R1.fastq.gz",
                          "../data/TinyDemo_R3.fastq.gz",
                          indexFq="../data/TinyDemo_R2.fastq.gz")
        cStrToCheck = ("cat TinyDemo_R1.shaded.BS.cons.fastq | paste "
                       "- - - - | cut -d'|' -f4 | cut -d'=' -f2 | paste -sd+ "
                       "| bc")
        assert int(subprocess.check_output(cStrToCheck,
                                           shell=True).strip()) == 25000
        self.filenames += ["TinyDemo_R1.fastq.famstats.txt",
                           "TinyDemo_R1.shaded.BS.cons.fastq",
                           "TinyDemo_R1.shaded.BS.fastq",
                           "TinyDemo_R1.shaded.fastq",
                           "TinyDemo_R3.shaded.BS.cons.fastq",
                           "TinyDemo_R3.shaded.BS.fastq",
                           "TinyDemo_R3.shaded.fastq"]

    def test_sfc(self):
        singleFastqConsolidate("../data/TestR1.fastq")
        conFq = open("TestR1.cons.fastq")
        assert conFq.readlines() == ['@AAAAAATGGACCCATTAACC 1:N:0:ACAGTG|FP=I'
                                     'ndexPass|BS=AAAAAATGGACCCATTAACC|FM=3|N'
                                     'D=0|FA=3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,'
                                     '3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3'
                                     ',3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,'
                                     '3,3,3,3,3,3,3,3,3,3,3,3,3,3,3|PV=101,10'
                                     '2,102,101,102,114,111,114,111,113,106,1'
                                     '13,108,113,114,114,112,113,113,111,113,'
                                     '87,109,113,112,113,113,113,114,111,114,'
                                     '113,114,111,113,113,114,113,114,106,113'
                                     ',112,114,113,103,113,111,113,114,114,11'
                                     '4,112,110,111,113,113,114,114,110,112,1'
                                     '13,113,113,114,114,112,114,113,108,108'
                                     '\n',
                                     'AAATCGGGTCACTCCCACCTGAATACTGCGCTTTTCCGA'
                                     'TCGGCTTAAAAAATGGCGCACCACGAGATTA\n',
                                     '+\n', '~~~~~~~~~~~~~~~~~~~~~x~~~~~~~~'
                                     '~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~'
                                     '~\n']
        conFq.close()
        self.filenames.append("TestR1.cons.fastq")

    def test_famsizestats(self):
        """
        TODO: Test GetFamSizeStats
        """
        pass

if __name__ == '__main__':
    unittest.main()
