#  Copyright 2012-2017, Intel Corporation, All Rights Reserved.
#
# This software is supplied under the terms of a license
# agreement or nondisclosure agreement with Intel Corp.
# and may not be copied or disclosed except in accordance
# with the terms of that agreement.
#
#  Author:  Christopher M. Cantalupo
"""
Module containing the function that is called by micprun.  micprun
serves as an executable wrapper to this function.
"""


import os
import copy
import cPickle
import sys
import subprocess
import datetime

import common as micp_common
import kernel as micp_kernel
import offload as micp_offload
import params as micp_params
import stats as micp_stats
import info as micp_info
import connect as micp_connect

from micp.common import mp_print, CAT_INFO, CAT_WARN, CAT_OFFLOAD
from distutils import spawn

CONST_ROOT_ACCESS_ALLOWED = \
"""Some kernels ({}) will be run in elevated mode."""

CONST_NO_SUDO = \
"""Some kernels ({}) require to be run in elevated mode.
Please install 'sudo' and add '--sudo' to application arguments."""

CONST_ROOT_ACCESS_DENIED = \
"""Some kernels ({}) require to be run in elevated mode.
To allow that please add '--sudo' to application
arguments."""

CONST_SKIPPED_EXEC = \
"""Execution of the '{}' kernel will be skipped."""

