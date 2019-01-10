"""
Utilities module whose functions are designed to do the basic processing of
the data using obspy modules (which also rely on scipy and numpy).

:copyright:
    EQcorrscan developers.

:license:
    GNU Lesser General Public License, Version 3
    (https://www.gnu.org/copyleft/lesser.html)
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import numpy as np
import logging
import datetime as dt

from collections import Counter
from multiprocessing import Pool, cpu_count

from obspy import Stream, Trace, UTCDateTime
from obspy.signal.filter import bandpass, lowpass, highpass


Logger = logging.getLogger(__name__)


def _check_daylong(tr):
    """
    Check the data quality of the daylong file.

    Check to see that the day isn't just zeros, with large steps, if it is
    then the resampling will hate it.

    :type tr: obspy.core.trace.Trace
    :param tr: Trace to check if the data are daylong.

    :return quality (simply good or bad)
    :rtype: bool

    .. rubric:: Example

    >>> from obspy import read
    >>> from eqcorrscan.utils.pre_processing import _check_daylong
    >>> # Get the path to the test data
    >>> import eqcorrscan
    >>> import os
    >>> TEST_PATH = os.path.dirname(eqcorrscan.__file__) + '/tests/test_data'
    >>> st = read(TEST_PATH + '/WAV/TEST_/' +
    ...           '2013-09-01-0410-35.DFDPC_024_00')
    >>> _check_daylong(st[0])
    True
    """
    if len(np.nonzero(tr.data)[0]) < 0.5 * len(tr.data):
        qual = False
    else:
        qual = True
    return qual


def shortproc(st, lowcut, highcut, filt_order, samp_rate, parallel=False,
              num_cores=False, starttime=None, endtime=None,
              seisan_chan_names=False, fill_gaps=True):
    """
    Basic function to bandpass and downsample.

    Works in place on data.  This is employed to ensure all parts of the
    data are processed in the same way.

    :type st: obspy.core.stream.Stream
    :param st: Stream to process
    :type lowcut: float
    :param lowcut: Low cut for bandpass in Hz
    :type highcut: float
    :param highcut: High cut for bandpass in Hz
    :type filt_order: int
    :param filt_order: Number of corners for bandpass filter
    :type samp_rate: float
    :param samp_rate: Sampling rate desired in Hz
    :type parallel: bool
    :param parallel:
        Set to True to process traces in parallel, for small numbers of traces
        this is often slower than serial processing, defaults to False
    :type num_cores: int
    :param num_cores:
        Control the number of cores for parallel processing, if set to False
        then this will use all the cores available.
    :type starttime: obspy.core.utcdatetime.UTCDateTime
    :param starttime:
        Desired data start time, will trim to this before processing
    :type endtime: obspy.core.utcdatetime.UTCDateTime
    :param endtime:
        Desired data end time, will trim to this before processing
    :type seisan_chan_names: bool
    :param seisan_chan_names:
        Whether channels are named like seisan channels (which are two letters
        rather than SEED convention of three) - defaults to True.
    :type fill_gaps: bool
    :param fill_gaps: Whether to pad any gaps found with zeros or not.

    :return: Processed stream
    :rtype: :class:`obspy.core.stream.Stream`

    .. note::
        If your data contain gaps you should *NOT* fill those gaps before
        using the pre-process functions. The pre-process functions will fill
        the gaps internally prior to processing, process the data, then re-fill
        the gaps with zeros to ensure correlations are not incorrectly
        calculated within gaps. If your data have gaps you should pass a merged
        stream without the `fill_value` argument (e.g.: `st = st.merge()`).

    .. warning::
        If you intend to use this for processing templates you should consider
        how resampling will impact your cross-correlations. Minor differences
        in resampling between day-long files (which you are likely to use for
        continuous detection) and shorter files will reduce your
        cross-correlations!

    .. rubric:: Example, bandpass

    >>> from obspy import read
    >>> from eqcorrscan.utils.pre_processing import shortproc
    >>> # Get the path to the test data
    >>> import eqcorrscan
    >>> import os
    >>> TEST_PATH = os.path.dirname(eqcorrscan.__file__) + '/tests/test_data'
    >>> st = read(TEST_PATH + '/WAV/TEST_/2013-09-01-0410-35.DFDPC_024_00')
    >>> st = shortproc(st=st, lowcut=2, highcut=9, filt_order=3, samp_rate=20,
    ...                parallel=True, num_cores=2)
    >>> print(st[0])
    AF.LABE..SHZ | 2013-09-01T04:10:35.700000Z - 2013-09-01T04:12:05.650000Z \
