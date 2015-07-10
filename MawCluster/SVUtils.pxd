cimport cython
cimport numpy as np
cimport pysam.calignmentfile
from cython cimport bint
from utilBMF.HTSUtils cimport PysamToChrDict, cystr

ctypedef pysam.calignmentfile.AlignedSegment AlignedSegment_t

cpdef bint DSD_SV_Tag_Condition(AlignedSegment_t read1,
                                AlignedSegment_t read2,
                                object extraField=?)
cpdef bint MDC_SV_Tag_Condition(AlignedSegment_t read1,
                                AlignedSegment_t read2,
                                object extraField=?)
cpdef bint DSI_SV_Tag_Condition(AlignedSegment_t read1,
                                AlignedSegment_t read2,
                                object extraField=?)
cpdef bint ORS_SV_Tag_Condition(AlignedSegment_t read1,
                                AlignedSegment_t read2,
                                object extraField=?)
cpdef bint ORB_SV_Tag_Condition(AlignedSegment_t read1,
                                AlignedSegment_t read2,
                                list extraField=?)
cpdef bint MSS_SV_Tag_Condition(AlignedSegment_t read1,
                                AlignedSegment_t read2,
                                object extraField=?)
cdef bint cMSS_SV_Tag_Condition(AlignedSegment_t read1,
                                AlignedSegment_t read2)


cpdef bint MDC_SV_Tag_Condition(AlignedSegment_t read1,
                                AlignedSegment_t read2,
                                object extraField=?)
cdef bint cMDC_SV_Tag_Condition(AlignedSegment_t read1,
                                AlignedSegment_t read2)


cdef bint cORU_SV_Tag_Condition(AlignedSegment_t read1,
                                AlignedSegment_t read2)
cpdef bint ORU_SV_Tag_Condition(AlignedSegment_t read1,
                                AlignedSegment_t read2,
                                extraField=?)


cpdef bint LI_SV_Tag_Condition(AlignedSegment_t read1,
                               AlignedSegment_t read2,
                               int extraField=?)
cdef bint cLI_SV_Tag_Condition(AlignedSegment_t read1,
                               AlignedSegment_t read2,
                               int maxInsert=?)
