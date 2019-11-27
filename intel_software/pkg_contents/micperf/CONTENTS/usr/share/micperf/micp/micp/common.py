#  Copyright 2012-2017, Intel Corporation, All Rights Reserved.
#
# This software is supplied under the terms of a license
# agreement or nondisclosure agreement with Intel Corp.
# and may not be copied or disclosed except in accordance
# with the terms of that agreement.
#
#  Author:  Christopher M. Cantalupo

import platform
import sys
import re
import os
import textwrap
import subprocess

from os.path import join, isdir, exists
from distutils.spawn import find_executable

from inspect import currentframe, getframeinfo, getouterframes
import connect as micp_connect

# constants to identify KNC/KCL cards internally
KNL = 'knl'
KNC = 'knc'

# Xeon Phi model and family as reported in the sysfs
XEON_PHI_PROCESSOR_FAMILY = 6
XEON_PHI_PROCESSOR_MODEL = (87, 133) #KNL, KNM

# linux commands
READ_CPUINFO_PROCFS = 'cat /proc/cpuinfo'
READ_MEMINFO_PROCFS = 'cat /proc/meminfo'

#internal constants
LOCAL_HOST_ID = ('local', 'localhost', '-1', -1)

# error messages
NO_REFERENCE_TAGS_ERROR = """Could not find any reference data MIC_PERF_DATA
may be poiting to an invalid directory or micperf reference data is not
installed."""

NON_EXISTENT_FILE_ERROR = """Could not open file named {0}"""

NON_EXISTENT_OUT_DIRECTORY_ERROR = """Could not write to directory {0}, as it
does not exist."""

EMSG_SOURCE_VARS = """Make sure that compilervars.sh from
Composer_XE is sourced in your working environment."""

EMSG_NO_REDIST = """The Composer_XE_2017 redistributable
package located here:
https://software.intel.com/en-us/articles/redistributables-for-intel-parallel-studio-xe-2017-composer-edition-for-{}
can be installed to access the required shared object libraries."""

EMSG_NO_MPI = """mpirun executable was not found on this system.
Intel MPI runtimes are freely available for download here:
https://software.intel.com/en-us/intel-mpi-library
Note that mpivars.sh have to be sourced before run"""

EMSG_NO_LINPACK = """MKL Linpack is available for download here:
http://software.intel.com/en-us/articles/intel-math-kernel-library-linpack-download
The environment variable MKLROOT must point to the location of the
directory extracted from the .tgz file."""

## error/exit codes
# No error
E_NO_ERROR = 0
# General exception
E_EXCEPT = 1
# Input parse error
E_PARSE = 2
# I/O error
E_IO = 3
# Permission denied
E_ACCESS = 87
# Performance regression
E_PERF = 88
# MPSS not found
E_MPSS_NA = 89
# Wrong key/index/name
E_LOOKUP = 90
# Missing dependency
E_DEP = 91
# No executable
E_EXEC = 126
# Missing library
E_LIB = 127

class MicpException(Exception):
    """Micperf exception"""

    def micp_exit_code(self):
        """returns micperf exit code"""
        return E_EXCEPT

class NoExecutionPermission(MicpException):
    """Exception to notify binaries with no execution permissions"""
    def micp_exit_code(self):
        return E_EXCEPT

class WindowsMicInfoError(MicpException):
    """Exception to notify micinfo is not installed on windows"""
    def micp_exit_code(self):
        return E_EXCEPT

class FactoryLookupError(MicpException):
    """Exception to be raised when class was not found in class factory"""
    def micp_exit_code(self):
        return E_LOOKUP

DEP_REDIST = "redist"
DEP_MPI = "mpi"
DEP_LINPACK = "Linpack"

class MissingDependenciesError(MicpException):
    """Exception to be raised when dependencies are not met"""

    def __init__(self, dep):
        errString = ''
        self.dep = dep
        if dep is DEP_REDIST:
            errString = EMSG_NO_REDIST
            if is_platform_windows():
                errString = errString.format("windows")
            else:
                errString = errString.format("linux")
                errString = EMSG_SOURCE_VARS + " " + errString
        elif dep is DEP_MPI:
            errString = EMSG_NO_MPI
        elif dep is DEP_LINPACK:
            errString = EMSG_NO_LINPACK

        super(MissingDependenciesError, self).__init__(errString)

    def micp_exit_code(self):
        # put here for backward compatibility
        if self.dep is DEP_REDIST:
            return E_LIB
        return E_DEP

class PermissionDeniedError(MicpException):
    """Exception to be raised when user lacks required permissions to
    perform requested operation"""
    def micp_exit_code(self):
        return E_ACCESS

