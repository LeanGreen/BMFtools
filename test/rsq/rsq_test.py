import sys
import subprocess
try:
    import pysam
except ImportError:
    sys.stderr.write("Could not import pysam. Not running tests.\n")
    sys.exit(0)
correct_string = "@CCATAATAACGCCAGTAT PV:B:I,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,104,98,78,93,104,98,79,104,79,78,91,93,102,91,78,79,93,93,98,79,104,104,104,93,93,79,79,79,93,93,93,104,104,79,79,98,104,104,104,104,98,102,78,79,79,93,79,93,96,79,91,102,98,93,79,93,93,78,91,91,93,98,78,79,91,91,91,78,79,79,104,98,102,93,93,96,91,93,93,98,79,93,79,91,104,76,76,78,104,79,93,93,79,78,91,78,79,91,78,79,93,102,104,104,102,79,91,91,104,61,65,65,67,67,67,67,67,67,67,67,26\tFA:B:I,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3\tFM:i:3\tFP:i:1\tRV:i:1\tNC:i:0\tNP:i:2\tDR:i:1\nNNNNNNNNNNNNNNNNAGCCTTGTGTTTCTGACAATATATTCTTCAACAGCAGCTAGAAAGTTGGTTCAAACCAACTTTTAATATACAGTAGTTCTTTTCATTTACATTTCAAAATATTTAACAAAGTCAAACTTTC\n+\n################IIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIIGGIIIIIIIIIIIIIIIIIIIIIIIGGIIIIIIIIA"
def main():
    subprocess.check_call("../../bmftools_db rsq -ftmp.fq rsq_test.bam rsq_test.out.bam 2> rsq_test.log", shell=True)
    try:
        assert(subprocess.check_output("samtools view -c rsq_test.out.bam", shell=True).strip() == "0")
    except AssertionError:
        assert(subprocess.check_output("samtools view -c rsq_test.out.bam", shell=True).strip().decode() == "0")
    recs = list(pysam.FastqFile("tmp.fq"))
    assert len(recs) == 2
    try:
        assert str(recs[0]) == correct_string
        return 0
    except AssertionError:
        sys.stderr.write("%s found not expected %s. TEST FAILED\n" % (repr(str(recs[0])), repr(correct_string)))
        return 1


if __name__ == "__main__":
    sys.exit(main())
