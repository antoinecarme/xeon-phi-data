#  Copyright 2012-2017, Intel Corporation, All Rights Reserved.
#
# This software is supplied under the terms of a license
# agreement or nondisclosure agreement with Intel Corp.
# and may not be copied or disclosed except in accordance
# with the terms of that agreement.
#
#  Author:  Christopher M. Cantalupo

"""
Module containing abstract base Kernel class and a factory to create
concrete kernels instances.
"""

import os
import re
import copy
import sys

import common as micp_common
import params as micp_params
import version as micp_version

LIBEXEC_DEV = micp_version.MIC_PERF_CARD_ARCH
LIBEXEC_HOST = micp_version.MIC_PERF_HOST_ARCH


class Kernel(object):
    """
    Abstract base class for computational kernels.  This class defines
    an interface for integrating workloads into micp.  The class
    implements a default behavior for workloads that have a simple
    positional parameter command line interface.  Other workload
    application interfaces are supported (long form command line
    interface, short form flag command line interface, and parameter
    file).  The simplest derived kernel will implement only the
    __init__() method to define some attributes that determine the
    default behavior.
    """

    def __init__(self):
        """
        The initializer must be implemented for every derived class.
        The only attribute that is part of the Kernel interface is:

        self.name:
            Name of the kernel, which can differ from self.__name__
            if the name of the kernel does not meet the requirements of
            the name of a class (e.g. name starts with a numeral).

        To use default implementation __init__() must define the
        following private attributes:

        self._paramNames:
            List of names for parameters, these must be unique
            strings.  In the case of a kernel that uses getopt style
            parameters this attribute is a list of tuples.  The first
            element of each tuple is the name of a parameter.  The
            other tuple elements are any short form, long form, or
            position index that are associated with that parameter
            name.

        self._paramDefaults:
            Dictionary of default values with keys that match values
            in the self._paramNames list.

        self._categoryParams:
            Dictionary that maps parameter category names with lists
            of parameter strings.  This dictionary must contain at
            least the 'scaling' key (if the 'optimal' key is not
            provided it is taken to be the last of the scaling
            parameter strings).

        self._reverse_ordering:
            When set to False ordering_key will treat lower score value
            as better.
        """
        self.name = self.__name__
        self._paramNames = []
        self._paramDefaults = {}
        self._categoryParams = {'scaling': ' '}
        raise NotImplementedError('Abstract base class')

    def help(self, message=None, offload=None):
        """
        Returns a message that describes how to use the kernel.  This
        description includes the kernel parameters and default values
        for those parameters.
        """
        if message:
            header = 'Parameter help for kernel {0}:'.format(self.name)
        else:
            header = 'Parameter help for kernel {0} <param:default>:'.format(self.name)
            param_defaults = self.param_defaults(offload)
            message = ['<{0}:{1}>'.format(pn, param_defaults[pn])
                       if pn in param_defaults else
                       '<{0}>'.format(pn)
                       for pn in self.param_names()]
            message = ' '.join(message)
        message = '\n'.join((header, message, ''))
        return message

    def path_host_exec(self, offType):
        """
        Returns the path to the host executable for the offload class
        named offType.  Default implementation looks in the standard
        location and assumes that the executable name is the same as
        the class name.
        """
        return self._path_exec('intel64', self.name)

    def path_dev_exec(self, offType):
        """
        Returns the path to the device executable for the offload
        class named offType.  Default implementation looks in the
        standard location and assumes that the executable name is the
        same as the class name.
        """
        return self._path_exec('mic', self.name)

    def path_aux_data(self, offType):
        """
        Returns a list of paths to files on the host that will be
        copied to /tmp on the device when using the the offload class
        named offType.
        """
        return []

    def parse_desc(self, raw):
        """
        Parses the standard output from the execution of a kernel and
        returns a string that describes the run.

        For kernels that implement internal scaling,
        (self.internal_scaling() is True) this will be a list of
        descriptions.
        """
        expr = re.compile(r'\[ DESCRIPTION \].*\n')
        result = expr.search(raw)
        if result != None:
            result = result.group(0).strip()[16:]
        else:
            result = ''
        return result

    def parse_perf(self, raw):
        """
        Parses the standard output from the execution of a kernel
        passed as the parameter raw.  Returns a nested dictionary of
        the form:

        result[tag] = {'value':value, 'units':units, 'rollup':isRolled}

        Here tag is a descriptive identifier, value is the value of
        the performance metric, units are the units of this metric,
        and isRolled is a boolean value.  Performance data that are not
        rolled up (isRolled is False) require a higher verbosity for
        reporting and are not included in plots.

        Default implementation assumes the raw data contains lines of
        the form:

        [ PERFORMANCE ] tag value units R

        where trailing R is optional and if present implies isRolled
        is True.

        Kernels that implement internal scaling
        (self.internal_scaling() is True) return a list of the
        dictionaries described above rather than a single dictionary.
        """
        if self.internal_scaling():
            raise NotImplementedError('Default implementation of parse_perf() does not work if internal_scaling() is True')
        blocks = raw.split('[ PERFORMANCE ]')
        blocks.pop(0)
        result = {}
        for bb in blocks:
            bb = bb.strip().split()
            data = {}
            data['value'] = bb[1]
            data['units'] = bb[2]
            data['rollup'] = len(bb) > 3 and bb[3] == 'R'
            result[bb[0]] = data
        return result

    def param_names(self, full=False):
        """
        Returns a copy of the list of parameter names.  Default
        implementation depends on self._paramNames being defined.
        """
        if '_paramNames' in self.__dict__:
            if full:
                return list(self._paramNames)
            else:
                return [pn if isinstance(pn, str) else pn[0] for pn in self._paramNames]
        else:
            raise NotImplementedError('Abstract base class')

    def param_defaults(self, offload=None):
        """
        Returns a copy of the dictionary of default parameter values.
        The dictionary keys are the parameter names, and the defaults
        are stored in the dictionary values.  Default implementation
        depends on self._paramDefaults being defined.
        """
        if '_paramDefaults' in  self.__dict__:
            return dict(self._paramDefaults)
        else:
            return {}

    def param_for_env(self):
        """
        Returns a list of parameters that are passed to the workload
        by way of shell environment variables rather than the command
        line or parameter file.  This is a way of mapping kernel
        parameters to environment variables.

        Note that there is a special case for the environment variable
        OMP_NUM_THREADS which can be controlled by the kernel parameter
        omp_num_threads.  Other variables names in this list are
        mapped to the environment unchanged.
        """
        return []

    def category_params(self, category, offload=None):
        """
        Returns a list of parameters that define the parameter
        category specified.
        """
        if '_categoryParams' in self.__dict__:
            try:
                params = copy.deepcopy(self._categoryParams[category])
            except KeyError:
                if category == 'optimal' and 'scaling' in self._categoryParams:
                    params = copy.deepcopy([self._categoryParams['scaling'][-1]])
                else:
                    raise NameError('Unknonwn parameter category {0}'.format(category))

            # update parameters depending on offload method
            return self._update_params(params, offload)

        else:
            raise NotImplementedError('Abstract base class')


    def _update_params(self, current_params, offload):
        """Depending on the offload method kernel parameters may need to be
        updated. By default this method just returns the input params list,
        derived classes should override as needed.
        Receives a list of parameters params and the offload method (string).
        """
        return current_params


    def independent_var(self, category):
        """
        Returns the name of the parameter that should be plotted on
        the x-axis when plotting data generated for the specified
        parameter category.
        """
        try:
            if 'num_core' in self.param_names():
                return 'num_core'
            elif 'num_thread' in self.param_names():
                return 'num_thread'
            else:
                raise NameError('Neither num_core or num_thread are parameters')
        except AttributeError:
            return 'num_core'

    def offload_methods(self):
        """
        Returns a list of offload names that are supported by the
        kernel.
        """
        return []

    def param_type(self):
        """
        Returns one of four strings that define the type of parameters
        used by the kernel:  'pos', 'value', 'flag', 'file', or 'getopt'.

        pos: Kernel uses positional command line arguments without
        flags where the parameter order is given by the ordering of
        list returned by self.param_names(), e.g.
        user_prompt> executable 1 2 3

        value: Kernel uses long form parameters, e.g.
        user_prompt> executable --a_param 1 --b_param 2 --c_param 3

        flag: Kernel uses short form parameters where the flag is
        given by the first character in the parameter name e.g.
        user_prompt> executable -a 1 -b 2 -c 3

        file: Kernel uses a parameter file created by the method
        self.param_file(param) e.g.
        user_prompt> executable paramFile.txt
        """
        return 'pos'

    def internal_scaling(self):
        """
        Returns a Boolean value that indicates if the executable can
        scale the value of a parameter internally at run time rather
        than requiring multiple executions of the executable and
        varying a command line argument.  When this is the case the
        parsing methods will return a list of results from each
        execution rather than a single value.
        """
        return False

    def environment_host(self):
        """
        Returns a dictionary of environment variables that will be
        set for all executions of the kernel on the host.
        """
        return {}

    def environment_dev(self):
        """
        Returns a dictionary of environment variables that will be
        set for all executions of the kernel on the device.
        """
        return {}

    def param_file(self, param):
        """
        For kernels who have a self.param_type() of 'file' this method
        creates a parameter file on disk derived from the argument
        param and returns the path to this parameter file.
        """
        return None

    def mic_library_find(self, libName):
        ldLibraryPath = self.mic_ld_library_path().split(os.pathsep)
        try:
            return [os.path.join(pp, libName) for pp in ldLibraryPath if os.path.exists(os.path.join(pp, libName))][0]
        except (KeyError, IndexError):
            raise micp_common.MissingDependenciesError(
                micp_common.DEP_REDIST)

    def mic_ld_library_path(self):
        """
        Returns a string that augments the environment variable
        MIC_LD_LIBRARY_PATH (KNC) or LD_LIBRARY_PATH (KNL).
        The default implementation adds the location of the
        device side libraries for COI and MYO.
        """
        # TODO: Complete KNL LB Windows implementation
        if micp_common.is_platform_windows():
            mpssLibDir = os.environ.get('INTEL_MPSS_HOST_SDK',
                                        'C:\\Program Files\\Intel\\MPSS\\sdk\\lib')
            if 'MIC_LD_LIBRARY_PATH' in os.environ:
                ldLibraryPath = os.environ['MIC_LD_LIBRARY_PATH']
                return ';'.join([ldLibraryPath, mpssLibDir])
            else:
                return mpssLibDir
        else:
            # The KNL binaries are fully compatible with the x86_64 architecture
            # thus it is possible to use the same shared libraries used by the
            # host system. KNC architecture uses its own set of libraries.
            card_family, __ = micp_common.num_mics_pci()
            if card_family == micp_common.KNC:
                ld_library_path = 'MIC_LD_LIBRARY_PATH'
            else:
                ld_library_path = 'LD_LIBRARY_PATH'

            return os.environ.get(ld_library_path, '')

    def ld_library_path(self):
        """
        Returns a string that augments the environment variable
        LD_LIBRARY_PATH.  The default implementation simply returns
        LD_LIBRARY_PATH unaltered.
        """
        return os.environ.get('LD_LIBRARY_PATH', '')

    def device_param_name(self):
        """
        Returns the kernel parameter name that controls the index of the
        device that will be used for offload.
        """
        return 'device'

    def _do_unit_test(self):
        """
        Returns a Boolean value that indicates if the kernel
        implements a self check appropriate for use in the kernel unit
        testing.
        """
        return False

    def _path_exec(self, arch, binName):
        """
        Helper method which looks for the binary in its default
        location given an architecture arch and binary name binName.
        """
        archMap = {'intel64':'x86_64', 'mic':micp_version.MIC_PERF_CARD_ARCH}
        arch = archMap.get(arch, arch)

        pathList = []
        if arch != 'mic':
            pathList.extend(os.environ.get('PATH', '').split(os.pathsep))

        execDir = os.environ.get('MIC_PERF_EXEC', micp_version.MIC_PERF_EXEC)
        execDir = os.path.join(execDir, arch)
        pathList.insert(0, execDir)
        for path in pathList:
            result = os.path.join(path, binName)
            if os.path.exists(result):
                return result
        raise NoExecutableError('Could not find executable for {0} kernel'.format(self.name))

    def _set_defaults_to_optimal(self):
        """
        Can be called at the end of __init__ to insure that the default
        parameters match the optimal parameters.
        """
        if self.param_type() == 'getopt':
            optimal = micp_params.ParamsGetopt(self.category_params('optimal')[-1],
                                               self._paramNames, self._options,
                                               self._longOptions, self._paramDefaults)
        else:
            optimal = micp_params.Params(self.category_params('optimal')[-1],
                                         self._paramNames, self._paramDefaults)
        self._paramDefaults = dict([(nn, optimal.get_named(nn))
                                    for nn in self.param_names()])


    def clean_up(self, local_files, remote_files, remote_shell=None):
        """
        Receives a list of files to be removed from the local host, the remote
        device or both
        """

        if local_files:
            for _file in local_files:
                os.unlink(os.path.abspath(_file))

        if remote_files:
            if remote_shell is None:
                raise InternalError()

            remove_files = ['rm' ,'-f'] + remote_files
            remove_files = ' '.join(remove_files)
            pid = remote_shell.Popen(remove_files)
            pid.communicate()

    def get_working_directory(self):
        """
        Derived classes should override accordingly, by default there's no
        working directory for any of the kernels
        """
        return None

    def get_process_modifiers(self):
        """
        Method should return a list of "process modifiers" (host side) e.g.
        numactl, mpirun by default list is empty, derived classes should override
        accordingly.
        """
        return []

    def get_fixed_args(self):
        """
        Returns the list of additional fixed command line parameters that will
        be passed when executing kernel binary regardless choosen paramter
        type (by function param_type). Those parmeters cannot be changed by
        the user.
        """
        return []

    def is_mpi_required(self):
        """returns True if kernel requires MPI to be executed. Returns by default
        False, derived classes should override accordingly."""
        return False

    def is_optimized_for_snc_mode(self):
        """returns True if kernel is optimized for SNC2/SNC4. Returns False by
        default, derived classes should override accordingly."""
        return False

    def requires_root_access(self):
        """returns True if kernel has to be run in privileged mode, False
        otherwise"""
        return False

    def _ordering_key(self, stat):
        """if defined this function enables printing summary with peak
        performance (when multiple runs were executed). Kernel
        implementation should return member of 'Stats' that will be
        used for ordering. Type of returned value should be comparable.

        Note: by default higher score is being treat as better, set
        self._reverse_ordering = False in derived class to switch logic"""
        return None


