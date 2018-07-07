/*
 * =====================================================================================
 *
 *       Filename:  find_peaks.c
 *
 *        Purpose:  Routines for finding peaks in noisy data
 *
 *        Created:  03/07/17 02:25:07
 *       Revision:  none
 *       Compiler:  gcc
 *
 *         Author:  Calum Chamberlain
 *   Organization:  EQcorrscan
 *      Copyright:  EQcorrscan developers.
 *        License:  GNU Lesser General Public License, Version 3
 *                  (https://www.gnu.org/copyleft/lesser.html)
 *
 * =====================================================================================
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#if (defined(_MSC_VER))
    #include <float.h>
    #define isnanf(x) _isnan(x)
    #define inline __inline
#endif
#if (defined(__APPLE__) && !isnanf)
    #define isnanf isnan
#endif
#include <fftw3.h>
#if defined(__linux__) || defined(__linux) || defined(__APPLE__) || defined(__FreeBSD__) || defined(__OpenBSD__) || defined(__NetBSD__)
    #include <omp.h>
    #ifndef N_THREADS
        #define N_THREADS omp_get_max_threads()
    #endif
#endif
// Define minimum variance to compute correlations - requires some signal
#define ACCEPTED_DIFF 1e-15
// Define difference to warn user on
#define WARN_DIFF 1e-10

// find_peaks functions
int decluster(float*, long*, int, float, long, unsigned int*);

int findpeaks(float*, long, float);

int multi_find_peaks(float*, long, int, float*, int);

// multi_corr functions
int normxcorr_fftw(float*, long, long, float*, long, float*, long, int*, int*, int*);


int normxcorr_fftw_main(float*, long, long, float*, long, float*, long, float*, float*, float*,
        fftwf_complex*, fftwf_complex*, fftwf_complex*, fftwf_plan, fftwf_plan, fftwf_plan, int*, int*, int, int*);

int normxcorr_fftw_threaded(float*, long, long, float*, long, float*, long, int*, int*, int*);

void free_fftwf_arrays(int, float**, float**, float**, fftwf_complex**, fftwf_complex**, fftwf_complex**);

void free_fftw_arrays(int, double**, double**, double**, fftw_complex**, fftw_complex**, fftw_complex**);

int multi_normxcorr_fftw(float*, long, long, long, float*, long, float*, long, int*, int*, int, int, int*);

// time_corr functions
int normxcorr_time_threaded(float*, int, float*, int, float*, int);

int normxcorr_time(float*, int, float*, int, float*);

int multi_normxcorr_time(float*, int, int, float*, int, float*);

int multi_normxcorr_time_threaded(float*, int, int, float*, int, float*, int);