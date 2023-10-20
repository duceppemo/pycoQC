# Disable multithreading for MKL and openBlas
import os
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["MKL_THREADING_LAYER"] = "sequential"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ['OPENBLAS_NUM_THREADS'] = '1'

#~~~~~~~~~~~~~~IMPORTS~~~~~~~~~~~~~~#
# Standard library imports
import multiprocessing as mp
from time import time
from collections import *
from collections import *
import traceback
import logging
from itertools import islice
import gzip

# Third party imports
from tqdm import tqdm
from dateutil.parser import parse

# Local imports
from pycoQC.common import *
import functions


# Logger setup
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)
logLevel_dict = {2: logging.DEBUG, 1: logging.INFO, 0: logging.WARNING}


#~~~~~~~~~~~~~~CLASS~~~~~~~~~~~~~~#
class FastqParser(object):
    @staticmethod
    def make_chunks(file_handle, size):
        while True:
            chunk = list(islice(file_handle, size))
            if not chunk:
                break
            yield chunk

    @staticmethod
    def read_entry(entry, fastq_name, flag):
        my_dict = dict()
        lines = list()
        for line in entry:
            line = line.rstrip()
            lines.append(line)
            if len(lines) == 4:
                my_dict.update(FastqParser.single_fastq_entry_to_dict(lines, fastq_name, flag))
                lines = list()
        return my_dict

    @staticmethod
    def single_fastq_entry_to_dict(fastq_entry, fastq_name, flag):
        """
        Fields in fastq header from Guppy:

        @20a271c3-8f4b-466c-92b8-50a469aaa3e4
        runid=acfd15dcc73bb7bafd19e1fdbe72a535d7558bf1
        sampleid=run3_no_enrichment
        read=2743
        ch=207
        start_time=2022-06-27T23:14:28Z
        model_version_id=2021-11-17_dna_r10.4_minion_promethion_1024_67af0493
        barcode=barcode17
        """

        header, seq, extra, qual = fastq_entry  # get each component of list in a variable

        # Split header line to get items and store in dictionary
        items = header.split()
        read_dict = dict()
        for i in items[1:]:
            key, value = i.split('=')
            read_dict[key] = value

        # Some fields will be absent if fastq not generated Guppy, thus the use of try/except statements
        # Get the values of interest into the dictionary
        try:
            run_id = read_dict['runid']
        except KeyError:
            run_id = ''
        try:
            time_string = parse(read_dict['start_time'])
        except KeyError:
            time_string = ''
        try:
            channel = read_dict['ch']
        except KeyError:
            channel = ''
        try:
            barcode = read_dict['barcode']
        except KeyError:
            barcode = ''

        # The following values are always present in any given fastq
        read_id = items[0][1:]  # remove the leading "@"
        length = len(seq)

        # Average phred score
        phred_list = [ord(letter) - 33 for letter in qual]
        average_phred = round(functions.compute_average_quality(phred_list, length), 2)  # cython

        # %GC
        g_count = float(seq.count('G'))
        c_count = float(seq.count('C'))
        gc = round((g_count + c_count) / float(length) * 100, 2)

        # Flag
        if flag == 'pass':
            flag = 'TRUE'
        else:
            flag = 'FALSE'

        # Output everyting in a dictionary
        entry_dict = dict()
        # entry_dict[read_id] = (run_id, time_string, channel, barcode, average_phred, length, gc)
        entry_dict[read_id] = dict()
        entry_dict[read_id]['read_id'] = read_id
        entry_dict[read_id]['run_id'] = run_id
        entry_dict[read_id]['channel'] = channel
        entry_dict[read_id]['barcode_arrangement'] = barcode
        entry_dict[read_id]['sequence_length_template'] = length
        entry_dict[read_id]['mean_qscore_template'] = average_phred
        entry_dict[read_id]['gc_percent'] = gc
        entry_dict[read_id]['start_time'] = time_string
        entry_dict[read_id]['passes_filtering'] = flag

        return entry_dict

    @staticmethod
    def iterate_fastq_parallel(input_fastq, cpu):
        # Fastq file name
        fastq_name = os.path.basename(input_fastq).split('.')[0].split('_')[0]

        # Flag
        flag = 'pass'  # Default value
        if 'fail' in input_fastq:
            flag = 'fail'  # Check in path for the word "fail"

        # Chunk fastq files and run chunks in parallel
        fastq_dict = dict()
        with gzip.open(input_fastq, "rt") if input_fastq.endswith('.gz') else open(input_fastq, "r") as f:
            pool = mp.Pool(int(cpu))
            jobs = [pool.apply_async(FastqParser.read_entry, [chunk, fastq_name, flag])
                    for chunk in FastqParser.make_chunks(f, 4000)]
            results = [j.get() for j in jobs]
            pool.close()
            pool.join()
            pool.terminate()  # Needed to do proper garbage collection?

            # Update self.sample_dict with results from every chunk
            for d in results:
                fastq_dict.update(d)  # Do the merge

        return fastq_dict


