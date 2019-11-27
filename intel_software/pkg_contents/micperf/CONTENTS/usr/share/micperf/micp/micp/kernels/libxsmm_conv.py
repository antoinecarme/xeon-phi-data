#  Copyright 2012-2017, Intel Corporation, All Rights Reserved.
#
# This software is supplied under the terms of a license
# agreement or nondisclosure agreement with Intel Corp.
# and may not be copied or disclosed except in accordance
# with the terms of that agreement.

import os
import re

import micp.kernel as micp_kernel
import micp.info as micp_info
import micp.common as micp_common
import micp.params as micp_params

from micp.common import mp_print, get_ln, CAT_ERROR

confParamNames = [ 'iters', 'inpWidth', 'inpHeight', 'nImg', 'nIfm', \
                'nOfm', 'kw', 'kh', 'pad', 'stride']
optimalParamValues = '100 224 224 16 3 64 7 7 3 2'

# expected minimal number of parsed scores in output
CONST_expected_perf_scores = 6

class libxsmm_conv(micp_kernel.Kernel):
    def __init__(self):
        optimalParamsString = ''
        self._categoryParams = {}

        info = micp_info.Info()
        maxCount = info.num_cores()

        self.name = 'libxsmm_conv'
        self.param_validator = micp_params.NO_VALIDATOR
        self._paramNames = ['omp_num_threads']
        self._paramNames.extend(confParamNames)

        self._paramDefaults = {'omp_num_threads':str(maxCount)}

        for (idx, val) in enumerate(optimalParamValues.split(' ')):
            optimalParamsString += '--{0} {1} '.format(confParamNames[idx], val)
            self._paramDefaults[confParamNames[idx]] = val

        self._categoryParams['test'] = [ optimalParamsString ]
        self._categoryParams['optimal'] = [ optimalParamsString ]
        self._categoryParams['optimal_quick'] = self._categoryParams['optimal']
        self._categoryParams['scaling'] = self._categoryParams['optimal']
        self._categoryParams['scaling_quick'] = self._categoryParams['optimal']
        # scale with step 10
        coreConfig = range(1, maxCount, 10)
        self._categoryParams['scaling_core'] = \
            [ ' '.join(['--omp_num_threads {0}'.format(cc), optimalParamsString]) \
                for cc in coreConfig]

    def path_host_exec(self, offload_method):
        if offload_method == 'local':
            return self._path_exec(micp_kernel.LIBEXEC_HOST, "layer_example_f32")
        else:
            return None

    def _do_unit_test(self):
        return True

    def offload_methods(self):
        return ['local']

    def param_type(self):
        return 'pos'

    def independent_var(self, category):
        return 'omp_num_threads'

    def param_for_env(self):
        return ['omp_num_threads']

    def path_dev_exec(self, offType):
        """ Intel Xeon Phi Coprocessors is not supported """
        return None

    def environment_host(self):
        return {'LD_LIBRARY_PATH':self.ld_library_path(),
                'KMP_PLACE_THREADS':'1T',
                'KMP_AFFINITY':'compact,granularity=fine'}

    def get_process_modifiers(self):
        info = micp_info.Info()
        if info.is_processor_mcdram_available():
            return ['numactl', '--membind=1']
        else:
            return []

    def parse_desc(self, raw):
        # skip benchmark type information
        keyword = "PARAMS:"
        params_a_beg_index = raw.find(keyword)
        params_a_end_index = raw.find("\n", params_a_beg_index)

        if params_a_beg_index == -1 or params_a_end_index == -1:
            micp_kernel.raise_parse_error(raw)

        extract = '{0}'.format(
            raw[params_a_beg_index+len(keyword) : params_a_end_index])

        # draw similar description as in case of mkl convolution
        kparams = dict([param.split(":") for param in extract.split()])
        desc = ['W', 'H', 'C', 'N', 'K', 'R', 'S']
        desc = [(param_name + "=" + kparams[param_name]) for param_name in desc]

        return ' '.join(desc)

    def parse_perf(self, raw):
        res_lines = raw.splitlines()
        result = {}

        bench_direction = None
        bench_storage_type = None
        bench_result = None

        for line in res_lines:
            if "Performance" in line:
                if bench_direction or bench_storage_type:
                    micp_kernel.raise_parse_error(raw)
                if "FWD" in line:
                    bench_direction = "FWD"
                elif "BWD" in line:
                    bench_direction = "BWD"
                elif "UPD" in line:
                    bench_direction = "UPD"
                else:
                    micp_kernel.raise_parse_error(raw)

                bracket_start = line.find('(') + 1;
                bracket_end = line.find(")", bracket_start)
                if bracket_start == -1 or bracket_end == -1:
                    micp_kernel.raise_parse_error(raw)
                bench_storage_type = line[bracket_start : bracket_end]
            elif "GFLOPS" in line:
                if not bench_direction or not bench_storage_type:
                    micp_kernel.raise_parse_error(raw)
                for s in line.split():
                    try:
                        bench_result = float(s)
                        break
                    except:
                        pass

                result['Computation.Avg.{0}.{1}'.format(bench_storage_type, bench_direction)] = \
                    {'value':bench_result, 'units':'GFlops', 'rollup':True}

                bench_direction = None
                bench_storage_type = None

        if len(result) < CONST_expected_perf_scores:
            micp_kernel.raise_parse_error(raw)

        return result
