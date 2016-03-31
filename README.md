#BMFtools
###Summary
>BMFtools (**B**arcoded **M**olecular **F**amilies tools) is a suite of tools for barcoded reads which takes advantage of PCR redundancy for error reduction/elimination. The core functionality consists of **molecular** demultiplexing at fastq stage, producing a unique observation for each sequenced founded template molecule. Accessory tools provide postprocessing, filtering, quality control, and summary statistics

===================


### Installation

```bash
git clone https://github.com/ARUP-NGS/BMFtools --recursive
cd BMFtools
make
```

### Tools

Name | Use |
:---:|:----|
bmftools cap| Postprocess a tagged BAM for BMF-agnostic tools.|
bmftools depth| Calculates depth of coverage over a set of bed intervals.|
bmftools dmp| Demultiplex inline barcoded experiments.|
bmftools err| Calculate error rates based on cycle, base call, and quality score.|
bmftools famstats| Calculate family size statistics for a bam alignment file.|
bmftools filter| Filter or split a bam file by a set of filters.|
bmftools mark| Add unclipped start position as annotation for both read and mate.|
bmftools rsq| Rescue bmf-sorted or ucs-sorted bam alignments.|
bmftools sdmp| Demultiplex secondary-index barcoded experiments.|
bmftools sort| Sort for bam rescue.|
bmftools stack| A maximally-permissive yet statistically-thorough variant caller using molecular barcode metadata.|
bmftools target| Calculates on-target rate.|
bmftools vet| Curate variant calls from another variant caller (.vcf) and a bam alignment.|

These tools are divided into four categories:
  1. Core functionality
  2. Manipulation
  3. Analysis
  4. Utilities


### Core Functionality

####bmftools dmp/sdmp
bmftools dmp and sdmp perform **molecular** demultiplexing of barcoded experiments, for inline and secondary index chemistries, respectively.

First, these tools add the barcodes to the comment fields of the fastqs and split the records into subsets based on the first characters in the barcode.
Then, reads with exactly-matching barcode are collapsed into a unique observation, with a meta-analysis performed on each base call.

Since there can be errors in reading the barcode,
`bmftools rsq` is made available for using positional information to rescue reads with mismatches into their proper families.

bmftools dmp collapses templates where both strands were sequenced, whereas sdmp lacks strand information.

Note: It is **STRONGLY** recommended that for the secondary-index chemistry that you mask adapter sequence in the molecular barcode reads.
When the secondary-index barcode read consists primarily or entirely of adapter, this informs us that the chemistry did not perform as expected.
This preprocessing will "N" those bases, marking the reads as QC fail with the FP integer tag (0 for fail, 1 for pass).

####bmftools rsq
Uses positional information to collapse reads with the same alignment signatures (start/stop/

### Manipulation

####bmftools cap
Caps quality scores from PV tags to facilitate working with barcode-agnostic tools.

####bmftools filter
Filters or splits a bam file based on a set of filters.

Filters:
Fail reads with insufficient mapping quality.
Fail reads with insufficient family size.
Fail read pairs where both .
Fail reads outside of a bed region.
Fail reads with a family size below given parameter.
Fail reads without all bits in given parameter in the sam flag field.
Fail reads with any bits in given parameter in the sam flag field.

####bmftools vet

### Analysis

####bmftools depth
####bmftools target
####bmftools err
####bmftools famstats
####bmftools stack

### Utilities

####bmftools mark
####bmftools sort


Name | Use |
:---:|:----|
bmftools cap| Postprocess a tagged BAM for BMF-agnostic tools.|
bmftools depth| Calculates depth of coverage over a set of bed intervals.|
bmftools dmp| Demultiplex inline barcoded experiments.|
bmftools err| Calculate error rates based on cycle, base call, and quality score.|
bmftools famstats| Calculate family size statistics for a bam alignment file.|
bmftools filter| Filter or split a bam file by a set of filters.|
bmftools mark| Add unclipped start position as annotation for both read and mate.|
bmftools rsq| Rescue bmf-sorted or ucs-sorted bam alignments.|
bmftools sdmp| Demultiplex secondary-index barcoded experiments.|
bmftools sort| Sort for bam rescue.|
bmftools stack| A simple variant caller using molecular barcode metadata.|
bmftools target| Calculates on-target rate.|
bmftools vet| Curate variant calls from another variant caller (.vcf) and a bam alignment.|


### Use

```bash
bmftools
```

```bash
bmftools <--help/-h>
```

```bash
bmftools <subcommand> <-h>
```


## BMF Tags

Tag | Content | Format |
:----:|:-----|:-----:|
AF | Aligned Fraction aligned (fraction of bases mapped to reference bases, not counting IDSHNP operations. | Float |
DR | Whether the read was sequenced from both strands. Only valid for Loeb-like inline barcodes. | Integer [0, 1] |
FA | Number of reads in Family which Agreed with final sequence at each base | Comma-separated list of integers. Regex: [0-9,]+ |
FM | Size of family (number of reads sharing barcode.), e.g., "Family Members" | Integer |
FP | Read Passes Filter related to barcoding. Determines QC fail flag in bmftools mark (without -q).| Integer [0, 1]|
MF | Mate fraction aligned (fraction of bases mapped to reference bases, not counting IDSHNP operations. | Float |
mc | Mate soft-clipped length | Integer |
NC | Number of changed bases in rescued families of reads. | Integer |
NF | Mean number of differences between reads and consensus per read in family | Single-precision floating number |
PV | Phred Values for a read which has saturated the phred scoring system | uint32_t array |
RV | Number of reversed reads in consensus. Only for Loeb-style inline chemistry. | Integer |
SC | Soft-clipped length | Integer |

## Barcoding methods

Essentially, the process is *molecular* **d**e**m**ulti**p**lexing.

####Secondary Index Barcoding 
Requires read fastqs and an additional fastq containing barcodes.
> bmftools sdmp

(Secondary-index DeMultiPlex)