class Factory(object):
    def __init__(self):
        self._classMap = {}

    def register(self, theName, theClass):
        self._classMap[theName] = theClass

    def class_names(self):
        return sorted(self._classMap.keys())

    def create(self, className):
        try:
            resultClass = self._classMap[className]
        except KeyError:
            nameList = '\n\t'.join(self.class_names())
            kernelsListMsg = \
                'No registered class named "{}".\nAvailable classes: \n\t{}'
            print kernelsListMsg.format(className, nameList)
            raise FactoryLookupError("")
        return resultClass()


def star_border(name):
    lineWidth = 80
    minStars = 5
    if name:
        name = ' ' + name + ' '
    if len(name) < lineWidth - 2*minStars:
        leftStars = (lineWidth - len(name))/2
        rightStars = lineWidth - (leftStars + len(name))
        return '*'*leftStars + name + '*'*rightStars
    else:
        return '*'*minStars + name + '*'*minStars

def is_platform_windows():
    return platform.platform().lower().startswith('windows')

def init_static_var(variable, value):
    """decorator to initialize static variables"""
    def decorate(function):
        setattr(function, variable, value)
        return function
    return decorate


@init_static_var("result", None)
def is_selfboot_platform():
    """check if micperf is running on a Xeon Phi Processor"""
    # a static variable is used to store final result
    if is_selfboot_platform.result is not None:
        return is_selfboot_platform.result

    if is_platform_windows():
        is_selfboot_platform.result = _windows_is_selfboot()
    else:
        is_selfboot_platform.result = _linux_is_selfboot()

    return is_selfboot_platform.result


def _windows_is_selfboot():
    """returns true if processor is Xeon Phi false otherwise (windows)"""
    local_shell = micp_connect.LocalConnect()
    wmic_cpu_desc = local_shell.Popen("wmic cpu get description /format:csv")
    stdout, stderr = wmic_cpu_desc.communicate()

    if wmic_cpu_desc.returncode:
        error = "ERROR: Unable to determine platform model Xeon or Xeon Phi\n{0}"
        raise OSError(error.format(stderr))

    # expected id '.. Family F Model MM...'
    xeon_phi_ids = [ r'\s*family\s*{0}\s*model\s*{1}'.format(XEON_PHI_PROCESSOR_FAMILY, model)
                    for model in XEON_PHI_PROCESSOR_MODEL ]

    for line in stdout.splitlines():
        for xeon_phi_id in xeon_phi_ids:
            if re.search(xeon_phi_id, line, re.I):
                return True

    # if this point is reached, this is NOT a Xeon Phi Processor
    return False


def _linux_is_selfboot():
    """returns true if processor is Xeon Phi false otherwise (linux)"""
    # This method assumes this is NOT a Xeon Phi Processor and read procfs to confirm it
    mic_device = micp_connect.LocalConnect()
    cpuinfo = mic_device.Popen(READ_CPUINFO_PROCFS)
    output, stderr = cpuinfo.communicate()

    if cpuinfo.returncode:
        error = "ERROR: Unable to determine platform model Xeon or Xeon Phi\n{0}"
        raise OSError(error.format(stderr))

    is_sb_model = False
    is_sb_family = False
    output = output.splitlines()
    for line in output:
        # line expected format "property name : value"

        if re.match(r'^model\s+:\s*\d+', line):
            actual_model = int(line.split(':')[1])
            is_sb_model = actual_model in XEON_PHI_PROCESSOR_MODEL

        if re.match(r'^cpu family', line):
            actual_family = int(line.split(':')[1])
            is_sb_family = actual_family == XEON_PHI_PROCESSOR_FAMILY

        if is_sb_model and is_sb_family:
            return True

    # if this point is reached initial assumption is confirmed
    return False


def exit_application(message, exit_code):
    """ prints message to stderr or stdout depending on exit_code
    and terminates the application

    IMPORTANT: this function should only be called from the front end
    scripts: micpprun, micpplot, micpinfo, micpcsv and micpprint"""
    if exit_code:
        sys.stderr.write(message)
    else:
        print message
    sys.exit(exit_code)


def _read_file(path):
    """reads a file given by path, removes trailing white spaces,
    tabs and new lines and returns result"""
    with open(path) as attrib:
        data = attrib.read()
    return data.rstrip(' \t\n\r')

