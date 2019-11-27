#  Copyright 2012-2017, Intel Corporation, All Rights Reserved.
#
# This software is supplied under the terms of a license
# agreement or nondisclosure agreement with Intel Corp.
# and may not be copied or disclosed except in accordance
# with the terms of that agreement.
#
#  Author:  Christopher M. Cantalupo


import os
import copy
import sys
import shutil
import socket
from math import copysign

import params as micp_params
import common as micp_common
import stats as micp_stats
import kernel as micp_kernel
import connect as micp_connect
import info as micp_info

from micp.common import mp_print, CAT_ERROR, CAT_WARN, CAT_ENV, CAT_CMD

CONST_EXECUTABLE_NOT_FOUND = 'Executable for kernel {} and offload {} does not exist, skipping'

CONST_NOT_SUPPORTED_KERNEL = 'Micperf kernel "{}" does not support the "{}" offload method, skipping.'

class Offload(object):

    _CARD_EXECUTION_DIR = '/tmp/'

    def __init__(self):
        raise NotImplementedError('Abstract base class')

    @staticmethod
    def _is_name_resolution_error(error_message):
        """returns true if 'name resolution' error string is the given error
        message"""
        return 'Temporary failure in name resolution' in error_message

    @staticmethod
    def _run_workload(connect_object_type, args, env, cwd, device):
        """receives a connect_object_type and the arguments to instantiate it
        (args, env), when the object is created the workload (args) is executed,
        This wrapper catches the permission denied errors (no execution permission)
        and report them back to the caller. It also receives a 'device' string
        to be used in the error message (if any)"""
        try:
            return connect_object_type(args, env=env, cwd=cwd)
        except OSError as err:
            if err.strerror == 'Permission denied':
                message = ('Unable to execute "{0}" on the {1}, please make'
                           ' sure it has the right execution permissions')
                raise micp_common.NoExecutionPermission(message.format(args[0], device))
            else:
                raise

    @staticmethod
    def _validate_mpi_requirements(kernel):
        """raises an exception if MPI requirements for current kernel are not met"""
        if kernel.is_mpi_required() and not micp_common.is_mpi_available():
            raise micp_common.MissingDependenciesError(micp_common.DEP_MPI)

    def run(self, kernel, device, paramList, devParamList=None, kernelStdOut=None):
        """Run a kernel multiple times: once for each parameter listed.

        Args:
           kernel (micp.Kernel):  An instance to be executed.

           device:  Name of device targeted for offload.

           paramList (list of micp.Params):  A list of paramters, one
           for each kernel execution.

           kernelStdOut: object to be sink for kernel output

        Kwargs:
           devParamList (list of micp.Params):  If specified gives a
           distinct parameter list to be used for the device side
           executable.

        Returns:
            list of micp.Stats: Data collected by parsing standard
            output of the kernel.

        Raises:
            micp.kernel.NoExecutableError: Could not find executable

            NameError: Mic device name parameter unrecognized or
            kernel.parameter_type() returns unknown paramter type.

            micp.connect.CalledProcessError: Kernel executable returns
            an error code other than 127.

            micp_common.MissingDependenciesError: Some libararies or tools
            have not been installed.
        """
        result = []
        filesToCopy = None
        filesToRemove = []
        devParamFile = []
        hostParamFile = []

        MPI_NAME_RESOLUTION_ERROR = ('\n\n    ERROR: MPI was unable to connect to {0} (localhost) to run HPCG,\n'
                                     '        please make sure the name \'{0}\' can be resolved e.g. \"ping {0}\" succeeds.\n'
                                     '        On Linux make sure /etc/hosts contains the following line:\n'
                                     '        127.0.0.1    {0}\n\n').format(socket.gethostname())
        connect = micp_connect.MPSSConnect(device)
        localConnect = micp_connect.MPSSConnect('localhost')

        self._validate_mpi_requirements(kernel)
        try:
            if self._runHost:
                execPath = kernel.path_host_exec(self.name)
            else:
                execPath = kernel.path_dev_exec(self.name)
        except micp_kernel.NoExecutableError as internalErr:
            if str(internalErr):
                mp_print(str(internalErr), CAT_WARN)
            mp_print(CONST_EXECUTABLE_NOT_FOUND.format(kernel.name, self.name),
                CAT_WARN)
            if kernel.name in ('linpack', 'hplinpack', 'hpcg'):
                raise micp_common.MissingDependenciesError(
                    micp_common.DEP_LINPACK)
            return []

        if execPath is None or not os.path.exists(execPath):
            msg = CONST_NOT_SUPPORTED_KERNEL.format(kernel.name, self.name)
            mp_print(msg, CAT_WARN)
            return []

        if devParamList is None:
            devParamList = list(paramList)

        # set the device index parameter for non-native and non-local kernels
        if self.name != 'native' and self.name != 'local':
            devIdx = connect.get_offload_index()
            devParName = kernel.device_param_name()
            for pList in (paramList, devParamList):
                for param in pList:
                    try:
                        paramDevIdx = param.get_named(devParName)
                        if paramDevIdx != str(devIdx):
                            sys.stderr.write('WARNING:  kernel parameter "{0}" set to {1} overriding with value {2}\n'.format(devParName, paramDevIdx, devIdx))
                            param.set_named(devParName, str(devIdx))
                    except NameError:
                        if devIdx != 0:
                            raise
                        else:
                            pass

        try:
            if self._runDev:
                filesToCopy = [execPath]
                filesToCopy.extend(kernel.path_aux_data(self.name))
                filesToRemove = [self._CARD_EXECUTION_DIR + os.path.basename(ff)
                                 for ff in filesToCopy
                                 if os.path.basename(ff)]
                connect.copyto(filesToCopy, self._CARD_EXECUTION_DIR)

            for (hostParam, devParam) in zip(paramList, devParamList):
                print ''
                print micp_common.star_border('RUN')
                print 'Running {0} {1}'.format(kernel.name, hostParam.__str__())
                print 'Please be patient, this may take a few minutes...'
                print ''

                if not kernel.is_optimized_for_snc_mode() and micp_info.Info().is_in_sub_numa_cluster_mode():
                    warn = 'WARNING: {0} is not optimized to run on SNC modes, low performance may be expected'
                    print warn.format(kernel.name)
                    print ''

                if self._runDev:
                    if kernel.param_type() == 'value':
                        devArgs = devParam.value_str()
                    elif kernel.param_type() == 'flag':
                        devArgs = devParam.flag_str()
                    elif kernel.param_type() == 'pos':
                        devArgs = devParam.pos_str()
                    elif kernel.param_type() == 'file':
                        devParamFileOnHost = kernel.param_file(devParam)
                        devParamFile = self._CARD_EXECUTION_DIR + os.path.basename(devParamFileOnHost)
                        connect.copyto(devParamFileOnHost, devParamFile)
                        shutil.rmtree(os.path.dirname(devParamFileOnHost))

                         # hplinpack knows how to find the configuration file
                        if kernel.name != 'hplinpack':
                            devArgs = devParamFile
                        else:
                            devArgs = ''
                        devParamFile = [devParamFile]
                    elif kernel.param_type() == 'getopt':
                        devArgs = devParam.__str__()
                    else:
                        raise NameError('Unknown parameter type {0}'.format(kernel.param_type()))

                    command_line = 'cd {wdir} && {wdir}{binary} {args}'
                    devArgs = command_line.format(wdir=self._CARD_EXECUTION_DIR,
                                                  binary=os.path.basename(execPath),
                                                  args=devArgs)

                    devProcEnv = kernel.environment_dev()
                    for pn in kernel.param_for_env():
                        if pn == 'omp_num_threads' or pn == 'hpl_numthreads':
                            devProcEnv[pn.upper()] = devParam.get_named(pn)
                        else:
                            devProcEnv[pn] = devParam.get_named(pn)
                    devProc = self._run_workload(connect.Popen, devArgs, devProcEnv, self._CARD_EXECUTION_DIR, "Xeon Phi Coprocessor")

                if self._runHost:
                    if kernel.param_type() == 'value':
                        hostArgs = hostParam.value_list()
                    elif kernel.param_type() == 'flag':
                        hostArgs = hostParam.flag_list()
                    elif kernel.param_type() == 'pos':
                        hostArgs =  hostParam.pos_list()
                    elif kernel.param_type() == 'file':
                        hostParamFile = kernel.param_file(hostParam)

                        # hplinpack knows how to find the configuration file
                        if kernel.name != 'hplinpack':
                            hostArgs = [hostParamFile]
                        else:
                            hostArgs = []
                        hostParamFile = [hostParamFile]
                    elif kernel.param_type() == 'getopt':
                        hostArgs = hostParam.__str__().split()
                    else:
                        raise NameError('Unknown parameter type {0}'.format(kernel.param_type()))
                    hostArgs.insert(0, execPath)
                    hostProcEnv = copy.deepcopy(os.environ)
                    confProcEnv = kernel.environment_host()
                    for pn in kernel.param_for_env():
                        if pn == 'omp_num_threads' or pn == 'hpl_numthreads':
                            if micp_common.is_selfboot_platform():
                                # in SNC modes we want to saturate all clusters
                                is_sncX_mode = micp_info.Info().is_in_sub_numa_cluster_mode()
                                if is_sncX_mode:
                                    confProcEnv['KMP_HW_SUBSET'] = '{0}c,1t'.format(hostParam.get_named(pn))
                                else:
                                    confProcEnv[pn.upper()] = hostParam.get_named(pn)
                            else:
                                variable_name = 'MIC_{0}'.format(pn.upper())
                                confProcEnv['MIC_ENV_PREFIX'] = 'MIC'
                                confProcEnv[variable_name] = hostParam.get_named(pn)
                        else:
                            confProcEnv[pn] = hostParam.get_named(pn)
                    hostProcEnv.update(confProcEnv)
                    hostArgs = kernel.get_process_modifiers() + hostArgs + kernel.get_fixed_args()
                    if kernel.requires_root_access():
                        hostArgs = ['sudo'] + hostArgs
                    envs_string  = ' '.join([env + '=' + str(confProcEnv[env]) \
                        for env in confProcEnv if env != "LD_LIBRARY_PATH"])
                    mp_print(envs_string, CAT_ENV)
                    mp_print(' '.join(hostArgs), CAT_CMD)
                    hostProc = self._run_workload(localConnect.Popen, hostArgs, hostProcEnv, kernel.get_working_directory(), "host")
                try:
                    block = []
                    if self._runDev:
                        (devOut, devErr) = devProc.communicate()
                        print devOut
                        sys.stderr.write(devErr)
                        if devProc.returncode != 0:
                            raise micp_connect.CalledProcessError(devProc.returncode, devArgs)
                        block.append(devOut)
                        block.append(devErr)
                    if self._runHost:
                        (hostOut, hostErr) = hostProc.communicate()
                        if not kernelStdOut:
                            print hostOut
                        else:
                            # separate outputs in file by separator
                            outSepFormat = \
                                '{ch:=^{width}}\n{:=^{width}}\n{ch:=^{width}}'
                            outSeparator = \
                                outSepFormat.format(' ' + kernel.name + ' ',
                                    width=80, ch='')
                            kernelStdOut.write(outSeparator)
                            try:
                                kernelStdOut.write('\n' + hostOut + '\n')
                            except EnvironmentError as e:
                                err_msg = \
                                    'Failed writing "{}" kernel output to file.'
                                mp_print(err_msg.format(kernel.name), CAT_WARN)
                                mp_print("Output:\n{}".format(hostOut),
                                    wrap=False)
                        sys.stderr.write(hostErr)
                        if hostProc.returncode == 127:
                            raise micp_common.MissingDependenciesError(
                                micp_common.DEP_REDIST)
                        if hostProc.returncode != 0:
                            if kernel.name == 'hpcg' and self._is_name_resolution_error(hostErr):
                                sys.stderr.write(MPI_NAME_RESOLUTION_ERROR)
                            raise micp_connect.CalledProcessError(hostProc.returncode, ' '.join(hostArgs))
                        block.append(hostOut)
                        block.append(hostErr)
                    block = '\n'.join(block)
                finally:
                    if self._runDev and devProc.returncode is None:
                        execName = os.path.basename(execPath)
                        warningMsg = "WARNING:  more than one {0} process running on device, killing all of them".format(execName)
                        killStr =  'if [ `pgrep {0} | wc -l` -gt 1 ]; then echo {1}; fi; pkill -9 {0}'.format(execName, warningMsg)
                        pid = connect.Popen(killStr)
                        killOut, killErr = pid.communicate()
                        print '\n'.join([killOut, killErr])
                        devProc.kill()
                    if self._runHost and hostProc.returncode is None:
                        hostProc.kill()
                    kernel.clean_up(hostParamFile, devParamFile, connect)

                if kernel.internal_scaling():
                    thisResult = [micp_stats.Stats(hostParam, desc, perf)
                                  for (desc, perf) in zip(kernel.parse_desc(block),
                                                          kernel.parse_perf(block))]
                    if '[ PERFORMANCE ]' not in block:
                        for stat in thisResult:
                            stat.reprint()
                    result.extend(thisResult)
                else:
                    stat = micp_stats.Stats(hostParam, kernel.parse_desc(block), kernel.parse_perf(block))
                    if '[ PERFORMANCE ]' not in block:
                        stat.reprint()
                    result.append(stat)
        except (Exception, KeyboardInterrupt) as err:
            err.partialResult = result
            raise
        finally:
            kernel.clean_up([], filesToRemove + devParamFile, connect)

        # print peak point only if comparison function has been defined
        if len(result) > 1 and kernel._ordering_key(result[0]) is not None:
            try:
                _reverse_ordering = True
                if hasattr(kernel, '_reverse_ordering'):
                    _reverse_ordering = kernel._reverse_ordering
                max_result = sorted(result, key=kernel._ordering_key,
                    reverse =_reverse_ordering)[0]
                mp_print('\n')
                print micp_common.star_border('PEAK PERFORMANCE')
                max_result.reprint()
            except:
                # intercept whatever may be thrown inside but ignore
                # since it is not critical
                pass

        return result

