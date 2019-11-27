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

class dgemm(micp_xgemm.xgemm):
    def __init__(self):
        super(dgemm, self).__init__()
        self.name = 'dgemm'

        self._categoryParams = {}
        self._categoryParams['test'] = [' ']

        maxMatrixSize = int(math.sqrt(self.maxMemory/8.0/3.0))
        if maxMatrixSize > 10240:
            maxMatrixSize = 10240

        maxStep = maxMatrixSize/512
        maxMatrixSize = maxStep*512
        matrixConfig = [512*ii for ii in range(1, maxStep+1)]

        # scaling - K=N=M=matrixSize where matrixSize is variable dependent
        # on amount of available memory
        self._categoryParams['scaling'] = [self.args.format(
            0, *([matrixSize] * 3)) for matrixSize in matrixConfig]

        # scaling_quick - same as scaling but limited to ten first
        # measurements
        self._categoryParams['scaling_quick'] = [self.args.format(
            0, *([matrixSize] * 3)) for matrixSize in matrixConfig[:8]]

        if maxMatrixSize < 7680:
            # optimal - num_thread=max K=N=M=maxMatrixSize
            self._categoryParams['optimal'] = \
                [self.args.format(0, *([maxMatrixSize] * 3))]
        elif self.maxCount == 52:
            # optimal - num_thread=max K=N=M=6656
            self._categoryParams['optimal'] = \
                [self.args.format(0, *([6656] * 3))]
        else:
            # optimal - num_thread=max K=N=M=7860
            self._categoryParams['optimal'] = \
                [self.args.format(0, *([7680] * 3))]

        # optimal_quick - num_thread=max K=N=M=4096
        self._categoryParams['optimal_quick'] = \
            [self.args.format(0, *([4096] * 3))]

        # scaling_core - K=N=M=8192, num_thread defined by coreConfig
        self._categoryParams['scaling_core'] = [self.args.format(coreCount,
            *([8192] *3)) for coreCount in self.coreConfig]

        self._set_defaults_to_optimal()

    def parse_desc(self, raw):
        return super(dgemm, self).parse_desc(raw, "DGEMM")
