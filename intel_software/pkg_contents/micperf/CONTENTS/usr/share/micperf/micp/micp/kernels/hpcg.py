#  Copyright 2017, Intel Corporation, All Rights Reserved.
#
# This software is supplied under the terms of a license
# agreement or nondisclosure agreement with Intel Corp.
# and may not be copied or disclosed except in accordance
# with the terms of that agreement.
#
#  Author: Luis Sandoval

import os
import math
import tempfile

import micp.kernel as micp_kernel
import micp.info as micp_info
import micp.common as micp_common
import micp.params as micp_params

from micp.kernel import raise_parse_error

HPCG_CONFIG_FILE = """HPCG benchmark input file
Sandia National Laboratories; University of Tennessee, Knoxville
{0} {0} {0}
{1}"""

HPCG_CONFIG_FILE_NAME = 'hpcg.dat'
_8_GB = 8*1024**3

# For best HPCG performance use 4 MPI ranks, 32 threads per rank
_4_MPI_RANKS = 4
_32_THREADS = 32

DEFAULT_SCORE_TAG = 'Computation.Avg'

class hpcg(micp_kernel.Kernel):
    """Implements kernel interface for the HPCG benchmark. (Linux)"""

    def __init__(self):
        self.name = 'hpcg'

        # HPCG lastest output information, latest log name and working directory
        self._hpcg_output_info = {}
        self._lastest_hpcg_log = None
        self._working_directory = None

        self.param_validator = micp_params.HPCG_VALIDATOR
        self._paramNames = ['problem_size', 'time', 'omp_num_threads']

        max_problem = 128

        self._paramDefaults = {'time':60, 'problem_size':max_problem, 'omp_num_threads':_32_THREADS}

        # Initialize parameters for scaling and optimal categories
        self._categoryParams = {}
        self._categoryParams['test'] = [' ']

        args = '--problem_size {0} --time 60 --omp_num_threads {1}'

        # optimal problems should be multiple of 32
        valid_problems = range(32, max_problem+32, 32)
        self._categoryParams['scaling'] = [args.format(problem, _32_THREADS)
                                           for problem in valid_problems]

        self._categoryParams['scaling_quick'] = [args.format(problem, _32_THREADS)
                                                 for problem in valid_problems]

        self._categoryParams['optimal_quick'] = [args.format(valid_problems[-1], _32_THREADS)]

        # parameters for scaling_core category, use 2, 4, ... up to 32 threads
        self._categoryParams['scaling_core'] = [args.format(max_problem, _threads)
                                                for _threads in range(2, _32_THREADS+2, 2)]
        self._set_defaults_to_optimal()


    def _do_unit_test(self):
        """HCPG includes a self-test"""
        return True


    def offload_methods(self):
        """returns a list of supported offload methods"""
        return ['local']


    def path_host_exec(self, offType):
        """returns path to knightslanding HPCG binary in the MKLROOT directory,
        raises exception if environment variable MKLROOT is not set or binary is
        not found. Returns None if offload_type is not supported """
        if offType == 'local':
            if micp_common.is_platform_windows():
                raise OSError("ERROR: Windows is not supported at this time")

            if micp_common.is_selfboot_platform():
                binary = 'xhpcg_knl'
            else:
                binary = 'xhpcg_avx2'

            if 'MKLROOT' in os.environ:
                return self._search_path_to_file(os.environ['MKLROOT'], binary)

            error = ("MKLROOT not in environment.  Source composer's"
                     " compilervars.sh before running hplinpack")
            raise micp_kernel.NoExecutableError(error)
        return None


    def path_dev_exec(self, offType):
        """returns None, Intel Xeon Phi Coprocessors not supported yet"""
        return None


    def path_aux_data(self, offType):
        """returns empty list, no additional libraries needed to run hpcg"""
        return []


    def param_type(self):
        """returns the kernel's parameter type ('file' for hpcg)"""
        return 'file'


    def _parse_hpcg_output(self):
        """look into the HPCG working directory and parse the most recent log
        available, information is stored in a dictionary (_hpcg_output_info)"""
        all_files = os.listdir(self._working_directory)

        # hpcg expected log name  format: n{size}-{ranks}-{threads}.*.yaml
        # e.g. n160-4p-32t-color-2-4-2.4_2016.04.28.20.36.20.yaml
        is_a_log_file = lambda name: name.startswith('n') and name.endswith('.yaml')
        hpcg_log_files = filter(is_a_log_file, all_files)
        hpcg_log_files = [os.path.join(self._working_directory, f) for f in hpcg_log_files]
        hpcg_log_files = sorted(hpcg_log_files, key=os.path.getctime)

        if not hpcg_log_files:
            raise_parse_error(self._lastest_hpcg_log,
            "NO HPCG *.yaml logs found in: {0}.".format(self._working_directory))

        # each file should be parsed only once
        newer_log = os.path.abspath(hpcg_log_files[-1])
        if self._lastest_hpcg_log == newer_log:
            return

        with open(newer_log) as filehandle:
            hpcg_log_content = filehandle.read()

        self._hpcg_output_info = dict([tuple([ll.strip() for ll in line.split(':')])
                                       for line in hpcg_log_content.splitlines()
                                       if ':' in line and line.find(':') == line.rfind(':')])

        self._lastest_hpcg_log = newer_log

        print "For HPCG execution details please refer to the logs:\n"
        print "    Log Directory: {0}".format(os.path.dirname(os.path.realpath(newer_log)))
        print "    HPCG current test log: {0}".format(newer_log)
        print "\n"


    def parse_desc(self, raw):
        """parses the most recent HPCG log and returns a summary (string) of the
        HPCG run-time parameters. Raises and exception if kernel failed."""
        self._parse_hpcg_output()

        try:
            nx = self._hpcg_output_info['nx']
            ny = self._hpcg_output_info['ny']
            nz = self._hpcg_output_info['nz']
            ranks = self._hpcg_output_info['Distributed Processes']
            threads = self._hpcg_output_info['Threads per processes']
        except KeyError:
            error_message = "HPCG failed, please refer to the logs for further details"
            raise micp_kernel.SelfCheckError(error_message.format(self._lastest_hpcg_log))

        result = 'hpcg Local Dimensions nx={0}, ny={1}, nz={2}, MPI ranks {3}, threads per rank {4}'
        return result.format(nx, ny, nz, ranks, threads)


    def parse_perf(self, raw):
        """parses the most recent HPCG log and returns the performance reported
        by the kernel. Raises an exception if results are not available"""
        self._parse_hpcg_output()

        try:
            speed = self._hpcg_output_info['HPCG result is VALID with a GFLOP/s rating of']
        except KeyError:
            raise_parse_error(self._lastest_hpcg_log,
                "HPCG failed, please refer to the logs for further details")

        result = {}
        result[DEFAULT_SCORE_TAG] = {'value':speed, 'units':'GFlops', 'rollup':True}
        return result


    def environment_dev(self):
        """returns empty dictionary, Intel Xeon Phi Coprocessors not supported"""
        return {}


    def environment_host(self):
        """returns a dictionary with the environment variables to be set on the host"""
        mic_sb = {'OMP_NUM_THREADS':str(_32_THREADS),
                  'KMP_AFFINITY':'granularity=fine,balanced',
                  'KMP_HW_SUBSET':'16c,2t'}

        if micp_common.is_selfboot_platform():
            return mic_sb
        else:
            return {}


    def independent_var(self, category):
        """returns independent variable for plots/tables (depends on the kernel
        parameters category)"""
        if category == 'scaling_core':
            return 'omp_num_threads'
        return 'problem_size'


    def _search_path_to_file(self, directory, binary_name):
        """searches binary_name, in the given directory, returns the full path
        to the first match"""
        for root, __, files in os.walk(directory):
            if binary_name in files:
                return os.path.join(root, binary_name)
        raise micp_kernel.NoExecutableError


    def get_process_modifiers(self):
        """returns the mpi/numactl command line (as a list) needed to run hpcg
        with 4 mpi ranks and bind the process to an MCDRAM node (if available)"""
        info = micp_info.Info()
        if info.is_processor_mcdram_available():
            return ['numactl', '--membind=1', 'mpirun', '-n', str(_4_MPI_RANKS)]
        else:
            return ['mpirun', '-n', str(_4_MPI_RANKS)]


    def param_file(self, param):
        """create configuration file 'hpcg.dat' for the given parameters 'param'
        in the working directory, return the absolute path to the caller"""

        problem_size = param.get_named('problem_size')
        time = param.get_named('time')

        if self._working_directory is None:
            self._working_directory = tempfile.mkdtemp(prefix='micperf_hpcg_logs_')

        config_file_content = HPCG_CONFIG_FILE.format(problem_size, time)
        config_file_path = os.path.join(self._working_directory, HPCG_CONFIG_FILE_NAME)

        with open(config_file_path, 'w') as fid:
            fid.write(config_file_content)

        return config_file_path


    def get_working_directory(self):
        """return HPCG working directory"""
        return self._working_directory


    def is_mpi_required(self):
        """HPCG requires MPI at all times"""
        return True

    def _ordering_key(self, stat):
        return float(stat.perf[DEFAULT_SCORE_TAG]['value'])