class NativeOffload(Offload):
    def __init__(self):
        self.name = 'native'
        self._runDev = True
        self._runHost = False

    def run(self, kernel, device, paramList, kernelStdOut=None):
        """
        Native offload may require fewer parameters than the other
        offload methods.  This method removes extra parameters and then
        calls the super class version of run.
        """
        try:
            newParamList = []
            for pp in paramList:
                if pp.num_param() > kernel.paramMax['native']:
                    newParamList.append(
                    micp_params.ParamsDrop(pp,kernel.paramDrop['native'], kernel.paramMax['native']))
                else:
                    newParamList.append(pp)
            paramList = newParamList
        except (KeyError, AttributeError):
            pass
        return super(NativeOffload, self).run(kernel, device, paramList, kernelStdOut=kernelStdOut)

class COIOffload(Offload):
    def __init__(self):
        self.name = 'coi'
        self._runDev = False
        self._runHost = True

class AutoOffload(Offload):
    def __init__(self):
        self.name = 'auto'
        self._runDev = False
        self._runHost = True

class PragmaOffload(Offload):
    def __init__(self):
        self.name = 'pragma'
        self._runDev = False
        self._runHost = True

    def run(self, kernel, device, paramList, devParamList=None, kernelStdOut=None):
        connect = micp_connect.MPSSConnect(device)
        os.environ['OFFLOAD_DEVICES'] = str(connect.get_offload_index())
        return super(PragmaOffload, self).run(kernel, device, paramList, devParamList, kernelStdOut)