class KernelFactory(micp_common.Factory):
    """
    Factory class for creating concrete kernel instances from derived
    kernel classes found in the kernel sub-directory module.
    """
    def __init__(self):
        self._classMap = {}
        self.register_pkg('kernels')

    def register_pkg(self, pkgName):
        package = __import__(pkgName, globals(), locals(), [], -1)
        moduleNameList = package.__all__
        moduleList = [__import__('.'.join((pkgName, moduleName)), globals(), locals(), [], -1)
                      for moduleName in moduleNameList]
        moduleList = [module.__dict__[moduleName]
                      for (module, moduleName) in zip(moduleList, moduleNameList)]
        success = False
        for module in moduleList:
            try:
                self.register(module)
                success = True
            except NameError as registerErr:
                pass
        if not success:
            raise registerErr

    def register(self, module):
        moduleName = module.__name__
        dotLoc = moduleName.rfind('.')
        if dotLoc != -1:
            moduleName = moduleName[dotLoc+1:]
        className = [c for c in dir(module) if c.lower() == moduleName.lower()]
        if len(className) == 0:
            raise NameError('No attribute matching module name in ' + moduleName)
        if len(className) > 1:
            sys.stderr.write('WARNING: micp_kernel.Factory found more than one\n')
            sys.stderr.write('kernel class in ' + moduleName + '\n')
            sys.stderr.write('         Choosing first one named ' + className[0] + '\n')
        if self._classMap.has_key(moduleName):
            sys.stderr.write('WARNING: micp_kernel.Factory overwriting\n')
            sys.stderr.write('factory method ' + moduleName + '\n')
        self._classMap[moduleName] = eval('module.' + className[0])

    def create(self, name):
        deprecationDict = {'1dfft': 'onedfft',
                           '1dfft_streaming': 'onedfft_streaming',
                           '2dfft': 'twodfft',
                           'dgemm_mkl': 'dgemm',
                           'sgemm_mkl': 'sgemm',
                           'linpack_dp': 'linpack',
                           'stream_mccalpin': 'stream'}
        if name in deprecationDict:
            sys.stderr.write('WARNING:  Kernel name {0} deprecated, use {1}\n'.format(name, deprecationDict[name]))
            name = deprecationDict[name]
        return super(KernelFactory,self).create(name)

def add_rollup(raw, tag):
    """
    Returns a buffer that has ' R' appended to all performance report
    lines in the text buffer raw that are tagged with string tag.
    """
    result = []
    for line in raw.split('\n'):
        words = line.split('[ PERFORMANCE ] ')
        if len(words) == 2 and words[0] == '' and words[1].startswith(tag + ' ') and not line.endswith(' R'):
            line = line + ' R'
        result.append(line)
    result = '\n'.join(result)
    return result

class NoExecutableError(micp_common.MicpException):
    """Requested executable has not been found"""
    def micp_exit_code(self):
        return micp_common.E_LIB

class SelfCheckError(micp_common.MicpException):
    """Kernel handling exception"""
    def micp_exit_code(self):
        return micp_common.E_EXCEPT

def raise_parse_error(raw, msg=''):
    """ helper function to raise parse exceptions when parsing
    kernel output"""
    micp_common.mp_print("Failed parsing output [{}]:".format(
        micp_common.get_ln(True)), micp_common.CAT_ERROR)
    micp_common.mp_print(raw, wrap=False)
    raise SelfCheckError(msg)