def num_mics_pci():
    """Return a tuple (<family>, <coprocessors_present>),
    only available for linux"""
    #device ID for the x100 family (KNC)
    knc_did_re = re.compile("^0x225[0-9a-f]$", re.I)
    #device ID for the x200 family (KNL)
    # 0x2264 reserved for DMA channels
    knl_did_re = re.compile("^0x226[01235]$", re.I)

    pci_devs_path = "/sys/bus/pci/devices"
    all_devs = filter(isdir, [join(pci_devs_path, d)
                        for d in os.listdir(pci_devs_path)])

    #get a list of tuples (<vendor>, <device>)
    all_devs = [(_read_file(join(d, "vendor")), _read_file(join(d, "device")))
                for d in all_devs if exists(join(d, "vendor"))
                                 and exists(join(d, "device"))]
    all_mics = [device for vendor, device in all_devs
                if vendor == "0x8086" and (knc_did_re.match(device) or
                knl_did_re.match(device))]

    if not all_mics:
        return "", 0

    return (KNL if knl_did_re.match(all_mics[0]) else KNC,
            len(all_mics))


def unsigned_int(param):
    """validate if the string param represents a unsigned
    integer, raises a ValueError Exception on failure"""
    if param.isdigit():
        return True
    error = 'unsigned integer expected got "{0}" instead'.format(param)
    raise ValueError(error)


def signed_int(param):
    """validate if the string param represents a signed
    integer, raises a ValueError Exception on failure"""
    if re.match('^-?\d+$', param):
        return True
    error = 'signed integer expected got "{0}" instead'.format(param)
    raise ValueError(error)


def custom_type(param, regex):
    """returns true if param matches the pattern given by regex
    such regex should have the format 'value1|value2|...|valueN'
    to easily format the error message"""
    pattern = '^{0}$'.format(regex)
    if re.match(pattern, param):
        return True
    expected = regex.replace('|', ' or ')
    error = ('argument should have one of following values:'
             ' "{0}" got "{1}" instead')
    raise ValueError(error.format(expected, param))


def no_check(param):
    """doesn't perform any check, always returns true"""
    return True

def no_args(param):
    """returns True if param is not empty (useful to validate options that
    do not take any arguments), raises a ValueError Exception on failure."""
    if not param:
        return True

    error = 'This option does not take any arguments, \'{0}\' found'
    raise ValueError(error.format(param))

def is_mpi_available():
    """verify if mpirun is available in the system's PATH"""
    if is_platform_windows():
        # TODO: Support for Windows
        return False

    return find_executable('mpirun')

def get_ln(getOuter = False):
    """ get line number of call, for debugging.
    getOuter = False - gets line number of this call
    getOuter = True - gets line number of calling function
    """

    outerFrame = 2 if getOuter else 1
    CONST_1st_level_frame = 0
    ln = None

    # current frame
    cf = currentframe()
    if not cf:
        return None
    try:
        # outer frame
        of = getouterframes(cf)[outerFrame]
        ln = getframeinfo(of[CONST_1st_level_frame]).lineno
    except:
        pass
    finally:
        del cf

    return ln

CONST_category_max_width = 11
CONST_msg_format = '[ {:<' + str(CONST_category_max_width) + '} ] '

CAT_ERROR = "ERROR"
CAT_WARN = "WARNING"
CAT_INFO = "INFO"
CAT_CMD = "CMD LINE"
CAT_ENV = "ENVIRONMENT"
CAT_OFFLOAD = "OFFLOAD"
CAT_DESC = "DESCRIPTION"
CAT_PERF = "PERFORMANCE"

def mp_print(text, category=None, wrap=True, width=80,
    _indent=' ' * len(CONST_msg_format.format(''))):
    """pretty prints the text in predefined format:
    [CATEGORY] lines of max width equal to 'width'

    - used without category to print continuation of previous
      message

    - use wrap=False for preformatted text

    - _indent is internal, passed as parameter for
      code optimization"""

    if not text:
        return ""

    category_pref = CONST_msg_format.format(category)
    text = "{}{}".format(category_pref if category else "", text.strip("\n\r"))

    if wrap:
        initial_indent=_indent

        if category:
            initial_indent = ''

        # reindent
        text = textwrap.dedent(text)
        text = textwrap.fill(text, width=width, initial_indent=initial_indent,
            subsequent_indent=_indent)
    else:
        if category:
            text = _indent.join(text.splitlines(True))
        else:
            text = _indent + _indent.join(text.splitlines(True))

    text = text + '\n'

    if category in [CAT_ERROR, CAT_WARN]:
        mp_print.out = sys.stderr
    elif category:
        mp_print.out = sys.stdout
    try:
        # try in case no category was ever set
        mp_print.out.write(text)
    except:
        mp_print.out = sys.stderr
        mp_print.out.write(text)

    return text