class SCIFOffload(Offload):
    def __init__(self):
        self.name = 'scif'
        self._runDev = True
        self._runHost = True

    def run(self, kernel, device, paramList, kernelStdOut=None):
        """
        SCIF offload may require different parameter on host and
        device.  This method removes extra parameters and then calls
        the super class version of run.
        """
        paramDropSign = 1

        # HPL automatically setups all the coprocessor side dependencies
        # micperf doesn't need to do anything in this case.
        if kernel.name == 'hplinpack':
            self._runDev = False
        else:
            self._runDev = True
        try:
            shortParamList = []
            paramDropSign = copysign(1, kernel.paramDrop['scif'])
            for pp in paramList:
                if (kernel.name == 'sgemm' or kernel.name == 'dgemm') and pp.get_named('test') != None:
                    pp.set_named('num_rep', '1')
                if pp.num_param() > kernel.paramMax['scif']:
                    shortParamList.append(
                    micp_params.ParamsDrop(pp, abs(kernel.paramDrop['scif']), kernel.paramMax['scif']))
                else:
                    shortParamList.append(pp)
        except (AttributeError, KeyError):
            shortParamList = None
        if paramDropSign == 1:
            return super(SCIFOffload, self).run(kernel, device, paramList, shortParamList, kernelStdOut=kernelStdOut)
        else:
            return super(SCIFOffload, self).run(kernel, device, shortParamList, paramList, kernelStdOut=kernelStdOut)