def run(kernelNames='all', offMethod='native:scif', paramCat='optimal',
        kernelArgs='', devIdx='0', verbLevel='0', outDir='', tag='',
        compResult='', margin='', kernelPlugin='', statistical_model={},
        sudo=False, logFileName=None):
    """
    Core function that is used by the micprun executable. Specifying
    an existing outDir causes run to store a pkl file in outDir. The
    file is named according to system information and run parameters.
    """
    runArgs = locals()

    if compResult:
        if type(compResult) == str:
            compResult = cPickle.load(open(compResult, 'rb'))
            # Note we expect that the user would have already
            # overridden these parameters if they pass the
            # compResult as an object rather than a path.
            kernelNames = runArgs['kernelNames'] = compResult.runArgs['kernelNames']
            offMethod = runArgs['offMethod'] = compResult.runArgs['offMethod']
            paramCat = runArgs['paramCat'] = compResult.runArgs['paramCat']
            kernelArgs = runArgs['kernelArgs'] = compResult.runArgs['kernelArgs']
            devIdx = runArgs['devIdx'] = compResult.runArgs['devIdx']

    device = devIdx
    mpssConnect = micp_connect.MPSSConnect(device)
    devIdx = mpssConnect.get_offload_index()
    verbLevel = int(verbLevel)

    info = micp_info.Info()
    info.set_device_index(devIdx)

    kernelFactory = micp_kernel.KernelFactory()
    if kernelPlugin:
        kernelFactory.register_pkg(kernelPlugin)

    if kernelNames == 'help':
        kernelNames = kernelFactory.class_names()
        kernelNames.insert(0, 'Available kernels:')
        print '\n    '.join(kernelNames)
        return

    if kernelNames == 'all':
        kernelNames = kernelFactory.class_names()
    else:
        kernelNames = kernelNames.split(':')

    kernelList = [kernelFactory.create(kn) for kn in kernelNames]

    # check if sudo kernels can be executed
    if os.getuid() != 0:
        sudoKernelList = [k for k in kernelList if k.requires_root_access()]
        if sudoKernelList:
            sudoKernelNames = ", ".join([k.name for k in sudoKernelList])
            sudoPath = spawn.find_executable("sudo")
            skipSudoKernels = True

            if not sudoPath:
                mp_print(CONST_NO_SUDO.format(sudoKernelNames),
                    CAT_WARN)
                kernelList = [k for k in kernelList if k not in sudoKernelList]
            elif not sudo:
                mp_print(CONST_ROOT_ACCESS_DENIED.format(sudoKernelNames),
                    CAT_WARN)
                kernelList = [k for k in kernelList if k not in sudoKernelList]
            else:
                mp_print(CONST_ROOT_ACCESS_ALLOWED.format(sudoKernelNames),
                    CAT_INFO)
                skipSudoKernels = False

            if skipSudoKernels:
                for sudoKernel in sudoKernelList:
                    mp_print(CONST_SKIPPED_EXEC.format(sudoKernel.name), CAT_WARN)

    if not kernelList:
        return micp_common.E_NO_ERROR

    xNameList = [kk.independent_var(paramCat) for kk in kernelList]

    offloadFactory = micp_offload.OffloadFactory()
    if offMethod == 'all':
        offloadNames = offloadFactory.class_names()
    else:
        offloadNames = offMethod.split(':')
    offloadList = [offloadFactory.create(on) for on in offloadNames]

    if paramCat and kernelArgs:
        sys.stderr.write('WARNING: paramCat and and kernel arguments both specified.\n')
        sys.stderr.write('         Kernel arguments are ignored\n')
        kernelArgs = ''

    if kernelArgs and type(kernelArgs) is not list:
        kernelArgs = [kernelArgs]

    errorString = 'WARNING: {0} kernel does not implement parameter categories'
    result = micp_stats.StatsCollection(runArgs, tag, info)
    if outDir:
        if result.tag:
            fileName = os.path.join(outDir, 'micp_run_stats_{0}.pkl'.format(result.tag))
        else:
            fileName = os.path.join(outDir, 'micp_run_stats.pkl')
    else:
        fileName = None

    exit_code = micp_common.E_NO_ERROR

    kernelStdOut = None
    if logFileName:
        try:
            kernelStdOut = open(logFileName, 'w')
        except:
            # ignore, kernels will be print to standard output
            pass

    try:
        for offload in offloadList:
            for (kernel, xName) in zip(kernelList, xNameList):
                if paramCat:
                    try:
                        kernelArgs = kernel.category_params(paramCat, offload.name)
                    except NotImplementedError:
                        sys.stderr.write(errorString.format(kernel.name) + '\n')
                        continue
                try:
                    paramNames = kernel.param_names(full=True)
                    defaults = kernel.param_defaults(offload.name)
                    paramForEnv = kernel.param_for_env()
                    if kernel.param_type() == 'getopt':
                        options = kernel.options()
                        long_options = kernel.long_options()
                        kernelParams = [micp_params.ParamsGetopt(ka, paramNames, options,
                                                                 long_options, defaults)
                                        for ka in kernelArgs]
                    else:
                        param_validator = getattr(kernel, 'param_validator', micp_params.NO_VALIDATOR)
                        kernelParams = [micp_params.Params(ka, paramNames, defaults, paramForEnv, param_validator)
                                        for ka in kernelArgs]
                except NotImplementedError:
                    kernelParams = [micp_params.ParamsPos(ka)
                                    for ka in kernelArgs]
                except micp_params.MicpParamsHelpError as err:
                    if offload.name in kernel.offload_methods():
                        print kernel.help(err.__str__(), offload.name)
                    continue
                try:
                    runResult = offload.run(kernel, device, kernelParams,
                        kernelStdOut=kernelStdOut)
                except (Exception, KeyboardInterrupt) as err:
                    if 'partialResult' in dir(err):
                        result.append(kernel.name, offload.name, xName, err.partialResult)
                    if fileName:
                        fid = open(fileName, 'wb')
                        cPickle.dump(result, fid)
                        fid.close()
                    raise
                result.append(kernel.name, offload.name, xName, runResult)
    finally:
        # check since the file might not have been opened
        if kernelStdOut:
            kernelStdOut.close()

    if fileName:
        fid = open(fileName, 'wb')
        cPickle.dump(result, fid)
        fid.close()

    if compResult:
        combined = copy.deepcopy(result)
        combined.extend(compResult)
    else:
        combined = result

    if verbLevel >= 1:
        print combined
        if outDir:
            combined.csv_write(outDir)

    if verbLevel >= 2:
        if outDir:
            fileName = fileName[:-4] + '_all.csv'
            fid = open(fileName, 'w')
            fid.write(combined.csv(False))
            fid.close()
        try:
            combined.plot(outDir)
        except NameError:
            pass

    # if we only have results for a single kernel the "all kernels" plot is equal
    # to the plot created above for verbosity == 2, if that the case skip
    if verbLevel >= 3 and not combined.includes_results_for_single_kernel():
        try:
            combined.plot_all(outDir)
        except NameError:
            pass

    if compResult and margin:
        result.perf_regression_test(float(margin), compResult, statistical_model)

    return exit_code
