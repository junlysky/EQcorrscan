#!/usr/bin/python
"""
Functions to generate lag-times for events detected by correlation.

Part of the EQcorrscan module to integrate seisan nordic files into a full
cross-channel correlation for detection routine.
EQcorrscan is a python module designed to run match filter routines for
seismology, within it are routines for integration to seisan and obspy.
With obspy integration (which is necessary) all main waveform formats can be
read in and output.

This main section contains a script, LFE_search.py which demonstrates the usage
of the built in functions from template generation from picked waveforms
through detection by match filter of continuous data to the generation of lag
times to be used for relative locations.

The match-filter routine described here was used a previous Matlab code for the
Chamberlain et al. 2014 G-cubed publication.  The basis for the lag-time
generation section is outlined in Hardebeck & Shelly 2011, GRL.

Code generated by Calum John Chamberlain of Victoria University of Wellington,
2015.


.. rubric:: Note
Pre-requisites:
    - gcc             - for the installation of the openCV correlation routine
    - python-cv2      - Python bindings for the openCV routines
    - python-joblib   - used for parallel processing
    - python-obspy    - used for lots of common seismological processing
                        - requires:
                            - numpy
                            - scipy
                            - matplotlib
    - NonLinLoc       - used outside of all codes for travel-time generation

Copyright 2015 Calum Chamberlain

This file is part of EQcorrscan.

    EQcorrscan is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    EQcorrscan is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with EQcorrscan.  If not, see <http://www.gnu.org/licenses/>.

"""
import numpy as np
from match_filter import DETECTION, normxcorr2

def _channel_loop(detection, template, i=0):
    """
    Utility function to take a stream of data for the detected event and parse
    the correct data to lag_gen

    :type detection: obspy.Stream
    :type template: obspy.Stream
    :type i: int, optional
    :param i: Used to track which process has occured when running in parallel

    :returns: lagtimes, a tuple of (lag in s, cross-correlation value, station, chan)
    """
    lagtimes=[]
    for i in xrange(len(template)):
        image=detection.select(station=template[i].stats.station,\
                                channel=template[i].stats.channel)
        if image: #Ideally this if statement would be removed.
            ccc = normxcorr2(template[i].data, image[0].data)
            lagtimes.append((np.argmax(ccc)*image[0].stats.delat, np.max(ccc), \
                    template[i].stats.station, template[i].stats.channel))
    return (i, lagtimes)

def day_loop(detections, template):
    """
    Function to loop through multiple detections for one template - ostensibly
    designed to run for the same day of data for I/O simplicity, but as you
    are passing stream objects it could run for all the detections ever, as long
    as you have the RAM!

    :type detections: List of obspy.Stream
    :param detections: List of all the detections for this template that you
                    want to compute the optimum pick for.
    :type template: obspy.Stream
    :param template: The original template used to detect the detections passed

    :returns: lags - List of List of tuple: lags[i] corresponds to detection[i],
                lags[i][j] corresponds to a channel of detection[i], within
                this tuple is the lag (in seconds), normalised correlation,
                station and channel.
    """
    from multiprocessing import Pool, cpu_count # Used to run detections in parallel
    lags=[]
    num_cores=cpu_count()
    if num_cores > len(detections):
        num_cores=len(detections)
    pool=Pool(processes=num_cores, maxtasksperchild=None)
    results=[pool.apply_async(_channel_loop, args=(detections[i], template, i))\
                        for i in xrange(len(detections))]
    pool.close()
    lags=[p.get() for p in results]
    lags.sort(key=lambda tup: tup[0]) # Sort based on i
    return lags

def lag_calc(detections, detect_data, templates, shift_len=0.2, min_cc=0.4):
    """
    Overseer function to take a list of detection objects, cut the data for
    them to lengths of the same length of the template + shift_len on
    either side. This will then write out SEISAN s-file for the detections
    with pick times based on the lag-times found at the maximum correlation,
    providing that correlation is above the min_cc.

    :type detections: List of DETECTION
    :param detections: List of DETECTION objects
    :type detect_data: obspy.Stream
    :param detect_data: All the data needed to cut from - can be a gappy Stream
    :type templates: List of tuple of String, obspy.Stream
    :param templates: List of the templates used as tuples of template name, template
    :type shift_len: float
    :param shift_len: Shift length allowed for the pick in seconds, will be
                    plus/minus this amount - default=0.2
    :type min_cc: float
    :param min_cc: Minimum cross-correlation value to be considered a pick,
                    default=0.4
    """
    from utils import Sfile_util
    from obspy import Stream
    # First work out the delays for each template
    delays=[] # List of tuples
    for template in templates:
        temp_delays=[]
        for tr in tempate[1]:
            temp_delays.append((tr.stats.station, tr.stats.channel,\
                    tr.stats.starttime-template.sort['starttime'][0].stats.starttime))
        delays.append((template[0], temp_delays))
    detect_streams=[]
    for detection in detections:
        detect_stream=[]
        for tr in detect_data:
            tr_copy=tr.copy()
            template=[t for t in templates if t[0]==detection.template_name][0]
            template=template.select(station=tr.stats.station,
                            channel=tr.stats.channel)
            if template:
                template_len=len(template[0])
            else:
                continue # If there is no template-data match then skip the rest
                         # of the trace loop.
            delay=[delay for delay in delays if delay[0]==detection.template_name][0]
            delay=[d for d in delay if d[0]==tr.stats.station and \
                    d[1]==tr.stats.channel][0]
            detect_stream.append(tr_copy.trim(starttime=detection.detect_time-\
                        shift_len+delay, endtime=detection.detect_time+delay+\
                        shift_len+template_len))
        detect_streams.append((detection.template_name, Stream(detect_stream)))
        # Tuple of template name and data stream
    # Segregate detections by template
    lags=[]
    for template in templates:
        template_detections=[detect[1] for detect in detect_streams\
                if detect[0]==template[0]]
        lags.append(day_loop(template_detections, template[1]))

    # Write out the lags!
    for event in lags:
        # I think I have an old version of Sfile_util here
        sfilename=Sfile_util.blanksfile(wavefile, 'L', 'PYTH', 'out', True)
        picks=[]
        for pick in event:
            picks.append(Sfile_util.PICK())
        Sfile_util.populateSfile(sfilename, picks)