| 20.0 Hz, 1800 samples

    .. rubric:: Example, low-pass

    >>> from obspy import read
    >>> from eqcorrscan.utils.pre_processing import shortproc
    >>> # Get the path to the test data
    >>> import eqcorrscan
    >>> import os
    >>> TEST_PATH = os.path.dirname(eqcorrscan.__file__) + '/tests/test_data'
    >>> st = read(TEST_PATH + '/WAV/TEST_/2013-09-01-0410-35.DFDPC_024_00')
    >>> st = shortproc(st=st, lowcut=None, highcut=9, filt_order=3,
    ...                samp_rate=20)
    >>> print(st[0])
    AF.LABE..SHZ | 2013-09-01T04:10:35.700000Z - 2013-09-01T04:12:05.650000Z \
| 20.0 Hz, 1800 samples

    .. rubric:: Example, high-pass

    >>> from obspy import read
    >>> from eqcorrscan.utils.pre_processing import shortproc
    >>> # Get the path to the test data
    >>> import eqcorrscan
    >>> import os
    >>> TEST_PATH = os.path.dirname(eqcorrscan.__file__) + '/tests/test_data'
    >>> st = read(TEST_PATH + '/WAV/TEST_/2013-09-01-0410-35.DFDPC_024_00')
    >>> st = shortproc(st=st, lowcut=2, highcut=None, filt_order=3,
    ...                samp_rate=20)
    >>> print(st[0])
    AF.LABE..SHZ | 2013-09-01T04:10:35.700000Z - 2013-09-01T04:12:05.650000Z \
