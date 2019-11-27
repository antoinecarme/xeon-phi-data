#  Copyright 2012-2017, Intel Corporation, All Rights Reserved.
#
# This software is supplied under the terms of a license
# agreement or nondisclosure agreement with Intel Corp.
# and may not be copied or disclosed except in accordance
# with the terms of that agreement.
#
#  Author:  Christopher M. Cantalupo

import os
import math
import itertools

import micp.kernel as micp_kernel
import micp.info as micp_info
import micp.common as micp_common
import micp.params as micp_params

from micp.kernel import raise_parse_error

DEFAULT_SCORE_TAG = 'Computation.Avg'

class xgemm(micp_kernel.Kernel):
    def __init__(self):
        info = micp_info.Info()
        self.param_validator = micp_params.XGEMM_VALIDATOR

        self._paramDefaults = {'i_num_rep':'3',
                               'n_num_thread':'228',
                               'm_mode':'NN',
                               'M_size':'-1',
                               'N_size':'-1',
                               'K_size':'-1'}

        self._paramNames = self._paramDefaults.keys()
        self.args = '--n_num_thread {0} --M_size {1} --N_size {2} --K_size {3}'
        self.maxMemory = info.mic_memory_size() - 1024**3

        # define maximal number of cores per MPI rank
        if info.is_in_sub_numa_cluster_mode():
            self.maxCount = info.snc_max_threads_per_quadrant()
        else:
            self.maxCount = info.num_cores()

        # define coreConfig - set of requested numbers of spawned threads
        # for scaling_core category. The set of values is chosen arbitrarily
        # so to satisfy reasonable coverage of range up to number of processor
        # cores.
        step = int(round(self.maxCount/10.0))
        if step < 4:
            step = 4
        self.coreConfig = range(step, self.maxCount, step)
        self.coreConfig.append(self.maxCount)

        self.units = 'GFlops'

    def _do_unit_test(self):
        return False

    def offload_methods(self):
        return['native', 'pragma', 'auto', 'local']

    def path_host_exec(self, offType):
        bench_name = self.name
        if offType == 'pragma':
            if micp_common.is_platform_windows():
                return self._path_exec(micp_kernel.LIBEXEC_HOST, bench_name + '_ofl.exe')
            else:
                return self._path_exec(micp_kernel.LIBEXEC_HOST, bench_name +'_ofl.x')

        if offType == 'auto' or offType == 'local':
            # binary name
            if micp_info.Info().is_processor_mcdram_available():
                xgemm_binary = bench_name + '_mcdram_cpu'
            else:
                xgemm_binary = bench_name + '_cpu'

            # in SNC mode use a different MPI based binary regardless of the
            # kind of memory to be used
            if micp_info.Info().is_in_sub_numa_cluster_mode():
                xgemm_binary = bench_name + '_mpi_snc_cpu'

            # extension
            if micp_common.is_platform_windows():
                xgemm_binary = '{0}.exe'.format(xgemm_binary)
            else:
                xgemm_binary = '{0}.x'.format(xgemm_binary)
            return self._path_exec(micp_kernel.LIBEXEC_HOST, xgemm_binary)

        return None

    def path_dev_exec(self, offType):
        bench_name = self.name
        if offType == 'native':
            return self._path_exec(micp_kernel.LIBEXEC_DEV, bench_name + '_mic.x')
        return None

    def path_aux_data(self, offType):
        result = []
        if offType == 'native':
            result.append(self.mic_library_find('libiomp5.so'))
        return result

    def param_type(self):
        return 'flag'

    def parse_desc(self, raw, prototype = 'XGEMM'):
        # parse the output and put parameters of run into dd dictionary
        # where keys represent the parameter name and dictionary value the
        # parameter value
        dd = dict([tuple([ll.strip() for ll in line.split(':')])
                   for line in raw.splitlines()
                   if ':' in line and line.find(':') == line.rfind(':')])

        try:
            M = dd['fixed M']
            N = dd['fixed N']
            K = dd['fixed K']
            # for mpirun driven run xgemm has different output thus 'if'
            # statement
            if 'threads used' in dd:
                # code below is for standard execution
                numThreads = dd['threads used']
            else:
                # code below for mpirun exection;
                # for mpirun execution dgemm will print 'MPI rank <rank_number>'
                # parameter for each requested rank, below code counts those and
                # parses the number of spawned threads for each rank
                numThreads_t = []
                key_t = 'MPI rank {}'
                for i in itertools.count():
                    key = key_t.format(i)
                    if key not in dd:
                        break
                    else:
                        numThreads_t.append(dd[key] + " [" + key + "]")
                numThreads = '/'.join(numThreads_t)

            numIt = dd['min_niters']
        except (IndexError, KeyError) as e:
            raise_parse_error(raw, "Key error: " + str(e))

        result = '(M={}, N={}, K={}) MKL {} with {} threads and {} iterations'.format(M, N, K, prototype, numThreads, numIt)
        return result

    def parse_perf(self, raw):
        """Parse xGEMM's raw output and extract performance results, expected
        line format (in SNC modes we also expect an avg for each NUMA node):
                    xGEMM output...

                       n        min        avg        max     stddev
             *     10240     286.64     290.43     296.65  3.815e+00

                   additional output...

        return results in dictionary as required by the micp/kernel.py interface.
        """
        line = [float(line.split()[3]) for line in raw.splitlines() if line.startswith('*')]
        speed = str(sum(line))

        dd = dict([tuple([ll.strip() for ll in line.split(':')])
                   for line in raw.splitlines()
                   if ':' in line and line.find(':') == line.rfind(':')])
        try:
            if dd['timer'] == 'native':
                self.tag = 'Task.Computation.Avg'
            elif dd['timer'] == 'invoke':
                self.tag = 'Device.Computation.Avg'
            elif dd['timer'] == 'full':
                self.tag = 'Host.Computation.Avg'
        except KeyError:
            self.tag = DEFAULT_SCORE_TAG
        result = {}
        result[self.tag] = {'value': speed, 'units': self.units, 'rollup': True}
        return result

    def environment_dev(self):
        return {'LD_LIBRARY_PATH':'/tmp'}

    def environment_host(self, auxHostVars = None):
        """returns extra enviroment variables needed to run xgemm on the host"""

        info = micp_info.Info()
        numThreads = info.num_cores() - 1
        maxMemory = str(int((info.mic_memory_size() - 1024**3)/(1024**3)))
        retvars = {'LD_LIBRARY_PATH':self.ld_library_path()}
        mic_sb = {'KMP_AFFINITY':'compact,1,0',
                  'LD_LIBRARY_PATH':self.ld_library_path(),
                  'USE_2MB_BUFFERS':'16K'}

        if auxHostVars:
            mic_sb.update(auxHostVars)
            retvars.update(auxHostVars)

        # additional variables for Windows running on Xeon Phi processors
        if micp_common.is_platform_windows() and micp_common.is_selfboot_platform():
            mic_sb['OMP_NUM_THREADS'] = str(info.num_cores())
            mic_sb['MKL_DYNAMIC'] = 'false'
            mic_sb['KMP_BLOCKTIME'] = 'infinite'
            mic_sb['KMP_LIBRARY'] = 'turnaround'

        # MKL_FAST_MEMORY_LIMIT forces MKL to store buffers in DDR memory
        if not micp_info.Info().is_processor_mcdram_available():
            retvars['MKL_FAST_MEMORY_LIMIT'] = '0'

        if micp_info.Info().is_in_sub_numa_cluster_mode():
            cores = micp_info.Info().snc_max_threads_per_quadrant()
            retvars['KMP_HW_SUBSET'] = '{0}c,1t'.format(cores)

        if micp_common.is_selfboot_platform():
            retvars.update(mic_sb)

        return retvars

    def independent_var(self, category):
        if category == 'scaling_core':
            return 'n_num_thread'
        return 'K_size'

    def get_process_modifiers(self):
        """returns the MPI command line (as a list) to run mpi_stream in
        the SNC modes, for the other cluster modes returns an empty list"""
        if micp_info.Info().is_in_sub_numa_cluster_mode():
            subclusters = micp_info.Info().get_number_of_nodes_with_cpus()
            return ['mpirun', '-n', str(subclusters)]
        else:
            return []

    def is_mpi_required(self):
        """MPI is required to run xGEMM when system is in the SCN2 or SNC4 mode"""
        return micp_info.Info().is_in_sub_numa_cluster_mode()


    def is_optimized_for_snc_mode(self):
        """micperf provides an optimized version for SNC modes"""
        return True

    def _ordering_key(self, stat):
        try:
            tag = self.tag
        except:
            tag = DEFAULT_SCORE_TAG
        return float(stat.perf[tag]['value'])
