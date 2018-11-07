# -*- coding: utf-8 -*-

# Standard library imports
from collections import OrderedDict, defaultdict
from glob import glob
import logging

# Third party imports
import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter, gaussian_filter1d
import plotly.graph_objs as go
import plotly.offline as py

# Local lib import
from pycoQC.common import jprint, is_readable_file

##~~~~~~~ MAIN CLASS ~~~~~~~#
class pycoQC ():

    #~~~~~~~FUNDAMENTAL METHODS~~~~~~~#
    def __init__ (self,
        seq_summary_file,
        run_type = None,
        runid_list = [],
        min_pass_qual = 7,
        iplot=True,
        verbose=False):
        """
        Parse Albacore sequencing_summary.txt file and clean-up the data
        * seq_summary_file: STR
            Path to the sequencing_summary generated by Albacore 1.0.0 +. One can also pass a UNIX style regex to match
            multiple files with glob https://docs.python.org/3.6/library/glob.html
        * run_type: STR [Default None = autodetect]
            Force to us the Type of the run 1D or 1D2
        * runid_list: LIST of STR [Default []]
            Select only specific runids to be analysed. Can also be used to force pycoQC to order the runids for
            temporal plots, if the sequencing_summary file contain several sucessive runs. By default pycoQC analyses
            all the runids in the file and uses the runid order as defined in the file.
        * min_pass_qual INT [Default 7]
            Pass reads are defined throughout the package based on this threshold
        * iplot
            if False the ploting function do not plot the results but only return the a plotly.Figure object.
            This is mainly intended to non-interative ploting
        """

        # Check that file is readable and import the summary file in a dataframe
        logger.info ("Import raw data from sequencing summary files")
        try:
            df_list = []
            fp_list = glob (seq_summary_file)
            if len(fp_list) == 0:
                raise pycoQCError ("Could not find any files matching {}".format(seq_summary_file))
            logger.debug ("\tSequencing summary files found: {}".format(fp_list))
            for fp in fp_list:
                df_list.append (pd.read_csv(fp, sep ="\t"))
            df = pd.concat(df_list, ignore_index=True, sort=False, join="inner")
        except IOError:
            raise pycoQCError ("File {} is not readeable".format(fp))
        if len(df) == 0:
            raise pycoQCError ("No valid read found in input file")
        logger.debug ("\t{:,} reads found in initial file".format(len(df)))

        # Define specific parameters depending on the run_type
        if verbose:
            jprint("Verify and rearrange fields", bold=True)

        if run_type == "1D" or (not run_type and "sequence_length_template" in df):
            if verbose:
                jprint("\t1D Run type")
            self.run_type = "1D"
            required_colnames = ["read_id", "run_id", "channel", "start_time", "sequence_length_template", "mean_qscore_template"]
            optional_colnames = ["calibration_strand_genome_template", "barcode_arrangement"]
            rename_colmanes = {
                "sequence_length_template":"num_bases",
                "mean_qscore_template":"mean_qscore",
                "calibration_strand_genome_template":"calibration",
                "barcode_arrangement":"barcode"}
        elif run_type == "1D2" or (not run_type and "sequence_length_2d" in df):
            if verbose:
                jprint("\t1D2 Run type")
            self.run_type = "1D2"
            required_colnames = ["read_id", "run_id", "channel", "start_time", "sequence_length_2d", "mean_qscore_2d"]
            optional_colnames = ["calibration_strand_genome_template", "barcode_arrangement"]
            rename_colmanes = {
                "sequence_length_2d":"num_bases",
                "mean_qscore_2d":"mean_qscore",
                "calibration_strand_genome_template":"calibration",
                "barcode_arrangement":"barcode"}
        else:
            raise ValueError ("Invalid run_type 1D or 1D2")

        # Verify that the required and optional columns in the dataframe
        main_col = self._check_columns (df=df, colnames=required_colnames, raise_error_if_missing=True)
        opt_col = self._check_columns (df=df, colnames=optional_colnames, raise_error_if_missing=False)

        # Drop unused fields, simplify field names and drop lines containing NA values
        df = df[main_col+opt_col]
        df = df.rename(columns=rename_colmanes)
        df = df.dropna()

        # Filter out calibration strands read if the "calibration_strand_genome_template" field is available
        if "calibration" in df:
            if verbose: jprint ("Filter out reads corresponding to the calibration strand", bold=True)
            l = len(df)
            df = df[(df["calibration"].isin(["filtered_out", "no_match"]))]
            if verbose: jprint ("\t{} reads discarded".format(l-len(df)))
            assert len(df) > 0, "No valid read left after calibration strand filtering"

        # Filter out zero length reads
        if (df["num_bases"]==0).any():
            if verbose: jprint ("Filter out zero length reads", bold=True)
            l = len(df)
            df = df[(df["num_bases"] > 0)]
            if verbose: jprint ("\t{} reads discarded".format(l-len(df)))
            assert len(df) > 0, "No valid read left after zero_len filtering"

        # select runid passed by user
        if runid_list:
            if verbose: jprint ("Verify run_ids passed by user", bold=True)
            df = df[(df["run_id"].isin(runid_list))]
            assert len(df) > 0, "No valid read left after runid filtering"
        # Else sort the runids by output per time assuming that the througput decreases over time
        else:
            if verbose: jprint ("Order run_ids by decreasing througput", bold=True)
            d = {}
            for run_id, sdf in df.groupby("run_id"):
                d[run_id] = len(sdf)/sdf["start_time"].ptp()
            runid_list = [i for i, j in sorted (d.items(), key=lambda t: t[1], reverse=True)]

        # Modify start time per run ids to order them following the runid_list
        increment_time = 0
        self.runid_start = OrderedDict()
        for runid in runid_list:
            if verbose: jprint ("\tProcessing reads with Run_ID {} / time offset: {}".format(runid, increment_time))
            max_val = df['start_time'][df["run_id"] == runid].max()
            df.loc[df["run_id"] == runid, 'start_time'] += increment_time
            self.runid_start[runid] = increment_time
            increment_time += max_val+1

        # Final cleanup
        if verbose: jprint ("Reindex and sort", bold=True)
        df = df.sort_values ("start_time")
        df = df.reset_index (drop=True)
        df = df.set_index ("read_id")
        self.total_reads = len (df)
        if verbose: jprint ("\t{} Total valid reads found".format(self.total_reads))

        self.all_df = df
        self.pass_df = df[df["mean_qscore"]>=min_pass_qual]
        self._min_pass_qual = min_pass_qual
        self._iplot = iplot

    def __str__(self):
        """
        readable description of the object
        """
        msg = "{} instance\n".format(self.__class__.__name__)
        msg+= "\tParameters list\n"

        # list all values in object dict in alphabetical order
        for k,v in OrderedDict(sorted(self.__dict__.items(), key=lambda t: t[0])).items():
            if not k in ["all_df", "pass_df"]:
                msg+="\t{}\t{}\n".format(k, v)
        return msg

    #~~~~~~~SUMMARY METHOD AND HELPER~~~~~~~#

    def summary (self,
        width = 1400,
        height = None):
        """
        Plot an interactive summary table
        * width: With of the ploting area in pixel
        * height: height of the ploting area in pixel
        """
        # Prepare empty plot
        data = [go.Table (columnwidth = [60, 20])]

        updatemenus = [
            dict (type="buttons", active=0, x=-0.05, y=1, xanchor='right', yanchor='top', buttons = [
                dict (label='All Reads', method='restyle', args=[self.__summary_data (df=self.all_df)]),
                dict (label='Pass Reads', method='restyle', args=[self.__summary_data (df=self.pass_df)]),
            ])]

        # Autodefine height depending on the numbers of run_ids
        if not height:
            height = 270+(30*self.all_df["run_id"].nunique())
        layout = go.Layout (updatemenus = updatemenus, width = width, height = height)

        fig = go.Figure (data=data, layout=layout)
        if self._iplot:
            py.iplot (fig, show_link=False)
        return fig

    def __summary_data (self, df):
        """
        Private function preparing data for summary
        """

        header=["Run_ID", "Reads", "Bases", "Mean Read Length", "Active Channels", "Run Duration (h)"]
        if "barcode" in df:
            header.append("Unique Barcodes")

        cells = []
        cells.append (self.__df_to_cell("All Run_IDs", df))
        for run_id, sdf in df.groupby ("run_id"):
            cells.append (self.__df_to_cell(run_id, sdf))

        # Transpose list of list
        cells = [*zip(*cells)]

        data_dict = dict (
            header = [{"values":header, "fill":{"color":"lightgrey"}, "align":"center", "font":{"color":'black', "size":12}, "height":40}],
            cells  = [{"values":cells, "fill":{"color":["lightgrey", "white"]}, "align":"center", "font":{"color":'black', "size":12}, "height":30}],
        )

        return data_dict

    def __df_to_cell (self, run_id, df):
        """Extract information from sub-dataframes and return a list of values"""
        l = []
        l.append (run_id)
        l.append ("{:,}".format(len(df)))
        l.append ("{:,}".format(df["num_bases"].sum()))
        l.append ("{:,}".format(int(df["num_bases"].mean())))
        l.append ("{:,}".format(df["channel"].nunique()))
        l.append (round((df["start_time"].ptp())/3600, 2))
        if "barcode" in df:
            l.append ("{:,}".format(df["barcode"].nunique()))
        return l

    #~~~~~~~1D DISTRIBUTION METHODS AND HELPER~~~~~~~#

    def reads_len_1D (self,
        color="lightsteelblue",
        width=1400,
        height=500,
        nbins=200,
        smooth_sigma=2,
        sample=100000):
        """
        Plot a distribution of read length (log scale)
        * color: Color of the area (hex, rgb, rgba, hsl, hsv or any CSV named colors https://www.w3.org/TR/css-color-3/#svg-color
        * width: With of the ploting area in pixel
        * height: height of the ploting area in pixel
        * nbins: Number of bins to devide the x axis in
        * smooth_sigma: standard deviation for Gaussian kernel
        * sample: If given, a n number of reads will be randomly selected instead of the entire dataset
        """
        # Downsample if needed
        all_df = self.all_df.sample(sample) if sample and len(self.all_df)>sample else self.all_df
        pass_df = self.pass_df.sample(sample) if sample and len(self.pass_df)>sample else self.pass_df

        # Prepare empty plot
        data = [
            go.Scatter (fill='tozeroy', fillcolor=color, mode='none', showlegend=True),
            go.Scatter (mode="lines+text", hoverinfo="skip", textposition='top center', line= {'color':'gray','width':1,'dash': 'dot'}),
            go.Scatter (mode="lines+text", hoverinfo="skip", textposition='top center', line= {'color':'gray','width':1,'dash': 'dot'}),
            go.Scatter (mode="lines+text", hoverinfo="skip", textposition='top center', line= {'color':'gray','width':1,'dash': 'dot'}),
            go.Scatter (mode="lines+text", hoverinfo="skip", textposition='top center', line= {'color':'gray','width':1,'dash': 'dot'}),
            go.Scatter (mode="lines+text", hoverinfo="skip", textposition='top center', line= {'color':'gray','width':1,'dash': 'dot'}),
            ]

        updatemenus = [
            dict (type="buttons", active=0, x=-0.2, y=0, xanchor='left', yanchor='bottom', buttons = [
                dict (
                    label='All Reads', method='update',
                    args=self.__reads_1D_data (all_df, field_name="num_bases", xscale="log", nbins=nbins, smooth_sigma=smooth_sigma)),
                dict (
                    label='Pass Reads', method='update',
                    args=self.__reads_1D_data (pass_df, field_name="num_bases", xscale="log", nbins=nbins, smooth_sigma=smooth_sigma)),
            ])]

        layout = go.Layout (
            hovermode="closest",
            legend={"x":-0.2, "y":1,"xanchor":'left',"yanchor":'top'},
            updatemenus=updatemenus,
            width=width,
            height=height,
            title = "Distribution of Read Length",
            xaxis = {"title":"Read Length", "type":"log", "zeroline":False, "showline":True},
            yaxis = {"title":"Read Density", "zeroline":False, "showline":True, "fixedrange":True},
        )

        fig = go.Figure (data=data, layout=layout)
        if self._iplot:
            py.iplot (fig, show_link=False)
        return fig

    def reads_qual_1D (self,
        color="salmon",
        width=1400,
        height=500,
        nbins=200,
        smooth_sigma=2,
        sample=100000):
        """
        Plot a distribution of quality scores
        * color: Color of the area (hex, rgb, rgba, hsl, hsv or any CSV named colors https://www.w3.org/TR/css-color-3/#svg-color
        * width: With of the ploting area in pixel
        * height: height of the ploting area in pixel
        * nbins: Number of bins to devide the x axis in
        * smooth_sigma: standard deviation for Gaussian kernel
        * sample: If given, a n number of reads will be randomly selected instead of the entire dataset
        """
        # Downsample if needed
        all_df = self.all_df.sample(sample) if sample and len(self.all_df)>sample else self.all_df
        pass_df = self.pass_df.sample(sample) if sample and len(self.pass_df)>sample else self.pass_df

        # Prepare empty plot
        data = [
            go.Scatter (fill='tozeroy', fillcolor=color, mode='none'),
            go.Scatter (mode="lines+text", hoverinfo="skip", textposition='top center', line= {'color':'gray','width':1,'dash': 'dot'}),
            go.Scatter (mode="lines+text", hoverinfo="skip", textposition='top center', line= {'color':'gray','width':1,'dash': 'dot'}),
            go.Scatter (mode="lines+text", hoverinfo="skip", textposition='top center', line= {'color':'gray','width':1,'dash': 'dot'}),
            go.Scatter (mode="lines+text", hoverinfo="skip", textposition='top center', line= {'color':'gray','width':1,'dash': 'dot'}),
            go.Scatter (mode="lines+text", hoverinfo="skip", textposition='top center', line= {'color':'gray','width':1,'dash': 'dot'}),
            ]

        # Define button and associated data
        updatemenus = [
            dict (type="buttons", active=0, x=-0.2, y=0, xanchor='left', yanchor='bottom', buttons = [
                dict (
                    label='All Reads', method='update',
                    args=self.__reads_1D_data (all_df, field_name="mean_qscore", nbins=nbins, smooth_sigma=smooth_sigma)),
                dict (
                    label='Pass Reads', method='update',
                    args=self.__reads_1D_data (pass_df, field_name="mean_qscore", nbins=nbins, smooth_sigma=smooth_sigma)),
            ])]

        layout = go.Layout (
            hovermode = "closest",
            legend = {"x":-0.2, "y":1,"xanchor":'left',"yanchor":'top'},
            updatemenus = updatemenus,
            width = width,
            height = height,
            title = "Distribution of Read Quality Scores",
            xaxis = {"title":"Read Quality Scores", "zeroline":False, "showline":True},
            yaxis = {"title":"Read Density", "zeroline":False, "showline":True, "fixedrange":True})

        fig = go.Figure(data=data, layout=layout)
        if self._iplot:
            py.iplot (fig, show_link=False)
        return fig

    def __reads_1D_data (self, df, field_name="num_bases", xscale="linear", nbins=200, smooth_sigma=2):
        """
        Private function preparing data for reads_len_1D and reads_qual_1D
        """

        #Extract data field from df
        data = df[field_name].values

        # Count each categories in log or linear space
        min = np.nanmin(data)
        max = np.nanmax(data)
        if xscale == "log":
            count_y, bins = np.histogram (a=data, bins=np.logspace (np.log10(min), np.log10(max)+0.1, nbins))
        elif xscale == "linear":
            count_y, bins = np.histogram (a=data, bins= np.linspace (min, max, nbins))

        # Remove last bin from labels
        count_x = bins[1:]

        # Smooth results with a savgol filter
        if smooth_sigma:
            count_y = gaussian_filter1d (count_y, sigma=smooth_sigma)

        # Get percentiles percentiles
        stat = np.round (np.percentile (data, [10,25,50,75,90]), 2)
        y_max = count_y.max()

        data_dict = dict (
            x = [count_x, [stat[0],stat[0]], [stat[1],stat[1]], [stat[2],stat[2]], [stat[3],stat[3]], [stat[4],stat[4]]],
            y = [count_y, [0,y_max], [0,y_max], [0,y_max], [0,y_max], [0,y_max]],
            name = ["Density", "10%", "25%", "Median", "75%", "90%"],
            text = [None,
                [None, "10%<br>{}".format(stat[0])],
                [None, "25%<br>{}".format(stat[1])],
                [None, "Median<br>{}".format(stat[2])],
                [None, "75%<br>{}".format(stat[3])],
                [None, "90%<br>{}".format(stat[4])]],
        )

        # Make layout dict = Off set for labels on top
        layout_dict = {"yaxis.range": [0, y_max+y_max/6]}

        return [data_dict, layout_dict]

    #~~~~~~~2D DISTRIBUTION METHOD AND HELPER~~~~~~~#

    def reads_len_qual_2D (self,
        colorscale = [[0.0,'rgba(255,255,255,0)'], [0.1,'rgba(255,150,0,0)'], [0.25,'rgb(255,100,0)'], [0.5,'rgb(200,0,0)'], [0.75,'rgb(120,0,0)'], [1.0,'rgb(70,0,0)']],
        width = 1400,
        height = 600,
        len_nbins = None,
        qual_nbins = None,
        smooth_sigma = 2,
        sample = 100000):
        """
        Plot a 2D distribution of quality scores vs length of the reads
        * colorscale: a valid plotly color scale https://plot.ly/python/colorscales/ (Not recommanded to change)
        * width: With of the ploting area in pixel
        * height: height of the ploting area in pixel
        * len_nbins: Number of bins to divide the read length values in (x axis)
        * qual_nbins: Number of bins to divide the read quality values in (y axis)
        * smooth_sigma: standard deviation for 2D Gaussian kernel
        * sample: If given, a n number of reads will be randomly selected instead of the entire dataset
        """
        # Downsample if needed
        all_df = self.all_df.sample(sample) if sample and len(self.all_df)>sample else self.all_df
        pass_df = self.pass_df.sample(sample) if sample and len(self.pass_df)>sample else self.pass_df

        # Define extra ploting options
        if len_nbins==None: len_nbins = width//7
        if qual_nbins==None: qual_nbins = height//7

        # Prepare empty plot
        data = [
            go.Contour (name="Density", hoverinfo="name+x+y", colorscale=colorscale, showlegend=True, connectgaps=True, line={"width":0}),
            go.Scatter (mode='markers', name='Median', hoverinfo="name+x+y", marker={"size":12,"color":'black', "symbol":"x"})
            ]

        updatemenus = [
            dict (type="buttons", active=0, x=-0.2, y=0, xanchor='left', yanchor='bottom', buttons = [
                dict (label='All Reads', method='restyle',
                      args=[self.__reads_distr_2D_data (all_df, len_nbins=len_nbins, qual_nbins=qual_nbins, smooth_sigma=smooth_sigma)]),
                dict (label='Pass Reads', method='restyle',
                      args=[self.__reads_distr_2D_data (pass_df, len_nbins=len_nbins, qual_nbins=qual_nbins, smooth_sigma=smooth_sigma)]),
            ])]

        layout = go.Layout (
            hovermode = "closest",
            legend = {"x":-0.2, "y":1,"xanchor":'left',"yanchor":'top'},
            updatemenus = updatemenus,
            width = width,
            height = height,
            title = "Mean read quality per sequence length",
            xaxis = {"title":"Estimated Read Length", "showgrid":True, "zeroline":False, "showline":True, "type":"log"},
            yaxis = {"title":"Read Quality Scores", "showgrid":True, "zeroline":False, "showline":True,})

        fig = go.Figure (data=data, layout=layout)
        if self._iplot:
            py.iplot (fig, show_link=False)
        return fig

    def __reads_distr_2D_data (self, df, len_nbins, qual_nbins, smooth_sigma=1.5):
        """
        Private function preparing data for reads_len_qual_2D
        """

        len_data = df["num_bases"]
        qual_data = df["mean_qscore"]

        len_min, len_med, len_max = np.percentile (len_data, (0, 50, 100))
        qual_min, qual_med, qual_max = np.percentile (qual_data, (0, 50, 100))

        len_bins = np.logspace (start=np.log10((len_min)), stop=np.log10(len_max)+0.1, num=len_nbins, base=10)
        qual_bins = np.linspace (start=qual_min, stop=qual_max, num=qual_nbins)

        z, y, x = np.histogram2d (x=qual_data, y=len_data, bins=[qual_bins, len_bins])
        if smooth_sigma:
            z = gaussian_filter(z, sigma=smooth_sigma)

        z_min, z_max = np.percentile (z, (0, 100))

        # Extract label and values
        data_dict = dict (
            x = [x, [len_med]],
            y = [y, [qual_med]],
            z = [z, None],
            contours = [dict(start=z_min, end=z_max, size=(z_max-z_min)/15),None])

        return data_dict

    #~~~~~~~OUTPUT_OVER_TIME METHODS AND HELPER~~~~~~~#

    def output_over_time (self,
        cumulative_color="rgb(204,226,255)",
        interval_color="rgb(102,168,255)",
        width=1400,
        height=500,
        sample=100000):
        """
        Plot a yield over time
        * cumulative_color: Color of cumulative yield area (hex, rgb, rgba, hsl, hsv or any CSV named colors https://www.w3.org/TR/css-color-3/#svg-color
        * interval_color: Color of interval yield line (hex, rgb, rgba, hsl, hsv or any CSV named colors https://www.w3.org/TR/css-color-3/#svg-color
        * width: With of the ploting area in pixel
        * height: height of the ploting area in pixel
        * sample: If given, a n number of reads will be randomly selected instead of the entire dataset
        """

        # Downsample if needed
        all_df = self.all_df.sample(sample) if sample and len (self.all_df)>sample else self.all_df
        pass_df = self.pass_df.sample(sample) if sample and len (self.pass_df)>sample else self.pass_df

        # Prepare empty plots
        data = [
            go.Scatter (name="", fill='tozeroy', fillcolor=cumulative_color, mode='none'),
            go.Scatter (name="", mode='lines', line={'color':interval_color,'width':2}),
            go.Scatter (mode="lines+text", hoverinfo="skip", textposition='top center', line={'color':'gray','width':1,'dash':'dot'}),
            go.Scatter (mode="lines+text", hoverinfo="skip", textposition='top center', line={'color':'gray','width':1,'dash':'dot'}),
            go.Scatter (mode="lines+text", hoverinfo="skip", textposition='top center', line={'color':'gray','width':1,'dash':'dot'}),
            go.Scatter (mode="lines+text", hoverinfo="skip", textposition='top center', line={'color':'gray','width':1,'dash':'dot'}),
            go.Scatter (mode="lines+text", hoverinfo="skip", textposition='top center', line={'color':'gray','width':1,'dash':'dot'}),
        ]

        updatemenus = [
            dict (type="buttons", active=0, x=-0.06, y=0, xanchor='right', yanchor='bottom', buttons = [
                dict (label='All Reads', method='update', args=self.__output_over_time_data (all_df, level="reads")),
                dict (label='Pass Reads', method='update', args=self.__output_over_time_data (pass_df, level="reads")),
                dict (label='All Bases', method='update', args=self.__output_over_time_data (all_df, level="bases")),
                dict (label='Pass Bases', method='update', args=self.__output_over_time_data (pass_df, level="bases")),
            ])]

        layout = go.Layout (
            width=width,
            height=height,
            updatemenus=updatemenus,
            legend={"x":-0.05, "y":1,"xanchor":'right',"yanchor":'top'},
            title="Output over experiment time",
            yaxis={"title":"Cummulative Count", "zeroline":False, "showline":True, "fixedrange":True},
            xaxis={"title":"Experiment time (h)", "zeroline":False, "showline":True})

        fig = go.Figure(data=data, layout=layout)
        if self._iplot:
            py.iplot (fig, show_link=False)
        return fig

    def __output_over_time_data (self, df, level="reads"):
        """
        Private function preparing data for output_over_time
        """
        # Bin data in categories
        t = (df["start_time"]/3600).values
        t_min = t.min()
        t_max = t.max()
        x = np.linspace (t_min, t_max, int((t_max-t_min)*10))
        t = np.digitize (t, bins=x, right=True)

        # Count reads or bases per categories
        if level == "reads":
            y = np.bincount(t)
        elif level == "bases":
            y = np.bincount(t, weights=df["num_bases"].values)

        # Transform to cummulative distribution
        y_cum = np.cumsum(y)
        y_cum_max = y_cum[-1]

        # Smooth and rescale interval trace
        y = gaussian_filter1d (y, sigma=1)
        y = y*y_cum_max/y.max()

        # Find percentages of data generated
        lab_text = []
        lab_name = []
        lab_x = []
        for lab in (50, 75, 90, 99, 100):
            val = y_cum_max*lab/100
            idx = (np.abs(y_cum-val)).argmin()
            lab_text.append([None, '{}%<br>{}h<br>{:,} {}'.format(lab, round(x[idx],2), int(y_cum[idx]), level)])
            lab_x.append ([x[idx], x[idx]])
            lab_name.append ("{}%".format(lab))

        # make data dict
        data_dict = dict(
            x = [x, x]+lab_x,
            y = [y_cum, y, [0,y_cum_max], [0,y_cum_max], [0,y_cum_max], [0,y_cum_max], [0,y_cum_max]],
            name = ["Cumulative", "Interval"]+lab_name,
            text = [None, None]+lab_text
        )

        # Make layout dict = offset for labels on top
        layout_dict = {"yaxis.range": [0, y_cum_max+y_cum_max/6]}

        return [data_dict, layout_dict]

    #~~~~~~~QUAL_OVER_TIME METHODS AND HELPER~~~~~~~#

    def qual_over_time (self,
        median_color="rgb(102,168,255)",
        quartile_color="rgb(153,197,255)",
        extreme_color="rgba(153,197,255, 0.5)",
        smooth_sigma=1,
        width=1400,
        height=500,
        sample=100000):
        """
        Plot a mean quality over time
        * median_color: Color of median line color (hex, rgb, rgba, hsl, hsv or any CSV named colors https://www.w3.org/TR/css-color-3/#svg-color
        * quartile_color: Color of inter quartile area and lines (hex, rgb, rgba, hsl, hsv or any CSV named colors https://www.w3.org/TR/css-color-3/#svg-color
        * extreme_color:: Color of inter extreme area and lines (hex, rgb, rgba, hsl, hsv or any CSV named colors https://www.w3.org/TR/css-color-3/#svg-col
        * smooth_sigma: sigma parameter for the Gaussian filter line smoothing
        * width: With of the ploting area in pixel
        * height: height of the ploting area in pixel
        * sample: If given, a n number of reads will be randomly selected instead of the entire dataset
        """
        # Downsample if needed
        all_df = self.all_df.sample(sample) if sample and len (self.all_df)>sample else self.all_df
        pass_df = self.pass_df.sample(sample) if sample and len (self.pass_df)>sample else self.pass_df

        # Prepare empty plots
        data= [
            go.Scatter(mode="lines", line={"color":extreme_color}, connectgaps=True, legendgroup="Extreme"),
            go.Scatter(mode="lines", fill="tonexty", line={"color":extreme_color}, connectgaps=True, legendgroup="Extreme"),
            go.Scatter(mode="lines", line={"color":quartile_color}, connectgaps=True, legendgroup="Quartiles"),
            go.Scatter(mode="lines", fill="tonexty", line={"color":quartile_color}, connectgaps=True, legendgroup="Quartiles"),
            go.Scatter(mode="lines", line={"color":median_color}, connectgaps=True),
        ]

        updatemenus = [
            go.layout.Updatemenu (type="buttons", active=0, x=-0.07, y=0, xanchor='right', yanchor='bottom', buttons = [
                go.layout.updatemenu.Button (
                    label='All Reads', method='restyle', args=self.__qual_over_time_data (all_df, smooth_sigma=smooth_sigma)),
                go.layout.updatemenu.Button (
                    label='Pass Reads', method='restyle', args=self.__qual_over_time_data (pass_df, smooth_sigma=smooth_sigma)),
        ])]

        layout = go.Layout (
            width=width,
            height=height,
            updatemenus=updatemenus,
            legend={"x":-0.07, "y":1,"xanchor":'right',"yanchor":'top'},
            title="Mean Read Quality Over Experiment Time",
            yaxis={"title":"Mean Quality", "zeroline":False, "showline":True, "rangemode":'nonnegative', "fixedrange":True},
            xaxis={"title":"Experiment time (h)", "zeroline":False, "showline":True, "rangemode":'nonnegative'})

        fig = go.Figure(data=data, layout=layout)
        if self._iplot:
            py.iplot (fig, show_link=False)
        return fig

    def __qual_over_time_data (self, df, smooth_sigma=1.5):
        """
        Private function preparing data for qual_over_time
        """
        # Bin data in categories
        t = (df["start_time"]/3600).values
        t_min = t.min()
        t_max = t.max()
        x = np.linspace (t_min, t_max, int((t_max-t_min)*10))
        t = np.digitize (t, bins=x, right=True)

        # List quality value per categories
        bin_qual_dict = defaultdict (list)
        for bin_idx, qual in zip (t, df["mean_qscore"].values) :
            bin = x[bin_idx]
            bin_qual_dict[bin].append(qual)

        # Aggregate values per category
        val_name = ["Min", "Max", "25%", "75%", "Median"]
        stat_dict = defaultdict(list)
        for bin in x:
            if bin in bin_qual_dict:
                p = np.percentile (bin_qual_dict[bin], [0, 100, 25, 75, 50])
            else:
                p = [np.nan,np.nan,np.nan,np.nan,np.nan]
            for val, stat in zip (val_name, p):
                stat_dict[val].append(stat)

        # Values smoothing
        if smooth_sigma:
            for val in val_name:
                stat_dict [val] = gaussian_filter1d (stat_dict [val], sigma=smooth_sigma)

        # make data dict
        data_dict = dict(
            x = [x],
            y = [stat_dict["Min"], stat_dict["Max"], stat_dict["25%"], stat_dict["75%"], stat_dict["Median"]],
            name = val_name,
        )

        return [data_dict]

    #~~~~~~~BARCODE_COUNT METHODS AND HELPER~~~~~~~#

    def barcode_counts (self,
        min_percent_barcode = 0.1,
        colors = ["#f8bc9c", "#f6e9a1", "#f5f8f2", "#92d9f5", "#4f97ba"],
        width = 700,
        height = 600,
        sample = 100000):
        """
        Plot a mean quality over time
        * min_percent_barcode: minimal percentage od total reads for a barcode to be reported
        * colors: List of colors (hex, rgb, rgba, hsl, hsv or any CSV named colors https://www.w3.org/TR/css-color-3/#svg-color
        * width: With of the ploting area in pixel
        * height: height of the ploting area in pixel
        * sample: If given, a n number of reads will be randomly selected instead of the entire dataset
        """
        # Verify that barcode information are available
        assert "barcode" in self.all_df, "No barcode information available"

        # Downsample if needed
        all_df = self.all_df.sample(sample) if sample and len(self.all_df)>sample else self.all_df
        pass_df = self.pass_df.sample(sample) if sample and len(self.pass_df)>sample else self.pass_df

        # Prepare empty plot
        data = [
            go.Pie (sort=False, marker=dict(colors=colors))
            ]

        updatemenus = [
            dict (type="buttons", active=0, x=-0.2, y=0, xanchor='left', yanchor='bottom', buttons = [
                dict (label='All Reads', method='restyle',
                      args=[self.__barcode_counts_data (df=all_df, min_percent_barcode=min_percent_barcode)]),
                dict (label='Pass Reads', method='restyle',
                      args=[self.__barcode_counts_data (df=pass_df, min_percent_barcode=min_percent_barcode)]),
            ])]

        layout = go.Layout (
            legend = {"x":-0.2, "y":1,"xanchor":'left',"yanchor":'top'},
            updatemenus = updatemenus,
            width = width,
            height = height,
            title = "Percentage of reads per barcode")

        fig = go.Figure (data=data, layout=layout)
        if self._iplot:
            py.iplot (fig, show_link=False)
        return fig

    def __barcode_counts_data (self, df, min_percent_barcode=0.1):
        """
        Private function preparing data for barcode_counts
        """
        counts = df["barcode"].value_counts()
        counts = counts.sort_index()

        if min_percent_barcode:
            cuttoff = counts.sum()*min_percent_barcode/100
            counts = counts[counts>cuttoff]

        # Extract label and values
        data_dict = dict (
            labels = [counts.index],
            values = [counts.values])

        return data_dict

    #~~~~~~~BARCODE_COUNT METHODS AND HELPER~~~~~~~#

    def channels_activity (self,
        colorscale = [[0.0,'rgba(255,255,255,0)'], [0.01,'rgb(255,255,200)'], [0.25,'rgb(255,200,0)'], [0.5,'rgb(200,0,0)'], [0.75,'rgb(120,0,0)'], [1.0,'rgb(0,0,0)']],
        n_channels=512,
        smooth_sigma=1,
        width=2000,
        height=600,
        sample=100000):
        """
        Plot a yield over time
        * width: With of the ploting area in pixel
        * height: height of the ploting area in pixel
        * sample: If given, a n number of reads will be randomly selected instead of the entire dataset
        """

        # Downsample if needed
        all_df = self.all_df.sample(sample) if sample and len (self.all_df)>sample else self.all_df
        pass_df = self.pass_df.sample(sample) if sample and len (self.pass_df)>sample else self.pass_df

        # Prepare empty plots
        data = [
            go.Heatmap(xgap=0.5, colorscale=colorscale, hoverinfo="x+y+z"),
        ]

        updatemenus = [
            dict (type="buttons", active=0, x=-0.06, y=0, xanchor='right', yanchor='bottom', buttons = [
                dict (label='All Reads', method='restyle', args=self.__channels_activity_data (all_df, level="reads", n_channels=n_channels, smooth_sigma=smooth_sigma)),
                dict (label='Pass Reads', method='restyle', args=self.__channels_activity_data (pass_df, level="reads", n_channels=n_channels, smooth_sigma=smooth_sigma)),
                dict (label='All Bases', method='restyle', args=self.__channels_activity_data (all_df, level="bases", n_channels=n_channels, smooth_sigma=smooth_sigma)),
                dict (label='Pass Bases', method='restyle', args=self.__channels_activity_data (pass_df, level="bases", n_channels=n_channels, smooth_sigma=smooth_sigma)),
            ])]

        layout = go.Layout (
            width=width,
            height=height,
            updatemenus=updatemenus,
            title="Output per channel over experiment time",
            xaxis={"title":"Channel id", "zeroline":False, "showline":False, "nticks":20, "showgrid":False},
            yaxis={"title":"Experiment time (h)", "zeroline":False, "showline":False, "hoverformat":".2f", "fixedrange":True})

        fig = go.Figure(data=data, layout=layout)
        if self._iplot:
            py.iplot (fig, show_link=False)
        return fig

    def __channels_activity_data (self, df, level="bases", n_channels=512, smooth_sigma=2):
        # Bin data in categories
        t = (df["start_time"]/3600).values
        t_min = t.min()
        t_max = t.max()
        bins = np.linspace (t_min, t_max, int((t_max-t_min)*3))
        t = np.digitize (t, bins=bins, right=True)

        # Count values per categories
        z = np.ones((len(bins), n_channels), dtype=np.int)
        if level == "bases":
            for t_idx, channel, n_bases in zip(t, df["channel"], df["num_bases"]):
                z[t_idx][channel-1]+=n_bases
        elif level == "reads":
            for t_idx, channel in zip(t, df["channel"]):
                z[t_idx][channel-1]+=1

        # Time series smoothing
        if smooth_sigma:
            z = gaussian_filter1d (z.astype(np.float32), sigma=smooth_sigma, axis=0)

        # Define x and y axis
        x = ["c {}".format(i) for i in range(1, n_channels+1)]
        y = bins[1:]

        # Make data dict
        data_dict = dict (x=[x], y=[y], z=[z])

        return [data_dict]

    #~~~~~~~PRIVATE METHODS~~~~~~~#
    def _check_columns (self, df, colnames, raise_error_if_missing=True):
        col_found = []
        # Verify the presence of the columns required for pycoQC
        for col in colnames:
            if col in df:
                col_found.append(col)
            elif raise_error_if_missing:
                raise ValueError("Column {} not found in the provided sequence_summary file".format(col))
        return col_found
