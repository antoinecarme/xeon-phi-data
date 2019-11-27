#  Copyright 2017, Intel Corporation, All Rights Reserved.
#
# This software is supplied under the terms of a license
# agreement or nondisclosure agreement with Intel Corp.
# and may not be copied or disclosed except in accordance
# with the terms of that agreement.
#
#  Author: Luis Sandoval

import os
import re
import tempfile
import shutil

import micp.kernel as micp_kernel
import micp.info as micp_info
import micp.common as micp_common
import micp.params as micp_params


from micp.kernel import raise_parse_error

DEFAULT_SCORE_TAG = 'Computation.Avg'

HPLINPACK_CONFIG_FILE = """HPLinpack benchmark input file
Innovative Computing Laboratory, University of Tennessee
HPL.out      output file name (if any)
6            device out (6=stdout,7=stderr,file)
1            # of problems sizes (N)
{problem_size}    Ns
1            # of NBs
{block_size}     NBs
1            PMAP process mapping (0=Row-,1=Column-major)
1            # of process grids (P x Q)
1            Ps
1            Qs
16.0         threshold
1            # of panel fact
1            PFACTs (0=left, 1=Crout, 2=Right)
1            # of recursive stopping criterium
4            NBMINs (>= 1)
1            # of panels in recursion
2            NDIVs
1            # of recursive panel fact.
1            RFACTs (0=left, 1=Crout, 2=Right)
1            # of broadcast
6            BCASTs (0=1rg,1=1rM,2=2rg,3=2rM,4=Lng,5=LnM,6=Psh,7=Psh2)
1            # of lookahead depth
0            DEPTHs (>=0)
0            SWAP (0=bin-exch,1=long,2=mix)
1           swapping threshold
1            L1 in (0=transposed,1=no-transposed) form
1            U  in (0=transposed,1=no-transposed) form
0            Equilibration (0=no,1=yes)
8            memory alignment in double (> 0)
"""

HPLINPACK_CONFIG_FILE_NAME = 'HPL.dat'
MIC_BLOCKSIZE = 336
HOST_BLOCKSIZE = 1280
PROCESSOR_MAX_MATRIX_SIZE = 100000
COPROCESSOR_MAX_MATRIX_SIZE = 40000
SCALING_CORE_MATRIX = 20000