| 20.0 Hz, 1800 samples
    """
    if isinstance(st, Trace):
        tracein = True
        st = Stream(st)
    else:
        tracein = False
    # Add sanity check for filter
    if highcut and highcut >= 0.5 * samp_rate:
        raise IOError('Highcut must be lower than the nyquist')
    length = None
    clip = False
    if starttime is not None and endtime is not None:
        for tr in st:
            tr.trim(starttime, endtime)
            if len(tr.data) == ((endtime - starttime) *
                                tr.stats.sampling_rate) + 1:
                tr.data = tr.data[1:len(tr.data)]
        length = endtime - starttime
        clip = True
    elif starttime:
        for tr in st:
            tr.trim(starttime=starttime)
    elif endtime:
        for tr in st:
            tr.trim(endtime=endtime)
    for tr in st:
        if len(tr.data) == 0:
            st.remove(tr)
            Logger.warning('No data for {0} after trim'.format(tr.id))
    if parallel:
        if not num_cores:
            num_cores = cpu_count()
        if num_cores > len(st):
            num_cores = len(st)
        pool = Pool(processes=num_cores)
        results = [pool.apply_async(process, (tr,), {
            'lowcut': lowcut, 'highcut': highcut, 'filt_order': filt_order,
            'samp_rate': samp_rate, 'starttime': starttime,
            'clip': clip, 'seisan_chan_names': seisan_chan_names,
            'fill_gaps': fill_gaps, 'length': length})
                   for tr in st]
        pool.close()
        try:
            stream_list = [p.get() for p in results]
        except KeyboardInterrupt as e:  # pragma: no cover
            pool.terminate()
            raise e
        pool.join()
        st = Stream(stream_list)
    else:
        for i, tr in enumerate(st):
            st[i] = process(
                tr=tr, lowcut=lowcut, highcut=highcut, filt_order=filt_order,
                samp_rate=samp_rate, starttime=starttime,
                clip=clip, seisan_chan_names=seisan_chan_names,
                fill_gaps=fill_gaps, length=length)
    if tracein:
        st.merge()
        return st[0]
    return st


def dayproc(st, lowcut, highcut, filt_order, samp_rate, starttime,
            parallel=True, num_cores=False, ignore_length=False,
            seisan_chan_names=False, fill_gaps=True):
    """
    Wrapper for dayproc to parallel multiple traces in a stream.

    Works in place on data.  This is employed to ensure all parts of the data \
    are processed in the same way.

    :type st: obspy.core.stream.Stream
    :param st: Stream to process (can be trace).
    :type lowcut: float
    :param lowcut: Low cut in Hz for bandpass.
    :type highcut: float
    :param highcut: High cut in Hz for bandpass.
    :type filt_order: int
    :param filt_order: Corners for bandpass.
    :type samp_rate: float
    :param samp_rate: Desired sampling rate in Hz.
    :type starttime: obspy.core.utcdatetime.UTCDateTime
    :param starttime: Desired start-date of trace.
    :type parallel: bool
    :param parallel:
        Set to True to process traces in parallel, this is often faster than
        serial processing of traces: defaults to True.
    :type num_cores: int
    :param num_cores:
        Control the number of cores for parallel processing, if set to False
        then this will use all the cores.
    :type ignore_length: bool
    :param ignore_length: See warning below.
    :type seisan_chan_names: bool
    :param seisan_chan_names:
        Whether channels are named like seisan channels (which are two letters
        rather than SEED convention of three) - defaults to True.
    :type fill_gaps: bool
    :param fill_gaps: Whether to pad any gaps found with zeros or not.

    :return: Processed stream.
    :rtype: :class:`obspy.core.stream.Stream`

    .. note::
        If your data contain gaps you should *NOT* fill those gaps before
        using the pre-process functions. The pre-process functions will fill
        the gaps internally prior to processing, process the data, then re-fill
        the gaps with zeros to ensure correlations are not incorrectly
        calculated within gaps. If your data have gaps you should pass a merged
        stream without the `fill_value` argument (e.g.: `st = st.merge()`).

    .. warning::
        Will fail if data are less than 19.2 hours long - this number is
        arbitrary and is chosen to alert the user to the dangers of padding
        to day-long, if you don't care you can ignore this error by setting
        `ignore_length=True`. Use this option at your own risk!  It will also
        warn any-time it has to pad data - if you see strange artifacts in your
        detections, check whether the data have gaps.

    .. rubric:: Example

    >>> import obspy
    >>> if int(obspy.__version__.split('.')[0]) >= 1:
    ...     from obspy.clients.fdsn import Client
    ... else:
    ...     from obspy.fdsn import Client
    >>> from obspy import UTCDateTime
    >>> from eqcorrscan.utils.pre_processing import dayproc
    >>> client = Client('NCEDC')
    >>> t1 = UTCDateTime(2012, 3, 26)
    >>> t2 = t1 + 86400
    >>> bulk_info = [('BP', 'JCNB', '40', 'SP1', t1, t2)]
    >>> st = client.get_waveforms_bulk(bulk_info)
    >>> st_keep = st.copy()  # Copy the stream for later examples
    >>> # Example of bandpass filtering
    >>> st = dayproc(st=st, lowcut=2, highcut=9, filt_order=3, samp_rate=20,
    ...              starttime=t1, parallel=True, num_cores=2)
    >>> print(st[0])
    BP.JCNB.40.SP1 | 2012-03-26T00:00:00.000000Z - 2012-03-26T23:59:59.\
950000Z | 20.0 Hz, 1728000 samples
    >>> # Example of lowpass filtering
    >>> st = dayproc(st=st, lowcut=None, highcut=9, filt_order=3, samp_rate=20,
    ...              starttime=t1, parallel=True, num_cores=2)
    >>> print(st[0])
    BP.JCNB.40.SP1 | 2012-03-26T00:00:00.000000Z - 2012-03-26T23:59:59.\