class Fastq_to_seq_summary():
    """
    Create a summary file akin the one generated by Albacore or Guppy from a directory containing
    multiple fastq files. The script will attempt to extract all the required fields but will not
    raise an error if not found.
    """
    
    def __init__(self,
                 fastq_dir: str,
                 seq_summary_fn: str,
                 max_fastq: int = 0,
                 threads: int = 4,
                 basecall_id: int = 0,
                 verbose_level: int = 0,
                 include_path: bool = False,
                 fields: list = ("read_id", "run_id", "channel", "start_time", "gc_percent",
                                 "sequence_length_template", "mean_qscore_template",
                                 "calibration_strand_genome_template", "barcode_arrangement")):
        """
        * fastq_dir
            Directory containing fastqfiles. Can contain multiple subdirectories
        * seq_summary_fn
            path of the summary sequencing file where to write the data extracted from the fastq files
        * max_fastq
            Maximum number of file to try to parse. 0 to deactivate
        * threads
            Total number of threads to use. 1 thread is used for the reader and 1 for the writer. Minimum 3(default = 4)
        * fields
            list of field names corresponding to attributes to try to fetch from the fastq files. List a valid field names:
            mean_qscore_template, sequence_length_template, called_events, skip_prob, stay_prob, step_prob, strand_score, read_id, start_time,
            duration, start_mux, read_number, channel, channel_digitisation, channel_offset, channel_range, channel_sampling,
            run_id, sample_id, device_id, protocol_run, flow_cell, calibration_strand, calibration_strand, calibration_strand,
            calibration_strand, barcode_arrangement, barcode_full, barcode_score, gc_percent
        * basecall_id
            id of the basecalling group. By default, leave to 0, but if you perform multiple basecalling on the same fastq files,
            this can be used to indicate the corresponding group(1, 2 ...)
        * include_path
            If True the absolute path to the corresponding file is added in an extra column
        * verbose_level
            Level of verbosity, from 2(Chatty) to 0(Nothing)
        """
        # Set logging level
        logger.setLevel(logLevel_dict.get(verbose_level, logging.WARNING))

        # Perform checks
        logger.info("Check input data and options")
        if not os.access(fastq_dir, os.R_OK):
            raise pycoQCError("Cannot read the indicated fastq directory")
        if not os.access(os.path.dirname(seq_summary_fn), os.W_OK):
            raise pycoQCError("Cannot write the indicated seq_summary_fn")
        if threads < 3:
            raise pycoQCError("At least 3 threads required")

        # Save self args
        self.fastq_dir = fastq_dir
        self.seq_summary_fn = seq_summary_fn
        self.threads = threads-2
        self.max_fastq = max_fastq
        self.fields = fields
        self.basecall_id = basecall_id
        self.include_path = include_path
        self.verbose_level = verbose_level

        # Init Multiprocessing variables
        in_q = mp.Queue(maxsize=1000)
        out_q = mp.Queue(maxsize=1000)
        error_q = mp.Queue()
        counter_q = mp.Queue()

        # Define processes
        ps_list = [mp.Process(target=self._list_fastq, args=(in_q, error_q))]
        for i in range(self.threads):
            ps_list.append(mp.Process(target=self._read_fastq, args=(in_q, out_q, error_q, counter_q, i)))
        ps_list.append(mp.Process(target=self._write_seq_summary, args=(out_q, error_q, counter_q)))

        logger.info("Start processing fastq files")
        try:
            # Start all processes
            for proc in ps_list:
                proc.start()
            # Monitor error queue
            for tb in iter(error_q.get, None):
                raise pycoQCError(tb)
            # Join processes
            for proc in ps_list:
                proc.join()

        # Kill processes if any error
        except(BrokenPipeError, KeyboardInterrupt, pycoQCError) as E:
            for proc in ps_list:
                proc.terminate()
            logger.info("\nAn error occurred. All processes were killed\n")
            raise E

    def _list_fastq(self, in_q, error_q):
        """
        Mono-threaded worker adding fastq files found in a directory tree recursively
        to a feeder queue for the multiprocessing workers
        """
        logger.debug("[READER] Start listing fastq files")
        try:
            # Load an input queue with fastq file path
            my_ext = ['fq', 'fq.gz', 'fastq', 'fastq.gz']
            i = 0
            for fastq_fn in recursive_file_gen(dir=self.fastq_dir, ext=my_ext):
                i += 1
                if self.max_fastq and i == self.max_fastq:
                    break
                in_q.put(fastq_fn)

            # Raise error is no file found
            if i == 0:
                raise pycoQCError("No valid fastq files found in indicated folder")

            logger.debug("[READER] Add a total of {} files to input queue".format(i+1))

        # Manage exceptions and deal poison pills
        except Exception:
            error_q.put(traceback.format_exc())
        finally:
            for i in range(self.threads):
                in_q.put(None)

    def _read_fastq(self, in_q, out_q, error_q, counter_q, worker_id):
        """
        Multi-threaded workers in charge of parsing fastq file.
        """
        logger.debug("[WORKER_{:02}] Start processing fastq files".format(worker_id))
        try:
            c = {"overall": Counter(), "fields_found": Counter(), "fields_not_found": Counter()}

            # Find t zero

            # Parse fastq file(s)
            for fastq_fn in iter(in_q.get, None):
                # Try to extract data from the fastq file
                d = OrderedDict()
                value_dict = FastqParser.iterate_fastq_parallel(fastq_fn, self.threads)  # Field value

                # Fetch required fields is available
                """
                "read_id", "run_id", "channel", "start_time",
                "sequence_length_template", "mean_qscore_template", "gc_percent"
                "calibration_strand_genome_template", "barcode_arrangement"
                """
                for read_id, read_info_dict in value_dict.items():
                    for field in self.fields:
                        if field in read_info_dict:
                            d[field] = read_info_dict[field]
                            c["fields_found"][field] += 1
                        else:
                            c["fields_not_found"][field] += 1

                    if self.include_path:
                        d["path"] = os.path.abspath(fastq_fn)

                    # Put read data in queue
                    if d:
                        out_q.put(d)
                        c["overall"]["valid files"] += 1
                    else:
                        c["overall"]["invalid files"] += 1

            # Put counter in counter queue
            counter_q.put(c)

        # Manage exceptions and deal poison pills
        except Exception:
            error_q.put(traceback.format_exc())
        finally:
            out_q.put(None)

    def _write_seq_summary(self, out_q, error_q, counter_q):
        """
        Mono-threaded Worker writing the sequencing summary file
        """
        logger.debug("[WRITER] Start collecting summary data")

        t = time()
        try:
            l = []
            with tqdm(unit=" reads", mininterval=0.1, smoothing=0.1, disable=self.verbose_level == 2) as pbar:
                # Collect line data
                for _ in range(self.threads):
                    for d in iter(out_q.get, None):
                        l.append(d)
                        pbar.update(1)

            # Transform collected data to dataframe and write to file
            logger.debug("[WRITER] Write data to file")
            df = pd.DataFrame(l)

            # Convert "start_time" column to datetime
            df['start_time'] = pd.to_datetime(df['start_time'])

            # Convert datetime to elapsed minutes
            time_zero = df.loc[:, 'start_time'].min()  # looking for min of 1st elements of list of tuples
            df.loc[:, 'start_time'] = df.loc[:, 'start_time'] - time_zero
            df.loc[:, 'start_time'] = df.loc[:, 'start_time'].dt.total_seconds()
            try:  #
                df.loc[:, 'start_time'] = df.loc[:, 'start_time'].astype(int)  # Convert to integer
            except pd.errors.IntCastingNaNError:
                pass


            df.to_csv(self.seq_summary_fn, sep="\t", index=False)

            # Collapse data from counters coming from workers
            logger.debug("[WRITER] Summarize counters")
            c = {"overall": Counter(), "fields_found": Counter(), "fields_not_found": Counter()}
            for _ in range(self.threads):
                worker_c = counter_q.get()
                for k, v in worker_c.items():
                    for k2, v2 in v.items():
                        c[k][k2] += v2

            logger.info("Overall counts {}".format(dict_to_str(c["overall"])))
            logger.info("fields found {}".format(dict_to_str(c["fields_found"])))
            logger.info("fields not found {}".format(dict_to_str(c["fields_not_found"])))

            # Print final
            logger.warning("Total reads: {} / Average speed: {} reads/s\n".format(len(df),
                                                                                  round(len(df) / (time() - t), 2)))

        # Manage exceptions and deal poison pills
        except Exception:
            error_q.put(traceback.format_exc())
        finally:
            error_q.put(None)