class hplinpack(micp_kernel.Kernel):
    """Implements kernel interface for the HPLinpack benchmark (Only Linux)"""

    _SUPPORTED_OFFLOAD_METHODS = ('local', 'native', 'scif')

    def __init__(self):
        info = micp_info.Info()
        physical_cores = info.num_cores()
        max_matrix_size = self._get_max_matrix_size()
        matrix_step_size = max_matrix_size / 10

        self.name = 'hplinpack'
        self.param_validator = micp_params.HPLINPACK_VALIDATOR
        self._paramNames = ['problem_size', 'block_size', 'hpl_numthreads']
        self._paramDefaults = {'problem_size' : str(max_matrix_size),
                               'block_size' : str(MIC_BLOCKSIZE),
                               'hpl_numthreads' : str(physical_cores)}

        self._working_directory = None

        # parameters for scaling and optimal categories
        self._categoryParams = {}
        self._categoryParams['test'] = [' ']

        args = '--problem_size {0} --block_size {1} --hpl_numthreads {2}'
        self._categoryParams['scaling'] = [args.format(problem, MIC_BLOCKSIZE, physical_cores)
                                           for problem in range(matrix_step_size, max_matrix_size + matrix_step_size, matrix_step_size)]

        self._categoryParams['optimal'] = self._categoryParams['scaling'][-1:]

        # scaling core category, parameters calculated experimentally
        # optimal matrix requires 3.2GB, data points will be collected every 10 cores
        cores_step_size = int(round(physical_cores/10.0))
        self._categoryParams['scaling_core'] = [args.format(SCALING_CORE_MATRIX, MIC_BLOCKSIZE, cores)
                                                for cores in range(cores_step_size, physical_cores, cores_step_size)]
        self._categoryParams['scaling_core'].append(args.format(SCALING_CORE_MATRIX, MIC_BLOCKSIZE, physical_cores))

        # quick categories
        self._categoryParams['scaling_quick'] = self._categoryParams['scaling'][:4]
        self._categoryParams['optimal_quick'] = self._categoryParams['scaling'][3:4]

        # NOTE: there's no need to call self._set_defaults_to_optimal(), default
        # parameters have already been set, besides HPLINPACK parameters may
        # vary depending on the offload method. self.param_defaults() has been
        # specialized for this purpose


    @staticmethod
    def _get_max_matrix_size():
        """returns the max matrix size that can be executed based on the amount
        of memory available, in the case of the KNL Processor the amount of DDR
        memory sets the limit"""

        if not micp_common.is_selfboot_platform():
            return COPROCESSOR_MAX_MATRIX_SIZE

        ddr_memory_size = micp_info.Info().ddr_memory_size() / 1024 # size in GB

        if not ddr_memory_size:
            raise ValueError("ERROR: No DDR memory available on the processor")

        # "min memory size in GB" -> "max matrix size", sizes calculated empirically
        hpl_matrices = {}
        hpl_matrices[23] = 50000
        hpl_matrices[34] = 60000
        hpl_matrices[45] = 70000
        hpl_matrices[59] = 80000
        hpl_matrices[75] = 90000
        hpl_matrices[93] = PROCESSOR_MAX_MATRIX_SIZE

        for min_memory_required in sorted(hpl_matrices.keys(), reverse=True):
            if ddr_memory_size > min_memory_required:
                return hpl_matrices[min_memory_required]

        raise ValueError("Not enough memory to run HPLinpack on this system.")


    def _do_unit_test(self):
        """hplinpack includes a self-check test"""
        return True


    def offload_methods(self):
        """returns list of supported offload methods"""
        return self._SUPPORTED_OFFLOAD_METHODS


    def _search_path_to_file(self, directory, binary_name):
        """searches binary_name, in the given directory, returns the full path
        to the first match or None if binary is not found"""
        for root, __, files in os.walk(directory):
            if binary_name in files:
                return os.path.join(root, binary_name)
        return None


    def _path_to_hpl_exec(self, offload_type):
        """returns path to hplinpack binary in MKLROOT directory, raises
        exception. If MKLROOT environment directory is not set or binary
        is not found. Returns None if offload_type is not supported"""

        if offload_type not in self._SUPPORTED_OFFLOAD_METHODS:
            return None

        if micp_common.is_platform_windows():
            raise OSError("ERROR: Windows is not supported at this time")

        if 'MKLROOT' not in os.environ:
            error = ("MKLROOT not in environment.  Source composer's"
                     " compilervars.sh before running hplinpack")
            raise micp_kernel.NoExecutableError(error)

        binaries = ['xhpl_intel64', 'xhpl_intel64_static']
        for hpl_binary in binaries:
            hpl_path = self._search_path_to_file(os.environ['MKLROOT'], hpl_binary)
            if hpl_path is not None:
                return hpl_path

        raise micp_kernel.NoExecutableError('ERROR: HPLinpack binary not found')


    def path_host_exec(self, offload_type):
        """returns absolute path to HPL binary for the Xeon Phi Processor"""
        return self._path_to_hpl_exec(offload_type)


    def path_dev_exec(self, offload_type):
        """returns absolute path to HPL binary for the Xeon Phi Coprocessor"""
        return self._path_to_hpl_exec(offload_type)


    def path_aux_data(self, offload_type):
        """returns empty list, no additional libraries are needed to
        execute hplinpack"""
        return []


    def param_type(self):
        """returns the kernel's parameter type ('file' for hplinpack)"""
        return 'file'


    def parse_desc(self, raw):
        """Parses the raw HPLinpack output and returns a string that summarizes
        the parameters used for the execution. Raises an exception if kernel
        execution failed"""

        # Raise exception if self check failed
        if '...... PASSED' not in raw:
            raise_parse_error(raw, "HPLinpack execution failed.")

        # Create a dictionary from lines containing one : character
        kernel_info = dict([tuple([ll.strip() for ll in line.split(':')])
                            for line in raw.splitlines()
                            if ':' in line and line.find(':') == line.rfind(':')])
        # Pull out important keys
        problem_size = kernel_info['N']
        blocks = kernel_info['NB']

        # Create output description
        result = 'HPLinpack problem size {0} block size {1}'
        return result.format(problem_size, blocks)


    def parse_perf(self, raw):
        """
        Parses the raw HPLinpack output and returns the performance as calculated
        by the workload.

        Expected lines in HPLinpack output:

        ================================================================================
        T/V                N    NB     P     Q               Time                 Gflops
        --------------------------------------------------------------------------------
        WC06C2C4       40000   336     1     1              35.40            1.20527e+03
        """

        lines = [ll.strip() for ll in raw.splitlines()]

        # search results header "T/V  N  NB ..." in hplinpack output
        line_num = 0
        is_results_header = re.compile(r'T/V\s+N\s+NB\s+P\s+Q\s+Time', re.IGNORECASE)
        header = None
        for line in lines:
            header = is_results_header.match(line)
            if header:
                break
            line_num = line_num + 1

        if not header:
            raise_parse_error(raw)

        # performance results are 2 lines below header in column 6
        speed = float(lines[line_num+2].split()[6])
        result = {}
        result[DEFAULT_SCORE_TAG] = {'value':speed, 'units':'GFlops', 'rollup':True}
        return result


    def param_file(self, param):
        """creates configuration file for hplinpack in temporary directory,
        returns absolute path to file"""
        problem_size = param.get_named('problem_size')
        block_size = param.get_named('block_size')

        config_file_content = HPLINPACK_CONFIG_FILE.format(problem_size=problem_size,
                                                           block_size=block_size)
        self._working_directory = tempfile.mkdtemp()
        config_file_path = os.path.join(self._working_directory, HPLINPACK_CONFIG_FILE_NAME)

        with open(config_file_path, 'w') as fid:
            fid.write(config_file_content)

        return config_file_path


    def independent_var(self, category):
        """returns independent variable for plots/tables (depends on the kernel
        parameters category)"""
        if category == 'scaling_core':
            return 'hpl_numthreads'
        return 'problem_size'


    def param_for_env(self):
        """returns list of parameters that should be set as environment variables"""
        return ['hpl_numthreads']

    def clean_up(self, local, remote, remote_shell=None):
        """overrides default clenup() to remove working directory, in addition
        to configuration files, remote binaries"""
        super(hplinpack, self).clean_up(local, remote, remote_shell)

        if self._working_directory and os.path.exists(self._working_directory):
            shutil.rmtree(self._working_directory)

    def get_working_directory(self):
        """returns HPCG working directory"""
        return self._working_directory


    def _update_params(self, current_params, offload):
        """When running SCIF offload HPL the host block size should be modified
        since the host CPU architecture is different from the KNL architecture.

        This method receives the list of default parameters and returns a new list
        with the parameters updated if the offload method is 'scif', parameters
        are unchanged for other supported offload methods."""
        if offload != 'scif':
            return current_params

        default_blocksize = '--block_size {0}'.format(MIC_BLOCKSIZE)
        new_blocksize = '--block_size {0}'.format(HOST_BLOCKSIZE)
        new_params = [re.sub(default_blocksize, new_blocksize, params)
                      for params in current_params]
        return new_params


    def param_defaults(self, offload=None):
        """Returns a copy of the dictionary of default parameter values.
        The dictionary keys are the parameter names, and the defaults
        are the correspinding values."""
        if offload == 'scif':
            param_defaults = self._paramDefaults.copy()
            param_defaults['block_size'] = str(HOST_BLOCKSIZE)
            return param_defaults

        # for other offload methods return default params
        return self._paramDefaults.copy()

    def _ordering_key(self, stat):
        return float(stat.perf[DEFAULT_SCORE_TAG]['value'])