class MYOOffload(Offload):
    def __init__(self):
        self.name = 'myo'
        self._runDev = True
        self._runHost = True

    def run(self, kernel, device, paramList, kernelStdOut=None):
        try:
            newParamList = []
            for pp in paramList:
                if pp.num_param() > kernel.paramMax['myo']:
                    newParamList.append(
                    micp_params.ParamsDrop(pp,kernel.paramDrop['myo'], kernel.paramMax['myo']))
                else:
                    newParamList.append(pp)
            paramList = newParamList
        except (KeyError, AttributeError):
            pass
        devParamList = [micp_params.Params('',['']) for dummy in range(len(paramList))]
        return super(MYOOffload, self).run(kernel, device, paramList, devParamList, kernelStdOut)


class LocalOffload(Offload):
    def __init__(self):
        self.name = 'local'
        self._runDev = False
        self._runHost = True

class OffloadFactory(micp_common.Factory):
    def __init__(self):
        super(OffloadFactory,self).__init__()
        self.register('native', NativeOffload)
        self.register('scif', SCIFOffload)
        self.register('coi', COIOffload)
        self.register('myo',MYOOffload)
        self.register('pragma', PragmaOffload)
        self.register('auto', AutoOffload)
        self.register('local', LocalOffload)

    def register(self, theName, theClass):
        super(OffloadFactory,self).register(theName.lower(), theClass)

    def create(self, className):
        if className.lower() == 'linux_native':
            className = 'native'
        return super(OffloadFactory,self).create(className.lower())
