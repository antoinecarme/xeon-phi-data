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

import micp.kernel as micp_kernel
import micp.kernels._xgemm as micp_xgemm
import micp.info as micp_info
import micp.common as micp_common
import micp.params as micp_params


class sgemm(micp_xgemm.xgemm):
    def __init__(self):
        super(sgemm, self).__init__()
        self.name = 'sgemm'

        self._categoryParams = {}
        self._categoryParams['test'] = [' ']

        # to get KNM peak performance large matrices have to be used which
        # makes little sense for other platforms because it causes long runtimes
        if micp_info.Info().get_processor_codename() == micp_info.INTEL_KNM:
            defMN = 50000
            defK = 4320
            # for SNCx modes size has to be reduced not to exceed memory amount
            if micp_info.Info().is_in_sub_numa_cluster_mode():
                subclusters = micp_info.Info().get_number_of_nodes_with_cpus()
                if subclusters == 2:
                    defMN = 34000
                elif subclusters == 4:
                    defMN = 23000

            self._categoryParams['optimal'] = \
                [self.args.format(0, defMN, defMN, defK)]
            # optimal_quick - same as optimal
            self._categoryParams['optimal_quick'] = \
                self._categoryParams['optimal']
            # scaling core - same as optimal but num_thread defined by coreConfig
            self._categoryParams['scaling_core'] = \
                [self.args.format(coreCount, defMN, defMN, defK) for coreCount
                    in self.coreConfig]
            # scaling - num_thread=max M, N same as optimal but K=[540,1080,2160,4320]
            self._categoryParams['scaling'] = \
                [self.args.format(0, defMN, defMN, k*540) for k
                    in [1,2,4,8]]
            # scaling_quick - same as scaling
            self._categoryParams['scaling_quick'] = \
                self._categoryParams['scaling']
        else:
            maxMatrixSize = int(math.sqrt(self.maxMemory/4.0/3.0))
            if maxMatrixSize > 16384:
                maxMatrixSize = 16384

            maxStep = maxMatrixSize/512
            maxMatrixSize = maxStep*512
            matrixConfig = [512*ii for ii in range(1, maxStep+1)]

            # optimal
            if maxMatrixSize < 15872:
                # optimal - num_thread=max K=N=M=maxMatrixSize
                self._categoryParams['optimal'] = \
                    [self.args.format(0, *([maxMatrixSize] * 3))]
            elif self.maxCount == 52:
                # optimal - num_thread=max K=N=M=13312
                self._categoryParams['optimal'] = \
                    [self.args.format(0, *([13312] * 3))]
            else:
                # optimal - num_thread=max K=N=M=15872
                self._categoryParams['optimal'] = \
                    [self.args.format(0, *([15872] * 3))]
            # optimal - num_thread=max K=N=M=5120
            self._categoryParams['optimal_quick'] = \
                    [self.args.format(0, *([5120] * 3))]
            # scaling_core - K=N=M=8192, num_thread defined by coreConfig
            self._categoryParams['scaling_core'] = [self.args.format(
                coreCount, *([8192] * 3)) for coreCount in self.coreConfig]
            # scaling - K=N=M=matrixSize where matrixSize is variable dependent
            # on amount of available memory
            self._categoryParams['scaling'] = [self.args.format(
                0, *([matrixSize] * 3)) for matrixSize in matrixConfig]
            # scaling_quick - same as scaling but limited to ten first
            # measurements
            self._categoryParams['scaling_quick'] = [self.args.format(
                0, *([matrixSize] * 3)) for matrixSize in matrixConfig[:10]]

    def environment_host(self):
        auxEnvs = None
        if micp_info.Info().get_processor_codename() == micp_info.INTEL_KNM:
            auxEnvs = {'MKL_ENABLE_INSTRUCTIONS':'AVX512_MIC_E1'}
        return super(sgemm, self).environment_host(auxEnvs)

    def parse_desc(self, raw):
        return super(sgemm, self).parse_desc(raw, "SGEMM")
