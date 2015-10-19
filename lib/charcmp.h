#ifndef CHARCMP_H
#define CHARCMP_H
//#include "branchlut.h"
/*
 * This is broken.
inline void comma_i32toa(int32_t value, char *buffer)
{
	*buffer++ = ',';
	i32toa_branchlut(value, buffer);
}
*/
/*
 * Small character comparison or conversion utilities.
 */


static inline int nuc2num(char character)
{
	switch(character) {
		case 'C': return 1; break;
		case 'G': return 2; break;
		case 'T': return 3; break;
		default: return 0; break; // 'A'
	}
}

#define NUC_CMPL(inchr, setchr)\
	switch(inchr) {\
		case 'A': setchr = 'T';break;\
		case 'C': setchr = 'G';break;\
		case 'G': setchr = 'C';break;\
		case 'T': setchr = 'A';break;\
		default: setchr = inchr;break;\
	}

static inline char nuc_cmpl(char character) {
	switch(character) {
		case 'A': return 'T';
		case 'C': return 'G';
		case 'G': return 'C';
		case 'T': return 'A';
		default: return character;
	}
}


static inline int nuc_cmp(char forward, char reverse)
{
	return forward - reverse;
}


//Converts a nucleotide in a char * into an index for the phred_sums and nuc_counts arrays.
static inline void nuc_to_pos(char character, int *nuc_indices)
{
	switch(character) {
		case 'A': nuc_indices[0] = 0; nuc_indices[1] = 0; return;
		case 'C': nuc_indices[0] = 1; nuc_indices[1] = 1; return;
		case 'G': nuc_indices[0] = 2; nuc_indices[1] = 2; return;
		case 'T': nuc_indices[0] = 3; nuc_indices[1] = 3; return;
		default: nuc_indices[0] = 0; nuc_indices[1] = 4; return;
	}
}

#endif