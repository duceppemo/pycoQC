# -*- coding: utf-8 -*-

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~IMPORTS~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#

# Standard library imports
from collections import *
import warnings
import datetime

# Local lib import
from pycoQC.common import *
from pycoQC.pycoQC_parse import pycoQC_parse
from pycoQC.pycoQC_plot import pycoQC_plot
from pycoQC.pycoQC_report import pycoQC_report
from pycoQC import __name__ as package_name
from pycoQC import __version__ as package_version

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~GLOBAL SETTINGS~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#

# Silence futurewarnings
warnings.filterwarnings("ignore", category=FutureWarning)


#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~MAIN CLASS~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~#
def pycoQC(
        summary_file: str,
        barcode_file: str = "",
        bam_file: str = "",
        runid_list: list = (),
        filter_calibration: bool = False,
        filter_duplicated: bool = False,
        min_barcode_percent: float = 0.1,
        min_pass_qual: float = 7,
        min_pass_len: int = 0,
        sample: int = 100000,
        html_outfile: str = "",
        report_title: str = "PycoQC report",
        config_file: str = "",
        template_file: str = "",
        json_outfile: str = "",
        skip_coverage_plot: bool = False,
        verbose: bool = False,
        quiet: bool = False):
    """
    Parse Albacore sequencing_summary.txt file and clean-up the data
    * summary_file
        Path to a sequencing_summary generated by Albacore 1.0.0 + (read_fast5_basecaller.py) / Guppy 2.1.3+ (guppy_basecaller).
        One can also pass multiple space separated file paths or a UNIX style regex matching multiple files
    * barcode_file
        Path to the barcode_file generated by Guppy 2.1.3+ (guppy_barcoder) or Deepbinner 0.2.0+. This is not a required file.
        One can also pass multiple space separated file paths or a UNIX style regex matching multiple files
    * bam_file
        Path to a Bam file corresponding to reads in the summary_file. Preferably aligned with Minimap2
        One can also pass multiple space separated file paths or a UNIX style regex matching multiple files
    * runid_list
        Select only specific runids to be analysed. Can also be used to force pycoQC to order the runids for
        temporal plots, if the sequencing_summary file contain several sucessive runs. By default pycoQC analyses
        all the runids in the file and uses the runid order as defined in the file.
    * filter_calibration
        If True read flagged as calibration strand by the software are removed
    * filter_duplicated
        If True duplicated read_ids are removed but the first occurence is kept (Guppy sometimes outputs the same read multiple times)
    * min_barcode_percent
        Minimal percent of total reads to retain barcode label. If below the barcode value is set as `unclassified`.
    * min_pass_qual
        Minimum quality to consider a read as 'pass'
    * min_pass_len
        Minimum read length to consider a read as 'pass'
    * sample
        If not None a n number of reads will be randomly selected instead of the entire dataset for ploting function (deterministic sampling)
    * html_outfile
        Path to an output html file report
    * report_title
        Title to use in the html report
    * config_file
        Path to a JSON configuration file for the html report.
        If not provided, falls back to default parameters.
        The first level keys are the names of the plots to be included.
        The second level keys are the parameters to pass to each plotting function
    * template_file
        Jinja2 html template for the html report
    * json_outfile
        Path to an output json file report
    * verbose
        Increase verbosity
    * quiet
        Reduce verbosity
    """

    # Save args and init options in dict for report
    options_d = locals()
    info_d = {"package_name": package_name, "package_version": package_version,
              "timestamp": str(datetime.datetime.now())}

    # Set logging level
    logger = get_logger(name=__name__, verbose=verbose, quiet=quiet)
    logger.warning("Checking arguments values")

    # Save all verified values + type
    runid_list = check_arg("runid_list", runid_list, required_type=list, allow_none=True)
    filter_calibration = check_arg("filter_calibration", filter_calibration, required_type=bool,
                                   allow_none=False)
    filter_duplicated = check_arg("filter_duplicated", filter_duplicated, required_type=bool,
                                  allow_none=False)
    min_barcode_percent = check_arg("min_barcode_percent", min_barcode_percent, required_type=float,
                                    min=0, max=100, allow_none=False)
    min_pass_qual = check_arg("min_pass_qual", min_pass_qual, required_type=float, min=0, max=60,
                              allow_none=False)
    min_pass_len = check_arg("min_pass_len", min_pass_len, required_type=int, min=0, allow_none=False)
    sample = check_arg("sample", sample, required_type=int, min=0, allow_none=True)
    html_outfile = check_arg("html_outfile", html_outfile, required_type=str, allow_none=True)
    html_outfile = check_arg("html_outfile", html_outfile, required_type=str, allow_none=True)
    report_title = check_arg("report_title", report_title, required_type=str, allow_none=True)
    config_file = check_arg("config_file", config_file, required_type=str, allow_none=True)
    template_file = check_arg("template_file", template_file, required_type=str, allow_none=True)
    json_outfile = check_arg("json_outfile", json_outfile, required_type=str, allow_none=True)
    skip_coverage_plot = check_arg("skip_coverage_plot", skip_coverage_plot, required_type=bool,
                                   allow_none=False)

    # Print debug info
    logger.debug("General info")
    logger.debug(dict_to_str(info_d))
    logger.debug("Runtime options")
    logger.debug(dict_to_str(options_d))

    #~~~~~~~~~~pycoQC_parse~~~~~~~~~~#
    parser = pycoQC_parse(
        summary_file=summary_file,
        barcode_file=barcode_file,
        bam_file=bam_file,
        runid_list=runid_list,
        filter_calibration=filter_calibration,
        filter_duplicated=filter_duplicated,
        min_barcode_percent=min_barcode_percent,
        verbose=verbose,
        quiet=quiet)

    logger.debug("Parser stats")
    logger.debug(parser)

    #~~~~~~~~~~pycoQC_plot~~~~~~~~~~#
    plotter = pycoQC_plot(
        parser=parser,
        min_pass_qual=min_pass_qual,
        min_pass_len=min_pass_len,
        sample=sample,
        verbose=verbose,
        quiet=quiet)

    logger.debug("Plotter stats")
    logger.debug(plotter)

    #~~~~~~~~~~pycoQC_report~~~~~~~~~~#
    if html_outfile or json_outfile:
        reporter = pycoQC_report(
            parser=parser,
            plotter=plotter,
            verbose=verbose,
            quiet=quiet)

        if html_outfile:
            reporter.html_report(
                outfile=html_outfile,
                config_file=config_file,
                template_file=template_file,
                report_title=report_title,
                skip_coverage_plot=skip_coverage_plot)

        # Run json output function
        if json_outfile:
            reporter.json_report(
                outfile=json_outfile)

    #~~~~~~~~~~return plotting object for API~~~~~~~~~~#
    return plotter
