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

confParamNames = [ 'groups', 'nImg', 'inpWidth', 'inpHeight', 'nIfm', \
                'nOfm', 'kw', 'kh', 'stride', 'pad', 'iters' ]
optimalParamValues = '1 16 224 224 3 64 7 7 2 3 100'

# expected minimal number of parsed scores in output
CONST_expected_perf_scores = 3
# expected number of "|"-separated sections in output
CONST_expected_sections = 2
# expected measurements per row
CONST_expected_meas_per_row = 4

class mkl_conv(micp_kernel.Kernel):
    def __init__(self):
        optimalParamsString = ''
        self._categoryParams = {}

        info = micp_info.Info()
        maxCount = info.num_cores()

        self.name = 'mkl_conv'
        self.param_validator = micp_params.NO_VALIDATOR
        # for ease of use, split params into two lists
        self._paramNames = ['omp_num_threads', 'with_padding', 'output']
        self._paramNames.extend(confParamNames)

        self._paramDefaults = {'omp_num_threads':str(maxCount),
            'with_padding':'0',
            'output':'--original-output'}

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
            return self._path_exec(micp_kernel.LIBEXEC_HOST, "std_conv_bench")
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
        res_line = raw.splitlines()
        # get general parameters before '|' character
        try:
            out_sections = res_line[1].rsplit("|", 1)
        except IndexError:
            micp_kernel.raise_parse_error(raw)

        if len(out_sections) != CONST_expected_sections:
            micp_kernel.raise_parse_error(raw)
        return out_sections[0].strip()

    def parse_perf(self, raw):
        res_lines = raw.splitlines()
        result = {}
        for line in res_lines:
            # example one line of output:
            # FWD w/ padding in flops min(ms) 0.01; max(gflop/s) 2.70;avg(ms) 0.02; avg(gflop/s) 1.58;
            # ex.                    ( FWD )
            propagation = re.search('([F|B]WD[A-Z_]*)', line)
            # ex.                (avg      )  ((gflops/s))     (1.58          )
            values = re.findall('([a-zA-Z]*)\(([a-zA-Z/]*)\)\s*([0-9]*\.[0-9]*)', line)

            # skip text data lines
            if not (propagation and values):
                continue

            # check syntax (4 measurements per row)
            if len(values) != CONST_expected_meas_per_row:
                micp_kernel.raise_parse_error(raw)

            propag_txt = propagation.group(0)
            for (prop, unit, value) in values:
                if prop != 'avg':
                    continue
                if unit == 'gflop/s':
                    result['Computation.Avg.{0}'.format(propag_txt)] = {'value':value, 'units':'GFlops', 'rollup':True}

        if len(result) != CONST_expected_perf_scores:
            micp_kernel.raise_parse_error(raw)
        return result
