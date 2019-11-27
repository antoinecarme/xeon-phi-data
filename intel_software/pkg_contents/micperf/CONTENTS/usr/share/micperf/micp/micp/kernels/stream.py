#  Copyright 2012-2017, Intel Corporation, All Rights Reserved.
#
# This software is supplied under the terms of a license
# agreement or nondisclosure agreement with Intel Corp.
# and may not be copied or disclosed except in accordance
# with the terms of that agreement.
#
#  Author:  Christopher M. Cantalupo

import os
import re

import micp.kernel as micp_kernel
import micp.info as micp_info
import micp.common as micp_common
import micp.params as micp_params

DEFAULT_SCORE_TAG = 'Task.Bandwidth'

class stream(micp_kernel.Kernel):
    def __init__(self):
        self.name = 'stream'
        self.param_validator = micp_params.STREAM_VALIDATOR
        self._paramNames = ['omp_num_threads']
        self._paramDefaults = {'omp_num_threads':'57'}

        self._categoryParams = {}

        self._categoryParams['test'] = [' ']

        if micp_info.Info().is_in_sub_numa_cluster_mode():
            maxCount = micp_info.Info().snc_max_threads_per_quadrant()
        else:
            maxCount = micp_info.Info().num_cores()

        coreConfig = range(1,maxCount+1)
        self._categoryParams['scaling'] = \
            ['--omp_num_threads {0}'.format(cc) for cc in coreConfig]

        optimalThreads = maxCount
        self._categoryParams['optimal'] = self._categoryParams['scaling'][-10:]
        self._categoryParams['optimal_quick'] = ['--omp_num_threads {0}'.format(optimalThreads)]
        self._categoryParams['scaling_quick'] = list(self._categoryParams['scaling'])
        self._categoryParams['scaling_core'] = list(self._categoryParams['scaling'])
        self._set_defaults_to_optimal()

    def path_aux_data(self, offType):
        result = []
        if offType == 'native':
            result.append(self.mic_library_find('libiomp5.so'))
        return result

    def path_dev_exec(self, offType):
        if offType == 'native':
            execName = 'stream_mic'
            return self._path_exec(micp_kernel.LIBEXEC_DEV, execName)
        return None

    def path_host_exec(self, offload_method):
        """return the full path to the micperf's stream binary"""
        if offload_method != 'local':
            return None

        if micp_info.Info().is_in_sub_numa_cluster_mode():
            exec_name = 'stream_mpi'
        else:
            exec_name = 'stream'

        if micp_common.is_platform_windows() and micp_common.is_selfboot_platform():
            exec_name = '{0}.exe'.format(exec_name)

        return self._path_exec(micp_kernel.LIBEXEC_HOST, exec_name)

    def _do_unit_test(self):
        return True

    def offload_methods(self):
        return ['native', 'local']

    def param_type(self):
        return 'value'

    def independent_var(self, category):
        return 'omp_num_threads'

    def param_for_env(self):
        return ['omp_num_threads']

    def environment_dev(self):
        return {'LD_LIBRARY_PATH':'/tmp',
                'KMP_AFFINITY':'scatter'}

    def environment_host(self):
        return {'LD_LIBRARY_PATH':self.ld_library_path(),
                'KMP_AFFINITY':'scatter'}

    def is_optimized_for_snc_mode(self):
        return True

    def get_process_modifiers(self):
        info = micp_info.Info()
        modifiers = []

        if info.is_in_sub_numa_cluster_mode():
            subclusters_count = info.get_number_of_nodes_with_cpus()
            modifiers += ['mpirun', '-n', str(subclusters_count)]
        if info.is_processor_mcdram_available():
            hbw_nodes = info.get_hbw_nodes()
            modifiers += ['numactl', '--membind={}'.format(hbw_nodes)]

        return modifiers

    def is_mpi_required(self):
        return micp_info.Info().is_in_sub_numa_cluster_mode()

    def parse_desc(self, raw):
        lines = raw.splitlines()
        # Check validation
        failRE = re.compile('fail', re.IGNORECASE)
        if failRE.search(raw):
            eMessage = [line for line in lines
                        if failRE.search(line) or
                        line.strip().startswith("Expected") or
                        line.strip().startswith("Observed")]
            eMessage.insert(0, '')
            eMessage = '\n'.join(eMessage)
            raise micp_kernel.SelfCheckError(eMessage)
        # Get stream version information
        name = [line.strip() for line in lines
                if line.startswith('STREAM version')][0]
        # Get the number of threads
        for line in lines:
            if line.startswith('Number of Threads requested'):
                for word in line.split():
                    try:
                        numThreads = int(word)
                        break
                    except ValueError:
                        continue

        result = '{0} with {1} threads'.format(name, numThreads)

        return result

    def parse_perf(self, raw):
        rate = float([line.split()[1] for line in raw.splitlines() if line.startswith('Triad: ')][-1])
        rate = str(rate/1000) # MB/s -> GB/s
        result = {}
        result[DEFAULT_SCORE_TAG] = {'value':rate, 'units':'GB/s', 'rollup':True}
        return result

    def _ordering_key(self, stat):
        return float(stat.perf[DEFAULT_SCORE_TAG]['value'])
