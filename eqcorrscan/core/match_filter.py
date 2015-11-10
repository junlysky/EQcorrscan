#!/usr/bin/python
"""
Function to cross-correlate templates generated by template_gen function with\
data and output the detecitons.  The main component of this script is the\
normxcorr2 function from the openCV image processing package.  This is a highly\
optimized and accurate normalized cross-correlation routine.  The details of\
this code can be found here:\
* http://www.cs.ubc.ca/research/deaton/remarks_ncc.html\
The cpp code was first tested using the Matlab mex wrapper, and has since been\
ported to a python callable dynamic library.

Part of the EQcorrscan module to integrate seisan nordic files into a full\
cross-channel correlation for detection routine.\
EQcorrscan is a python module designed to run match filter routines for\
seismology, within it are routines for integration to seisan and obspy.\
With obspy integration (which is necessary) all main waveform formats can be\
read in and output.

This main section contains a script, LFE_search.py which demonstrates the usage\
of the built in functions from template generation from picked waveforms\
through detection by match filter of continuous data to the generation of lag\
times to be used for relative locations.

The match-filter routine described here was used a previous Matlab code for the\
Chamberlain et al. 2014 G-cubed publication.  The basis for the lag-time\
generation section is outlined in Hardebeck & Shelly 2011, GRL.

Code generated by Calum John Chamberlain of Victoria University of Wellington,\
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
import warnings

class DETECTION(object):
    """
    Information required for a full detection based on cross-channel
    correlation sums.

    Attributes:
        :type template_name: str
        :param template_name: The name of the template for which this detection\
        was made
        :type detect_time: :class: 'obspy.UTCDateTime'
        :param detect_time: Time of detection as an obspy UTCDateTime object
        :type no_chans: int
        :param no_chans: The number of channels for which the cross-channel\
        correlation sum was calculated over.
        :type chans: list of str
        :param chans: List of stations for the detection
        :type cccsum_val: float
        :param cccsum_val: The raw value of the cross-channel correlation sum\
        for this detection.
        :type threshold: float
        :param threshold: The value of the threshold used for this detection,\
        will be the raw threshold value related to the cccsum.
        :type typeofdet: str
        :param typeofdet: Type of detection, STA, corr, bright
    """
    detectioncount=0
    def __init__(self, template_name, detect_time,
                 no_chans, detect_val,
                 threshold, typeofdet,
                 chans=None):

        self.template_name=template_name
        self.detect_time=detect_time
        self.no_chans=no_chans
        self.chans=chans
        self.detect_val=detect_val
        self.threshold=threshold
        self.typeofdet=typeofdet
        self.detectioncount+=1
    def __repr__(self):
        return "DETECTION()"
    def __str__(self):
        print_str="Detection on "+self.template_name+" at "+str(self.detect_time)
        return print_str

def normxcorr2(template, image):
    """
    Base function to call the c++ correlation routine from the openCV image
    processing suite.  Requires you to have installed the openCV python
    bindings, which can be downloaded on Linux machines using:
    **sudo apt-get install python-openCV**
    Here we use the cv2.TM_CCOEFF_NORMED method within openCV to give the
    normalized cross-correaltion.  Documentation on this function can be
    found here:
    **http://docs.opencv.org/modules/imgproc/doc/object_detection.html?highlight=matchtemplate#cv2.matchTemplate**

    :type template: :class: 'numpy.array'
    :param template: Template array
    :type image: :class: 'numpy.array'
    :param image: image to scan\
    the template through.  The order of these matters, if you put the template\
    after the image you will get a reversed correaltion matrix

    :return: New :class: 'numpy.array' object of the correlation values for the\
    correlation of the image with the template.
    """
    import cv2
    # Check that we have been passed numpy arrays
    if type(template) != np.ndarray or type(image) != np.ndarray:
        print 'You have not provided numpy arrays, I will not convert them'
        return 'NaN'
    # Convert numpy arrays to float 32
    cv_template=template.astype(np.float32)
    cv_image=image.astype(np.float32)
    ccc=cv2.matchTemplate(cv_image,cv_template,cv2.TM_CCOEFF_NORMED)
    if np.all(np.isnan(cv_image)) and np.all(np.isnan(cv_template)):
        ccc=np.zeros(len(ccc))
    if np.all(ccc==1.0) and (np.all(np.isnan(cv_template))\
                            or np.all(np.isnan(cv_image))):
        ccc=np.zeros(len(ccc))
        # Convert an array of perfect correlations to zero cross-correlations
    # Reshape ccc to be a 1D vector as is useful for seismic data
    ccc=ccc.reshape((1,len(ccc)))
    return ccc

def _template_loop(template, chan, station, channel, debug=0, i=0):
    """
    Sister loop to handle the correlation of a single template (of multiple
    channels) with a single channel of data.

    :type template: obspy.Stream
    :type chan: np.array
    :type station: String
    :type channel: String
    :type i: Int
    :param i: Optional argument, used to keep track of which process is being\
    run.

    :returns: tuple of (i,ccc) with ccc as an ndarray
    """
    from eqcorrscan.utils.timer import Timer

    ccc=np.array([np.nan] * (len(chan) - len(template[0].data) + 1),\
        dtype=np.float16)
    ccc=ccc.reshape((1,len(ccc)))           # Set default value for
                                            # cross-channel correlation in
                                            # case there are no data that
                                            # match our channels.
    with Timer() as t:
        # While each bit of this loop isn't slow, looping through the if statement when
        # I don't need to adds up, I should work this out earlier
        template_data=template.select(station=station, \
                                      channel=channel)
        template_data=template_data[0] # Assuming you only have one template per channel
        delay=template_data.stats.starttime - \
                template.sort(['starttime'])[0].stats.starttime
        pad=np.array([0] * int(round(delay * \
            template_data.stats.sampling_rate)))
        image=np.append(chan,pad)[len(pad):]
        ccc=(normxcorr2(template_data.data, image))
        ccc=ccc.astype(np.float16)
        # Convert to float16 to save memory for large problems - lose some
        # accuracy which will affect detections very close to threshold
    if debug >= 2 and t.secs > 4:
        print "Single if statement took %s s" % t.secs
        if not template_data:
            print "Didn't even correlate!"
        print station+' '+channel
    elif debug >=2:
        print "If statement without correlation took %s s" % t.secs
    if debug >= 3:
        print '********* DEBUG:  '+station+'.'+\
                channel+' ccc MAX: '+str(np.max(ccc[0]))
        print '********* DEBUG:  '+station+'.'+\
                channel+' ccc MEAN: '+str(np.mean(ccc[0]))
    if np.isinf(np.mean(ccc[0])):
        warnings.warn('Mean of ccc is infinite, check!')
        if debug >=3:
            np.save('inf_cccmean_ccc.npy', ccc[0])
            np.save('inf_cccmean_template.npy', template_data.data)
            np.save('inf_cccmean_image.npy', image)
    if debug >=3:
        print 'shape of ccc: '+str(np.shape(ccc))
        print 'A single ccc is using: '+str(ccc.nbytes/1000000)+'MB'
        print 'ccc type is: '+str(type(ccc))
    if debug >=3:
        print 'shape of ccc: '+str(np.shape(ccc))
        print "Parallel worker "+str(i)+" complete"
    return (i, ccc)

def _channel_loop(templates, stream, cores=1, debug=0):
    """
    Loop to generate cross channel correaltion sums for a series of templates
    hands off the actual correlations to a sister function which can be run in
    parallel.

    :type templates: :class: 'obspy.Stream'
    :param templates: A list of templates, where each one should be an\
    obspy.Stream object containing multiple traces of seismic data and the\
    relevant header information.
    :param stream: A single obspy.Stream object containing daylong seismic data\
    to be correlated through using the templates.  This is in effect the image
    :type core: int
    :param core: Number of cores to loop over
    :type debug: int
    :param debug: Debug level.

    :return: New list of :class: 'numpy.array' objects.  These will contain the\
    correlation sums for each template for this day of data.
    :return: list of ints as number of channels used for each cross-correlation
    """
    import time, cv2
    from multiprocessing import Pool
    from eqcorrscan.utils.timer import Timer
    num_cores=cores
    if len(templates) < num_cores:
        num_cores = len(templates)
    if 'cccs_matrix' in locals():
        del cccs_matrix
    # Initialize cccs_matrix, which will be two arrays of len(templates) arrays,
    # where the arrays cccs_matrix[0[:]] will be the cross channel sum for each
    # template.

    # Note: This requires all templates to be the same length, and all channels
    # to be the same length
    cccs_matrix=np.array([np.array([np.array([0.0]*(len(stream[0].data)-\
                                   len(templates[0][0].data)+1))]*\
                          len(templates))]*2)
    # Initialize number of channels array
    no_chans=np.array([0]*len(templates))

    for tr in stream:
        tr_data=tr.data
        station=tr.stats.station
        channel=tr.stats.channel
        if debug >=1:
            print "Starting parallel run for station "+station+" channel "+\
                    channel
        tic=time.clock()
        with Timer() as t:
            # Send off to sister function
            pool=Pool(processes=num_cores, maxtasksperchild=None)
            results=[pool.apply_async(_template_loop, args=(templates[i],\
                                                        tr_data, station,\
                                                                channel, i,\
                                                                debug))\
                                  for i in range(len(templates))]
            pool.close()
        if debug >=1:
            print "--------- TIMER:    Correlation loop took: %s s" % t.secs
            print " I have "+str(len(results))+" results"
        with Timer() as t:
            cccs_list=[p.get() for p in results]
            pool.join()
        if debug >=1:
            print "--------- TIMER:    Getting results took: %s s" % t.secs
        with Timer() as t:
            cccs_list.sort(key=lambda tup: tup[0]) # Sort by placeholder returned from function
        if debug >=1:
            print "--------- TIMER:    Sorting took: %s s" % t.secs
        with Timer() as t:
            cccs_list = [ccc[1] for ccc in cccs_list]
        if debug >=1:
            print "--------- TIMER:    Extracting arrays took: %s s" % t.secs
        if debug >= 3:
            print 'cccs_list is shaped: '+str(np.shape(cccs_list))
        with Timer() as t:
            cccs=np.concatenate(cccs_list, axis=0)
        if debug >=1:
            print "--------- TIMER:    cccs_list conversion: %s s" % t.secs
        del cccs_list
        if debug >=2:
            print 'After looping through templates the cccs is shaped: '+str(np.shape(cccs))
            print 'cccs is using: '+str(cccs.nbytes/1000000)+' MB of memory'
        cccs_matrix[1]=np.reshape(cccs, (1,len(templates),max(np.shape(cccs))))
        del cccs
        if debug >=2:
            print 'cccs_matrix shaped: '+str(np.shape(cccs_matrix))
            print 'cccs_matrix is using '+str(cccs_matrix.nbytes/1000000)+' MB of memory'
        # Now we have an array of arrays with the first dimensional index giving the
        # channel, the second dimensional index giving the template and the third
        # dimensional index giving the position in the ccc, e.g.:
        # np.shape(cccsums)=(len(stream), len(templates), len(ccc))

        if debug >=2:
            print 'cccs_matrix as a np.array is shaped: '+str(np.shape(cccs_matrix))
        # First work out how many channels were used
        for i in range(0,len(templates)):
            if not np.all(cccs_matrix[1][i]==0):
                # Check that there are some real numbers in the vector rather
                # than being all 0, which is the default case for no match
                # of image and template names
                no_chans[i]+=1
        # Now sum along the channel axis for each template to give the cccsum values
        # for each template for each day
        with Timer() as t:
            cccsums=cccs_matrix.sum(axis=0).astype(np.float32)
        if debug >=1:
            print "--------- TIMER:    Summing took %s s" % t.secs
        if debug>=2:
            print 'cccsums is shaped thus: '+str(np.shape(cccsums))
        cccs_matrix[0]=cccsums
        del cccsums
        toc=time.clock()
        if debug >=1:
            print "--------- TIMER:    Trace loop took "+str(toc-tic)+" s"
    if debug >=2:
        print 'cccs_matrix is shaped: '+str(np.shape(cccs_matrix))
    cccsums=cccs_matrix[0]
    return cccsums, no_chans

def match_filter(template_names, templates, st, threshold,\
                 threshold_type, trig_int, plotvar, plotdir='.', cores=1,\
                 tempdir=False, debug=0, plot_format='jpg'):
    """
    Over-arching code to run the correlations of given templates with a day of
    seismic data and output the detections based on a given threshold.

    :type templates: list :class: 'obspy.Stream'
    :param templates: A list of templates of which each template is a Stream of\
        obspy traces containing seismic data and header information.
    :type st: :class: 'obspy.Stream'
    :param st: An obspy.Stream object containing all the data available and\
        required for the correlations with templates given.  For efficiency this\
        should contain no excess traces which are not in one or more of the\
        templates.  This will now remove excess traces internally, but will\
        copy the stream and work on the copy, leaving the stream you input\
        untouched.
    :type threshold: float
    :param threshold: A threshold value set based on the threshold_type
    :type threshold_type: str
    :param threshold_type: The type of threshold to be used, can be MAD,\
        absolute or av_chan_corr.    MAD threshold is calculated as the\
        threshold*(median(abs(cccsum))) where cccsum is the cross-correlation\
        sum for a given template. absolute threhsold is a true absolute\
        threshold based on the cccsum value av_chan_corr is based on the mean\
        values of single-channel cross-correlations assuming all data are\
        present as required for the template, \
        e.g. av_chan_corr_thresh=threshold*(cccsum/len(template)) where\
        template is a single template from the input and the length is the\
        number of channels within this template.
    :type trig_int: float
    :param trig_int: Minimum gap between detections in seconds.
    :type plotvar: bool
    :param plotvar: Turn plotting on or off
    :type plotdir: str
    :param plotdir: Path to plotting folder, plots will be output here, defaults\
        to run location.
    :type tempdir: String or False
    :param tempdir: Directory to put temporary files, or False
    :type cores: int
    :param cores: Number of cores to use
    :type debug: int
    :param debug: Debug output level, the bigger the number, the more the output

    :return: :class: 'DETECTIONS' detections for each channel formatted as\
    :class: 'obspy.UTCDateTime' objects.

    .. rubric:: Note
        Plotting within the match-filter routine uses the Agg backend with\
        interactive plotting turned off.  This is because the function is\
        designed to work in bulk.  If you wish to turn interactive plotting on\
        you must import matplotlib in your script first, when you them import\
        match_filter you will get the warning that this call to matplotlib has\
        no effect, which will mean that match_filter has not changed the plotting\
        behaviour.

    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.ioff()
    from eqcorrscan.utils import findpeaks, EQcorrscan_plotting
    import time, copy
    from obspy import Trace
    match_internal=False # Set to True if memory is an issue, if True, will only
                          # use about the same amount of memory as the seismic dat
                          # take up.  If False, it will use 20-100GB per instance
    # Copy the stream here because we will fuck about with it
    stream=st.copy()
    # Debug option to confirm that the channel names match those in the templates
    if debug>=2:
        template_stachan=[]
        data_stachan=[]
        for template in templates:
            for tr in template:
                template_stachan.append(tr.stats.station+'.'+tr.stats.channel)
        for tr in stream:
            data_stachan.append(tr.stats.station+'.'+tr.stats.channel)
        template_stachan=list(set(template_stachan))
        data_stachan=list(set(data_stachan))
        if debug >= 3:
            print 'I have template info for these stations:'
            print template_stachan
            print 'I have daylong data for these stations:'
            print data_stachan
    # Perform a check that the daylong vectors are daylong
    for tr in stream:
        if not tr.stats.sampling_rate*86400 == tr.stats.npts:
            raise ValueError ('Data are not daylong for '+tr.stats.station+\
                              '.'+tr.stats.channel)
    # Call the _template_loop function to do all the correlation work
    outtic=time.clock()
    # Edit here from previous, stable, but slow match_filter
    # Would be worth testing without an if statement, but with every station in
    # the possible template stations having data, but for those without real
    # data make the data NaN to return NaN ccc_sum
    if debug >=2:
        print 'Ensuring all template channels have matches in daylong data'
    template_stachan=[]
    for template in templates:
        for tr in template:
            template_stachan+=[(tr.stats.station, tr.stats.channel)]
    template_stachan=list(set(template_stachan))
    # Copy this here to keep it safe
    for stachan in template_stachan:
        if not stream.select(station=stachan[0], channel=stachan[1]):
            # Add a trace of NaN's
            nulltrace=Trace()
            nulltrace.stats.station=stachan[0]
            nulltrace.stats.channel=stachan[1]
            nulltrace.stats.sampling_rate=stream[0].stats.sampling_rate
            nulltrace.stats.starttime=stream[0].stats.starttime
            nulltrace.data=np.array([np.NaN]*len(stream[0].data), dtype=np.float32)
            stream+=nulltrace
    # Remove un-needed channels
    for tr in stream:
        if not (tr.stats.station, tr.stats.channel) in template_stachan:
            stream.remove(tr)
    # Also pad out templates to have all channels
    for template in templates:
        for stachan in template_stachan:
            if not template.select(station=stachan[0], channel=stachan[1]):
                nulltrace=Trace()
                nulltrace.stats.station=stachan[0]
                nulltrace.stats.channel=stachan[1]
                nulltrace.stats.sampling_rate=template[0].stats.sampling_rate
                nulltrace.stats.starttime=template[0].stats.starttime
                nulltrace.data=np.array([np.NaN]*len(template[0].data), dtype=np.float32)
                template+=nulltrace

    if debug >= 2:
        print 'Starting the correlation run for this day'
    if match_internal:
        [cccsums, no_chans] = run_channel_loop(templates, stream, tempdir)
    else:
        [cccsums, no_chans]=_channel_loop(templates, stream, cores,\
                            debug)
    if len(cccsums[0])==0:
        raise ValueError('Correlation has not run, zero length cccsum')
    outtoc=time.clock()
    print 'Looping over templates and streams took: '+str(outtoc-outtic)+' s'
    if debug>=2:
        print 'The shape of the returned cccsums is: '+str(np.shape(cccsums))
        print 'This is from '+str(len(templates))+' templates'
        print 'Correlated with '+str(len(stream))+' channels of data'
    i=0
    detections=[]
    for cccsum in cccsums:
        template=templates[i]
        if threshold_type=='MAD':
            rawthresh=threshold*np.median(np.abs(cccsum))
        elif threshold_type=='absolute':
            rawthresh=threshold
        elif threshold=='av_chan_corr':
            rawthresh=threshold*(cccsum/len(template))
        else:
            print 'You have not selected the correct threshold type, I will use MAD as I like it'
            rawthresh=threshold*np.mean(np.abs(cccsum))
        # Findpeaks returns a list of tuples in the form [(cccsum, sample)]
        print 'Threshold is set at: '+str(rawthresh)
        print 'Max of data is: '+str(max(cccsum))
        print 'Mean of data is: '+str(np.mean(cccsum))
        if np.abs(np.mean(cccsum)) > 0.05:
            warnings.warn('Mean is not zero!  Check this!')
        # Set up a trace object for the cccsum as this is easier to plot and
        # maintins timing
        if plotvar:
            stream_plot=copy.deepcopy(stream[0])
            # Downsample for plotting
            stream_plot.decimate(int(stream[0].stats.sampling_rate / 10))
            cccsum_plot=Trace(cccsum)
            cccsum_plot.stats.sampling_rate=stream[0].stats.sampling_rate
            # Resample here to maintain shape better
            cccsum_hist=cccsum_plot.copy()
            cccsum_hist=cccsum_hist.decimate(int(stream[0].stats.sampling_rate\
                                                / 10)).data
            cccsum_plot=EQcorrscan_plotting.chunk_data(cccsum_plot, 10, 'Maxabs').data
            # Enforce same length
            stream_plot.data=stream_plot.data[0:len(cccsum_plot)]
            cccsum_plot=cccsum_plot[0:len(stream_plot.data)]
            cccsum_hist=cccsum_hist[0:len(stream_plot.data)]
            EQcorrscan_plotting.triple_plot(cccsum_plot, cccsum_hist, stream_plot,\
                                            rawthresh, True,\
                                            plotdir+'/cccsum_plot_'+template_names[i]+'_'+\
                                        str(stream[0].stats.starttime.year)+'-'+\
                                        str(stream[0].stats.starttime.month)+'-'+\
                                        str(stream[0].stats.starttime.day)+'.'+\
                                            plot_format)
            if debug >= 4:
                print 'Saved the cccsum to: '+template_names[i]+\
                            stream[0].stats.starttime.datetime.strftime('%Y%j')
                np.save(template_names[i]+\
                            stream[0].stats.starttime.datetime.strftime('%Y%j'),\
                        cccsum)
        tic=time.clock()
        if debug>=4:
            np.save('cccsum_'+str(i)+'.npy', cccsum)
        if debug>=3 and max(cccsum)>rawthresh:
            peaks=findpeaks.find_peaks2_short(cccsum, rawthresh, \
                                        trig_int*stream[0].stats.sampling_rate,\
                                        debug, stream[0].stats.starttime,
                                        stream[0].stats.sampling_rate)
        elif max(cccsum)>rawthresh:
            peaks=findpeaks.find_peaks2_short(cccsum, rawthresh, \
                                        trig_int*stream[0].stats.sampling_rate,\
                                        debug)
        else:
            print 'No peaks found above threshold'
            peaks=False
        toc=time.clock()
        if debug >= 1:
            print 'Finding peaks took: '+str(toc-tic)+' s'
        if peaks:
            for peak in peaks:
                detecttime=stream[0].stats.starttime+\
                            peak[1]/stream[0].stats.sampling_rate
                detections.append(DETECTION(template_names[i],
                                             detecttime,
                                             no_chans[i], peak[0], rawthresh,
                                             'corr'))
        i+=1

    return detections