950000Z | 20.0 Hz, 1728000 samples
    >>> # Example of highpass filtering
    >>> st = dayproc(st=st, lowcut=2, highcut=None, filt_order=3, samp_rate=20,
    ...              starttime=t1, parallel=True, num_cores=2)
    >>> print(st[0])
    BP.JCNB.40.SP1 | 2012-03-26T00:00:00.000000Z - 2012-03-26T23:59:59.\
950000Z | 20.0 Hz, 1728000 samples
    """
    # Add sanity check for filter
    if isinstance(st, Trace):
        st = Stream(st)
        tracein = True
    else:
        tracein = False
    if highcut and highcut >= 0.5 * samp_rate:
        raise IOError('Highcut must be lower than the nyquist')
    # Set the start-time to a day start - cope with
    if starttime is None:
        startdates = []
        for tr in st:
            if abs(tr.stats.starttime - (UTCDateTime(
                    tr.stats.starttime.date) + 86400)) < tr.stats.delta:
                # If the trace starts within 1 sample of the next day, use the
                # next day as the startdate
                startdates.append((tr.stats.starttime + 86400).date)
                Logger.warning(
                    '{0} starts within 1 sample of the next day, using this '
                    'time {1}'.format(
                        tr.id, (tr.stats.starttime + 86400).date))
            else:
                startdates.append(tr.stats.starttime.date)
        # Check that all traces start on the same date...
        if not len(set(startdates)) == 1:
            raise NotImplementedError('Traces start on different days')
        starttime = UTCDateTime(startdates[0])
    if parallel:
        if not num_cores:
            num_cores = cpu_count()
        if num_cores > len(st):
            num_cores = len(st)
        pool = Pool(processes=num_cores)
        results = [pool.apply_async(process, (tr,), {
            'lowcut': lowcut, 'highcut': highcut, 'filt_order': filt_order,
            'samp_rate': samp_rate, 'starttime': starttime, 'clip': True,
            'ignore_length': ignore_length, 'length': 86400,
            'seisan_chan_names': seisan_chan_names, 'fill_gaps': fill_gaps})
                   for tr in st]
        pool.close()
        try:
            stream_list = [p.get() for p in results]
        except KeyboardInterrupt as e:  # pragma: no cover
            pool.terminate()
            raise e
        pool.join()
        st = Stream(stream_list)
    else:
        for i, tr in enumerate(st):
            st[i] = process(
                tr=tr, lowcut=lowcut, highcut=highcut, filt_order=filt_order,
                samp_rate=samp_rate, starttime=starttime, clip=True,
                length=86400, ignore_length=ignore_length,
                seisan_chan_names=seisan_chan_names, fill_gaps=fill_gaps)
    for tr in st:
        if len(tr.data) == 0:
            st.remove(tr)
    if tracein:
        st.merge()
        return st[0]
    return st


def process(tr, lowcut, highcut, filt_order, samp_rate,
            starttime=False, clip=False, length=86400,
            seisan_chan_names=False, ignore_length=False, fill_gaps=True):
    """
    Basic function to process data, usually called by dayproc or shortproc.

    Functionally, this will bandpass, downsample and check headers and length
    of trace to ensure files start when they should and are the correct length.
    This is a simple wrapper on obspy functions, we include it here to provide
    a system to ensure all parts of the dataset are processed in the same way.

    .. note:: Usually this function is called via dayproc or shortproc.

    :type tr: obspy.core.trace.Trace
    :param tr: Trace to process
    :type lowcut: float
    :param lowcut: Low cut in Hz, if set to None and highcut is set, will use \
        a lowpass filter.
    :type highcut: float
    :param highcut: High cut in Hz, if set to None and lowcut is set, will \
        use a highpass filter.
    :type filt_order: int
    :param filt_order: Number of corners for filter.
    :type samp_rate: float
    :param samp_rate: Desired sampling rate in Hz.
    :type starttime: obspy.core.utcdatetime.UTCDateTime
    :param starttime: Desired start of trace
    :type clip: bool
    :param clip: Whether to expect, and enforce a set length of data or not.
    :type length: float
    :param length: Use to set a fixed length for data from the given starttime.
    :type seisan_chan_names: bool
    :param seisan_chan_names:
        Whether channels are named like seisan channels (which are two letters
        rather than SEED convention of three) - defaults to True.
    :type ignore_length: bool
    :param ignore_length: See warning in dayproc.
    :type fill_gaps: bool
    :param fill_gaps: Whether to pad any gaps found with zeros or not.

    :return: Processed trace.
    :type: :class:`obspy.core.stream.Trace`

    .. note::
        If your data contain gaps you should *NOT* fill those gaps before
        using the pre-process functions. The pre-process functions will fill
        the gaps internally prior to processing, process the data, then re-fill
        the gaps with zeros to ensure correlations are not incorrectly
        calculated within gaps. If your data have gaps you should pass a merged
        stream without the `fill_value` argument (e.g.: `tr = tr.merge()`).
    """
    # Add sanity check
    if highcut and highcut >= 0.5 * samp_rate:
        raise IOError('Highcut must be lower than the nyquist')

    # Define the start-time
    if starttime:
        # Be nice and allow a datetime object.
        if isinstance(starttime, dt.date) or isinstance(starttime,
                                                        dt.datetime):
            starttime = UTCDateTime(starttime)

    Logger.debug('Working on: {0}'.format(tr.id))
    # Check if the trace is gappy and pad if it is.
    gappy = False
    if isinstance(tr.data, np.ma.MaskedArray):
        gappy = True
        gaps, tr = _fill_gaps(tr)
    # Do a brute force quality check
    qual = _check_daylong(tr)
    if not qual:
        msg = ("Data have more zeros than actual data, please check the raw",
               " data set-up and manually sort it: " + tr.stats.station + "." +
               tr.stats.channel)
        raise ValueError(msg)
    tr = tr.detrend('simple')
    # Detrend data before filtering
    Logger.debug('I have {0} data points for {1} before processing'.format(
        tr.stats.npts, tr.id))

    # Sanity check to ensure files are daylong
    padded = False
    if clip:
        tr = tr.trim(starttime, starttime + length, nearest_sample=True)
    if float(tr.stats.npts / tr.stats.sampling_rate) != length and clip:
        Logger.info(
            'Data for {0} are not of daylong length, will zero pad'.format(
                tr.id))
        if tr.stats.endtime - tr.stats.starttime < 0.8 * length\
           and not ignore_length:
            raise NotImplementedError(
                "Data for {0}.{1} is {2:.2f} seconds long, which is less than "
                "80 percent of the desired length ({3} seconds), will not "
                "pad".format(
                    tr.stats.station, tr.stats.channel,
                    tr.stats.endtime - tr.stats.starttime, length))
        # trim, then calculate length of any pads required
        pre_pad_secs = tr.stats.starttime - starttime
        post_pad_secs = (starttime + length) - tr.stats.endtime
        if pre_pad_secs > 0 or post_pad_secs > 0:
            padded = True
            pre_pad = np.zeros(int(pre_pad_secs * tr.stats.sampling_rate))
            post_pad = np.zeros(int(post_pad_secs * tr.stats.sampling_rate))
            Logger.debug(str(tr))
            Logger.debug("Padding to day long with {0} s before and {1} s "
                         "at end".format(pre_pad_secs, post_pad_secs))
            tr.data = np.concatenate([pre_pad, tr.data, post_pad])
            # Use this rather than the expected pad because of rounding samples
            tr.stats.starttime -= len(pre_pad) * tr.stats.delta
            Logger.debug(str(tr))
        # If there is one sample too many after this remove the first one
        # by convention
        if len(tr.data) == (length * tr.stats.sampling_rate) + 1:
            tr.data = tr.data[1:len(tr.data)]
        if not tr.stats.sampling_rate * length == tr.stats.npts:
                raise ValueError('Data are not daylong for ' +
                                 tr.stats.station + '.' + tr.stats.channel)
        Logger.debug(
            'I now have {0} data points after enforcing length'.format(
                tr.stats.npts))
    # Check sampling rate and resample
    if tr.stats.sampling_rate != samp_rate:
        Logger.debug('Resampling')
        tr.resample(samp_rate)
    # Filtering section
    tr = tr.detrend('simple')    # Detrend data again before filtering
    if highcut and lowcut:
        Logger.debug('Bandpassing')
        tr.data = bandpass(tr.data, lowcut, highcut,
                           tr.stats.sampling_rate, filt_order, True)
    elif highcut:
        Logger.debug('Lowpassing')
        tr.data = lowpass(tr.data, highcut, tr.stats.sampling_rate,
                          filt_order, True)
    elif lowcut:
        Logger.debug('Highpassing')
        tr.data = highpass(tr.data, lowcut, tr.stats.sampling_rate,
                           filt_order, True)
    else:
        Logger.warning('No filters applied')
    # Account for two letter channel names in s-files and therefore templates
    if seisan_chan_names:
        tr.stats.channel = tr.stats.channel[0] + tr.stats.channel[-1]

    if padded:
        Logger.debug("Reapplying zero pads post processing")
        Logger.debug(str(tr))
        pre_pad = np.zeros(int(pre_pad_secs * tr.stats.sampling_rate))
        post_pad = np.zeros(int(post_pad_secs * tr.stats.sampling_rate))
        pre_pad_len = len(pre_pad)
        post_pad_len = len(post_pad)
        Logger.debug(
            "Taking only valid data between {0} and {1} samples".format(
                pre_pad_len, tr.stats.npts - post_pad_len))
        # Re-apply the pads, taking only the data section that was valid
        tr.data = np.concatenate(
            [pre_pad, tr.data[pre_pad_len: len(tr.data) - post_pad_len],
             post_pad])
        Logger.debug(str(tr))
    # Sanity check to ensure files are daylong
    if float(tr.stats.npts / tr.stats.sampling_rate) != length and clip:
        Logger.info(
            'Data for {0} are not of daylong length, will zero pad'.format(
                tr.id))
        # Use obspy's trim function with zero padding
        tr = tr.trim(starttime, starttime + length, pad=True, fill_value=0,
                     nearest_sample=True)
        # If there is one sample too many after this remove the last one
        # by convention
        if len(tr.data) == (length * tr.stats.sampling_rate) + 1:
            tr.data = tr.data[1:len(tr.data)]
        if not tr.stats.sampling_rate * length == tr.stats.npts:
                raise ValueError('Data are not daylong for ' +
                                 tr.stats.station + '.' + tr.stats.channel)
    # Replace the gaps with zeros
    if gappy:
        tr = _zero_pad_gaps(tr, gaps, fill_gaps=fill_gaps)
    return tr


def _zero_pad_gaps(tr, gaps, fill_gaps=True):
    """
    Replace padded parts of trace with zeros.

    Will cut around gaps, detrend, then pad the gaps with zeros.

    :type tr: :class:`osbpy.core.stream.Trace`
    :param tr: A trace that has had the gaps padded
    :param gaps: List of dict of start-time and end-time as UTCDateTime objects
    :type gaps: list

    :return: :class:`obspy.core.stream.Trace`
    """
    start_in, end_in = (tr.stats.starttime, tr.stats.endtime)
    for gap in gaps:
        stream = Stream()
        if gap['starttime'] > tr.stats.starttime:
            stream += tr.slice(tr.stats.starttime, gap['starttime']).copy()
        if gap['endtime'] < tr.stats.endtime:
            # Note this can happen when gaps are calculated for a trace that
            # is longer than `length`, e.g. gaps are calculated pre-trim.
            stream += tr.slice(gap['endtime'], tr.stats.endtime).copy()
        tr = stream.merge()[0]
    if fill_gaps:
        tr = tr.split()
        tr = tr.detrend()
        tr = tr.merge(fill_value=0)[0]
        # Need to check length - if a gap happened overlapping the end or start
        #  of the trace this will be lost.
        if tr.stats.starttime != start_in:
            # pad with zeros
            tr.data = np.concatenate(
                [np.zeros(int(tr.stats.starttime - start_in)), tr.data])
            tr.stats.starttime = start_in
        if tr.stats.endtime != end_in:
            tr.data = np.concatenate(
                [tr.data, np.zeros(int(end_in - tr.stats.endtime))])
    return tr


def _fill_gaps(tr):
    """
    Interpolate through gaps and work-out where gaps are.

    :param tr: Gappy trace (e.g. tr.data is np.ma.MaskedArray)
    :type tr: `obspy.core.stream.Trace`

    :return: gaps, trace, where gaps is a list of dict
    """
    tr = tr.split()
    gaps = tr.get_gaps()
    tr = tr.detrend().merge(fill_value=0)[0]
    gaps = [{'starttime': gap[4], 'endtime': gap[5]} for gap in gaps]
    return gaps, tr


def _prep_data_for_correlation(stream, templates, template_names=None,
                               force_stream_epoch=True):
    """
    Check that all channels are the same length and that all channels have data
    for both template and stream.

    Works in place on data - will cut to shortest length

    :param stream: Stream to compare data to
    :param templates:
        List of streams that will be forced to have the same channels as stream
    :param template_names:
        List of strings same length as templates
    :type force_stream_epoch: bool
    :param force_stream_epoch:
        Whether to force all channels in stream to cover the same time period

    :return: stream, templates, template_names (if template_names given)
    """
    from copy import deepcopy

    unnamed = False
    if template_names is None:
        template_names = list(range(len(templates)))
        unnamed = True

    # Check that all sampling rates are the same
    samp_rate = stream[0].stats.sampling_rate
    for tr in stream:
        if not tr.stats.sampling_rate == samp_rate:
            raise NotImplementedError("Sampling rates differ")
    for template in templates:
        for tr in template:
            if not tr.stats.sampling_rate == samp_rate:
                raise NotImplementedError("Sampling rates differ")
    # Perform a check that the continuous data are all the same length
    if force_stream_epoch:
        min_start_time = min([tr.stats.starttime for tr in stream])
        max_end_time = max([tr.stats.endtime for tr in stream])
        longest_trace_length = (
                stream[0].stats.sampling_rate * (max_end_time - min_start_time))
        longest_trace_length += 1
    else:
        longest_trace_length = max([tr.stats.npts for tr in stream])
    for tr in stream:
        if not tr.stats.npts == longest_trace_length:
            Logger.info(
                'Data for {0} is not as long as needed, padding'.format(tr.id))
            if force_stream_epoch:
                start_pad = np.zeros(
                    int(tr.stats.sampling_rate *
                        (tr.stats.starttime - min_start_time)))
                end_pad = np.zeros(
                    int(tr.stats.sampling_rate *
                        (max_end_time - tr.stats.endtime)))
                # In some cases there will be one sample missing when sampling
                # time-stamps are not set consistently between channels, this
                # results in start_pad and end_pad being len==0
                if len(start_pad) == 0 and len(end_pad) == 0:
                    Logger.debug(
                        "start and end pad are both zero, padding at one end")
                    if (tr.stats.starttime - min_start_time) > (
                       max_end_time - tr.stats.endtime):
                        start_pad = np.zeros(
                            int(longest_trace_length - tr.stats.npts))
                    else:
                        end_pad = np.zeros(
                            int(longest_trace_length - tr.stats.npts))
                tr.stats.starttime -= len(start_pad) / tr.stats.sampling_rate
            else:
                start_pad = np.zeros(0)
                end_pad = np.zeros(longest_trace_length - tr.stats.npts)
            tr.data = np.concatenate([start_pad, tr.data, end_pad])
    # Perform check that all template lengths are internally consistent
    for i, temp in enumerate(templates):
        if len(set([tr.stats.npts for tr in temp])) > 1:
            msg = ('Template %s contains traces of differing length, this is '
                   'not currently supported' % template_names[i])
            raise NotImplementedError(msg)
    Logger.debug('Ensuring all template channels have matches in'
                 ' continuous data')
    template_stachan = {}
    # Work out what station-channel pairs are in the templates, including
    # duplicate station-channel pairs.  We will use this information to fill
    # all templates with the same station-channel pairs
    for template in templates:
        stachans_in_template = []
        for tr in template:
            stachans_in_template.append((tr.stats.network, tr.stats.station,
                                         tr.stats.location, tr.stats.channel))
        stachans_in_template = dict(Counter(stachans_in_template))
        for stachan in stachans_in_template.keys():
            stachans = stachans_in_template[stachan]
            if stachan not in template_stachan.keys():
                template_stachan.update({stachan: stachans})
            elif stachans_in_template[stachan] > template_stachan[stachan]:
                template_stachan.update({stachan: stachans})
    # Remove un-matched channels from templates.
    _template_stachan = deepcopy(template_stachan)
    for stachan in template_stachan.keys():
        if not stream.select(network=stachan[0], station=stachan[1],
                             location=stachan[2], channel=stachan[3]):
            # Remove stachan from list of dictionary of template_stachans
            _template_stachan.pop(stachan)
            Logger.info('Removing template channel {0}.{1}.{2}.{3} due to'
                        ' no matches in continuous data'.format(
                            stachan[0], stachan[1], stachan[2], stachan[3]))
            # Remove template traces rather than adding NaN data
            for template in templates:
                if template.select(network=stachan[0], station=stachan[1],
                                   location=stachan[2], channel=stachan[3]):
                    for tr in template.select(
                            network=stachan[0], station=stachan[1],
                            location=stachan[2], channel=stachan[3]):
                        template.remove(tr)
    template_stachan = _template_stachan
    # Remove un-needed channels from continuous data.
    for tr in stream:
        if not (tr.stats.network, tr.stats.station,
                tr.stats.location, tr.stats.channel) in \
                template_stachan.keys():
            Logger.info(
                'Removing channel in continuous data for %s:'
                ' no match in template' % (tr.id))
            stream.remove(tr)
    # Check for duplicate channels
    stachans = [(tr.stats.network, tr.stats.station,
                 tr.stats.location, tr.stats.channel) for tr in stream]
    c_stachans = Counter(stachans)
    for key in c_stachans.keys():
        if c_stachans[key] > 1:
            msg = ('Multiple channels for %s.%s.%s.%s, likely a data issue'
                   % (key[0], key[1], key[2], key[3]))
            raise IOError(msg)
    # Pad out templates to have all channels
    _templates = []
    used_template_names = []
    for template, template_name in zip(templates, template_names):
        if len(template) == 0:
            msg = ('No channels matching in continuous data for ' +
                   'template' + template_name)
            Logger.warning(msg)
            continue
        for stachan in template_stachan.keys():
            number_of_channels = len(template.select(
                network=stachan[0], station=stachan[1], location=stachan[2],
                channel=stachan[3]))
            if number_of_channels < template_stachan[stachan]:
                missed_channels = template_stachan[stachan] - \
                                  number_of_channels
                nulltrace = Trace()
                nulltrace.stats.update(
                    {'network': stachan[0], 'station': stachan[1],
                     'location': stachan[2], 'channel': stachan[3],
                     'sampling_rate': template[0].stats.sampling_rate,
                     'starttime': template[0].stats.starttime,
                     'not_in_original': True})
                nulltrace.data = np.array([np.NaN] * len(template[0].data),
                                          dtype=np.float32)
                for dummy in range(missed_channels):
                    template += nulltrace
        template.sort()
        _templates.append(template)
        used_template_names.append(template_name)
        # Quick check that this has all worked
        if len(template) != max([len(t) for t in templates]):
            raise Exception('Internal error forcing same template '
                            'lengths, report this error.')
    templates = _templates
    _template_names = used_template_names
    if not unnamed:
        return stream, templates, template_names
    return stream, templates


if __name__ == "__main__":
    import doctest
    doctest.testmod()
