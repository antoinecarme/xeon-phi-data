# Copyright 2012-2017, Intel Corporation, All Rights Reserved.
#
# This software is supplied under the terms of a license
# agreement or nondisclosure agreement with Intel Corp.
# and may not be copied or disclosed except in accordance
# with the terms of that agreement.\
#
#  Author:  Christopher M. Cantalupo

"""
Module containing the Info class which follows the mono-state
pattern. This class stores information about the hardware and software
characteristics of a system.  There are also module level functions
for accessing the system information that mirror the Info class API.
"""

import subprocess
import re
import hashlib
import shlex
import os
import distutils.version
import copy
import platform
import sys

import common as micp_common
import connect as micp_connect
import micp.version as micp_version

from common import mp_print, CAT_INFO

SNC2_CPU_NUMA_NODES = 2
SNC4_CPU_NUMA_NODES = 4

# number of threads to saturate chip (max performance) in SNC modes
MAX_THREADS_SNC2 = 32
MAX_THREADS_SNC4 = 16

# Xeon Phi Family Codenames
INTEL_KNL = "KNL"
INTEL_KNM = "KNM"

def system_hw_hash():
    return Info().system_hw_hash()

def mpss_version():
    return Info().mpss_version()

def micperf_version():
    return Info().micperf_version()

def num_cores(devIdx):
    info = Info()
    origIdx = info.get_device_index()
    info.set_device_index(devIdx)
    result = info.num_cores()
    info.set_device_index(origIdx)
    return result

def mic_memory_size(devIdx):
    info = Info()
    origIdx = info.get_device_index()
    info.set_device_index(devIdx)
    result = info.mic_memory_size()
    info.set_device_index(origIdx)
    return result

def mic_stepping(devIdx):
    info = Info()
    origIdx = info.get_device_index()
    info.set_device_index(devIdx)
    result = info.mic_stepping()
    info.set_device_index(origIdx)
    return result

def micinfo_basic(devIdx):
    info = Info()
    origIdx = info.get_device_index()
    info.set_device_index(devIdx)
    result = info.micinfo_basic()
    info.set_device_index(origIdx)
    return result

def mic_sku(devIdx):
    info = Info()
    origIdx = info.get_device_index()
    info.set_device_index(devIdx)
    result = info.mic_sku()
    info.set_device_index(origIdx)
    return result


class InfoKNXXB(object):
    """
    abstract class that represents a KNX Processor or KNX Coprocessor
    (hardware and software) system configuration.

    The derived class should define the following private members:
     _commandDict: a dictionary that maps the commands in the list
        returned by _get_command_list() to its corresponding output.
     _micinfoDict: a dictionary of dictionaries that maps a device
        in the system (host, mic0, mic1, micN) to its 'properties'.

    Example:
        _commandDict = { 'uname -r':'2.6.32',
                         'uname -s':'Linux', ...}
        _micinfoDict = { 'host':{'OS name':'Linux', ...},
                         'mic0':{'Active Cores':61, ..},
                         ... }
    """
    # constants to identify system information
    # host info
    _HOST_OS_NAME = 'Host OS'
    _HOST_OS_VERSION = 'OS Version'
    _HOST_FAMILY = 'CPU Family'
    _HOST_PHYSICAL_MEMORY = 'Host Physical Memory'
    _HOST_CPU_SPEED = 'CPU Speed'

    # MIC architecture related info
    _MIC_ACTIVE_CORES = 'Total No of Active Cores'
    _MIC_PCI_SPEED = 'PCIe Speed'
    _MIC_PCI_WIDTH = 'PCIe Width'
    _MIC_PCI_MAX_PAYLOAD = 'PCIe Max payload size'
    _MIC_PCI_MAX_READ = 'PCIe Max read req size'
    _MIC_DEVICE_ID = 'Device ID'
    _MIC_SUBSYSTEM_ID = 'SubSystem ID'
    _MIC_STEPPING_ID = 'Coprocessor Stepping ID'
    _MIC_MODEL_EXT = 'Coprocessor Model Ext'
    _MIC_TYPE = 'Coprocessor Type'
    _MIC_FAMILY_EXT = 'Coprocessor Family Ext'
    _MIC_SKU = 'Board SKU'

    # derived classes should define the following constants
    _MIC_FAMILY = None
    _MIC_VENDOR_ID = None
    _MIC_MODEL = None
    _MIC_STEPPING = None
    _MIC_MEMORY_SIZE = None
    _MIC_SOFTWARE_VERSION = None
    _MIC_SPEED = None

    # additional constants
    _BYTES = 'bytes'
    _MBYTES = 'mbytes'

    def __init__(self):
        """derived classes should provide a proper constructor"""
        raise NotImplementedError("Error: abstract class")

    def __str__(self, categories=None):
        """
        string representation, by default it includes all the
        information stored in the dictionary _commandDict or
        a subset can chosen using the input argument 'categories'
        """
        if not categories:
            categories = self.get_app_list()
        elif type(categories) == str:
            categories = [categories]
        unorderedKeys = self._commandDict.keys()
        keys = []
        for category in categories:
            theseKeys = sorted([key for key in unorderedKeys if category in key])
            if len(theseKeys) == 0:
                raise LookupError('Requested application {0} not found'.format(category))
            keys.extend(theseKeys)
        result = []
        keys = sorted(list(set(keys)))
        for cmd in keys:
            result.append(micp_common.star_border(cmd))
            result.append(self._commandDict[cmd])
        return '\n'.join(result)

    def get_device_index(self):
        """
        For KNX coprocessors the device index should match
        the card number e.g. device index is 0 for mic0.

        For KNL Processors the device index is set to -1
        if micperf if running on the localhost it may be
        different for a remote host.
        """
        return self._devIdx

    def set_device_index(self, devIdx):
        """device index setter, see get_device_index()"""
        self._devIdx = devIdx

    def get_device_name(self):
        """
        derived classes should provide a proper implementation
        the device name is used internally as a key to access
        the device's information.
        This method should return the device name of the device pointed
        by device index e.g. if device index is 0 get_device_name()
        returns 'mic0'
        """
        raise NotImplemented("Error: abstract method")

    def set_device_name(self, name):
        """
        derived classes should provide a proper implementation
        see get_device_name().
        """
        raise NotImplemented("Error: abstract method")

    def num_cores(self):
        """get number of cores of the device pointed by the device index"""
        devID = self.get_device_name()
        return int(self._micinfoDict[devID][self._MIC_ACTIVE_CORES])

    def mic_memory_size(self):
        """
        get the memory size of the MIC device pointed by the device index,
        depending on the architecture memory may be GDDR or MCDRAM
        """
        devID = self.get_device_name()
        size, units = tuple(self._micinfoDict[devID][self._MIC_MEMORY_SIZE].split())
        return self._convert_to_xbytes(size, units, self._BYTES)

    def mic_stepping(self):
        """get stepping of the device pointed by the device index"""
        devID = self.get_device_name()
        try:
            result = self._micinfoDict[devID][self._MIC_STEPPING]
        except KeyError:
            result = 'NotAvailble'
        return result

    def mic_sku(self):
        """get sku of the device pointed by the device index"""
        devID = self.get_device_name()
        try:
            result = self._micinfoDict[devID][self._MIC_SKU]
        except KeyError:
            result = 'NotAvailable'
        return result

    def micinfo_basic(self):
        """
        derived classes should provide a proper implementation.
        micinfo_basic() should return a string with basic info
        of the device pointed by the device index.
        """
        raise NotImplemented("Error: abstract method")

    def get_app_list(self):
        """
        returns a dictionary containing the result of the commands
        that micperf ran on the host to determine its configuration.
        See _init_command_dict().
        """
        return sorted(self._commandDict.keys())

    def get_processor_codename(self):
        """Returns codename of Intel(R) Xeon Phi(TM) processor detected
        in the system. Returns None if processor is not supported"""
        devID = self.get_device_name()
        cpu_family = self._micinfoDict[devID][self._MIC_FAMILY]
        model_nr = self._micinfoDict[devID][self._MIC_MODEL]

        # map (family, model):"codename"
        phi_cn_map = {  ('6', '87')     : INTEL_KNL,
                        ('6', '133')    : INTEL_KNM }

        try:
            return phi_cn_map[(cpu_family, model_nr)]
        except KeyError:
            return None

    def system_hw_hash(self, criticalKeys):
        """
        Use some of the most remarkable hardware characteristics (criticalKeys)
        of the card and host to compute a hash that 'represents' the system.
        This method returns such hash as a string.
        """
        micinfoDictStd = copy.deepcopy(self._micinfoDict)

        # Standardize the output so that it is consistent between runs
        nonDecimal = re.compile(r'[^\d.]+')
        for infoDict in micinfoDictStd.values():
            if self._HOST_FAMILY in infoDict:
                # Remove extra white space
                infoDict[self._HOST_FAMILY] = \
                        ' '.join(infoDict[self._HOST_FAMILY].split())

            if self._HOST_CPU_SPEED in infoDict:
                # special case for test systems to avoid sleep state issues
                if infoDict[self._HOST_FAMILY] == 'GenuineIntel Family 6 Model 45 Stepping 7':
                    infoDict[self._HOST_CPU_SPEED] = '2600 MHz'
                else:
                    orig = infoDict[self._HOST_CPU_SPEED]
                    # Get rid of all non-numeric characters
                    mhz = float(nonDecimal.sub('', orig))
                    orig = orig.lower()
                    # Get units into MHz
                    if 'ghz' in orig:
                        mhz = 1000*mhz
                    elif 'khz' in orig:
                        mhz = mhz/1000
                    # Round CPU Speed to the nearest 100 MHz
                    mhz = str(int(round(mhz, -2)))
                    infoDict[self._HOST_CPU_SPEED] = mhz + ' MHz'

            if self._MIC_PCI_WIDTH in infoDict:
                orig = infoDict[self._MIC_PCI_WIDTH]
                # get rid of all non-numeric characters
                chan = nonDecimal.sub('', orig)
                infoDict[self._MIC_PCI_WIDTH] = chan

            if self._MIC_PCI_SPEED in infoDict:
                orig = infoDict[self._MIC_PCI_SPEED]
                # Get rid of all non-numeric characters
                gts = float(nonDecimal.sub('', orig))
                # Round PCIe speed to the nearest GT/s
                gts = str(int(round(gts)))
                infoDict[self._MIC_PCI_SPEED] = gts + ' GT/s'

            if self._MIC_SPEED in infoDict:
                orig = infoDict[self._MIC_SPEED]
                # Get rid of all non-numeric characters
                khz = float(nonDecimal.sub('', orig))
                orig = orig.lower()
                if 'mhz' in orig:
                    khz = 1000*khz
                elif 'ghz' in orig:
                    khz = 1000000*khz
                # Round Frequency to the nearest 100 MHz
                khz = str(int(round(khz, -5)))
                infoDict[self._MIC_SPEED] = khz + ' kHz'

            if self._HOST_PHYSICAL_MEMORY in infoDict:
                infoDict[self._HOST_PHYSICAL_MEMORY] = \
                    self._normalize_memsize(infoDict[self._HOST_PHYSICAL_MEMORY])

            if self._MIC_MEMORY_SIZE in infoDict:
                infoDict[self._MIC_MEMORY_SIZE] = \
                        self._normalize_memsize(infoDict[self._MIC_MEMORY_SIZE])

        everythingStr = ':'.join(
                            [':'.join([criticalKey + '=' + micinfoDictStd[devID][criticalKey]
                                for criticalKey in criticalKeys
                                if criticalKey in micinfoDictStd[devID]])
                                for devID in sorted(micinfoDictStd.keys())
                            ]
                        )
        hasher = hashlib.md5()
        hasher.update(everythingStr)
        md5hash = hasher.hexdigest()
        return md5hash[:8]

    def _normalize_memsize(self, orig):
        """
        auxiliary method used by system_hw_hash() to convert from kilobytes
        or gigabytes to megabytes (and round the result to 3 digits).
        This needs to be done so the hashes produced by system_hw_hash()
        are reliable among different systems e.g. a 1999 MB memory or a
        2001 MB memory should be seen as a 2GB memory.
        """
        nonDecimal = re.compile(r'[^\d.]+')
        # Get rid of all non-numeric characters
        mb = float(nonDecimal.sub('', orig))
        orig_lower = orig.lower()
        if 'kb' in orig_lower:
            mb = mb/1000
        elif 'gb' in orig_lower:
            mb = 1000*mb
        # Round Size to the nearest GB
        mb = str(int(round(mb, -3)))
        return mb + ' MB'

    def micperf_version(self):
        """
        derived classes should provide a proper implementation
        """
        raise NotImplemented("Error: abstract method")

    def _get_command_list(self):
        """
        returns a list of commands that should be run on the
        host to determine the system configuration
        """
        if micp_common.is_platform_windows():
            commands = ['set',
                        'systeminfo']
        else:
            commands = ['dmidecode -t bios',
                        'dmidecode -t system',
                        'dmidecode -t baseboard',
                        'dmidecode -t chassis',
                        'dmidecode -t processor',
                        'dmidecode -t memory',
                        'dmidecode -t cache',
                        'dmidecode -t connector',
                        'dmidecode -t slot',
                        'uname --kernel-name',
                        'uname --nodename',
                        'uname --kernel-release',
                        'uname --kernel-version',
                        'uname --machine',
                        'uname --processor',
                        'uname --hardware-platform',
                        'uname --operating-system',
                        'lspci -mmvvkD',
                        'env',
                        'numactl --hardware',
                        'cat /proc/cmdline']
        return commands

    def _init_command_dict(self):
        """
        runs a set the commands on the host to determine the system
        configuration.
        """
        self._commandDict = {}
        missing_commands = set()
        for cmd in self._get_command_list():
            try:
                pid = subprocess.Popen(shlex.split(cmd),
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       bufsize=-1,
                                       shell=micp_common.is_platform_windows())
                out, err = pid.communicate()
                self._commandDict[cmd] = '\n'.join((out, err))
            except OSError:
                if cmd.startswith('lspci'):
                    try:
                        cmd = '/sbin/' + cmd
                        pid = subprocess.Popen(shlex.split(cmd),
                                               stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE,
                                               bufsize=-1)
                        out, err = pid.communicate()
                        self._commandDict[cmd] = '\n'.join((out, err))
                    except OSError:
                        sys.stderr.write('WARNING: '
                            'Could not find lspci in path, '
                            'and it is not located in /sbin/lspci.\n')
                        self._commandDict[cmd] = ''
                elif cmd.startswith('/'):
                    try:
                        cmdList = shlex.split(cmd)
                        origPath = cmdList[0]
                        cmdList[0] = os.path.basename(origPath)
                        cmd = ' '.join(cmdList)
                        pid = subprocess.Popen(cmdList,
                                               stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE,
                                               bufsize=-1)
                        out, err = pid.communicate()
                        self._commandDict[cmd] = '\n'.join((out, err))
                    except OSError:
                        warning_msg = 'WARNING: Could not find {0} or {1}.\n'
                        sys.stderr.write(warning_msg.format(origPath, cmdList[0]))
                        self._commandDict[cmd] = ''
                elif cmd == 'set':
                    self._commandDict[cmd] = '\n'.join(
                                sorted(['{0}={1}'.format(var, val)
                                for (var, val)
                                in zip(os.environ.keys(), os.environ.values())])
                            )
                elif cmd.startswith('type '):
                    try:
                        self._commandDict[cmd] = open(cmd[5:]).read()
                    except (IOError, IndexError):
                        self._commandDict[cmd] = ''
                else:
                    self._commandDict[cmd] = ''
                    command = cmd.split()[0]

                    # print warning message only once per missing command
                    if command not in missing_commands:
                        sys.stderr.write('WARNING: Could not find {0}.\n'.format(command))
                        missing_commands.add(command)

    def _init_micinfo_dict(self):
        """
        initializes the dictionary that contains the system configuration
        """
        raise NotImplemented("Error: abstract method")

    def  _get_num_cores_from_cpuinfo(self, devIdx):
        """
        linux only
        get the number of cores of the system from the sysfs
        """
        connect = micp_connect.MPSSConnect(devIdx)
        pid = connect.Popen(micp_common.READ_CPUINFO_PROCFS)
        cpuinfo, err = pid.communicate()
        lineExpr = re.compile(r'core id\s*:\s+\d+')
        allLines = lineExpr.findall(cpuinfo)
        result = len(set([ll.split()[-1] for ll in allLines]))
        if result == 0:
            raise RuntimeError('No mic cores found')
        return result

    def  _get_cpu_mhz_from_cpuinfo(self, devIdx):
        """
        linux only
        get the CPU speed from the sysfs
        """
        connect = micp_connect.MPSSConnect(devIdx)
        pid = connect.Popen(micp_common.READ_CPUINFO_PROCFS)
        cpuinfo, err = pid.communicate()
        lineExpr = re.compile(r'cpu MHz\s*:\s+[\d.]+')
        allLines = lineExpr.findall(cpuinfo)
        result = str(max([float(line.split(':')[1]) for line in allLines]))
        return result

    def  _get_memory_size_from_meminfo(self, devIdx):
        """
        linux only
        get the memory size from the sysfs
        """
        connect = micp_connect.MPSSConnect(devIdx)
        pid = connect.Popen(micp_common.READ_MEMINFO_PROCFS)
        meminfo, err = pid.communicate()
        memDict = dict(
              [tuple([keyValue.strip() for keyValue in line.strip().split(':')])
               for line in meminfo.splitlines()
               if line.find(':') != -1 and line.find(':') == line.rfind(':')]
              )
        value, units = tuple(memDict['MemTotal'].split())
        return self._convert_to_xbytes(value, units, self._BYTES)

    def _get_cpu_family_from_cpuinfo(self, devIdx):
        """
        linux only
        get the CPU family from the sysfs
        """
        connect = micp_connect.MPSSConnect(devIdx)
        pid = connect.Popen(micp_common.READ_CPUINFO_PROCFS)
        cpuinfo, err = pid.communicate()

        vendorID = self._get_field_from_cpuinfo_output(r'vendor_id', cpuinfo)
        cpuFamily = self._get_field_from_cpuinfo_output(r'cpu family', cpuinfo)
        model = self._get_field_from_cpuinfo_output(r'model', cpuinfo)
        stepping = self._get_field_from_cpuinfo_output(r'stepping', cpuinfo)

        result = '{0} Family {1} Model {2} Stepping {3}'
        return result.format(vendorID, cpuFamily, model, stepping)

    def _get_field_from_cpuinfo_output(self, field, cpuinfo):
        """
        only linux
        receives a string 'field' that contains the name of a field in the
        variable 'cpuinfo' (output of 'cat /proc/cpuinfo'), creates a regex
        using such string and returns the first match in 'cpuinfo'
        """
        line_expr = re.compile(r'{0}\s*:.*\n'.format(field))
        all_lines = line_expr.findall(cpuinfo)
        requested_data = [line.split(':')[1].strip() for line in all_lines]
        if len(set(requested_data)) > 1:
            warning_msg = ('WARNING: multiple \'{0}\' values listed in '
                           '/proc/cpuinfo, using only {1}\n')
            sys.stderr.write(warning_msg.format(field, requested_data[0]))
        return requested_data[0]

    def _convert_to_xbytes(self, value, units, new_units):
        """
        converts between multiples of bytes e.g. 2000 bytes to megabytes:
          input:  _convert_to_xbytes(2000, b, _MBYTES)
          output: 2

        Values for new_units: _BYTES, _MBYTES
        """
        to_mbytes = {'b':1.0/(1024**2) , 'kb':1.0/1024 , 'mb':1 , 'gb':1024}
        to_bytes  = {'b':1 , 'kb':1024 , 'mb':1024**2 , 'gb':1024**3}
        convertion_factors = {}
        convertion_factors[self._BYTES] = to_bytes
        convertion_factors[self._MBYTES] = to_mbytes

        try:
            factor = convertion_factors[new_units.lower()][units.lower()]
        except KeyError:
            error_msg = 'Error: cannot convert \'{0} {1}\' to {2}'
            raise NameError(error_msg.format(value, units, new_units))
        return int(round(float(value)*factor))

    def _num_mics_pci(self):
        """alternative method to get the number of mics in case micinfo
        is not installed"""
        if micp_common.is_platform_windows():
            error_message = ('Unable to identify cards, please make'
                             ' sure micinfo is installed.')
            raise micp_common.WindowsMicInfoError()

        __, num_cards = micp_common.num_mics_pci()
        return num_cards

    def is_same_sku(self, other):
        """method used by micperf-pt"""
        deprecationDict = {'B1QS-7110 P/A': 'B1QS-7110 P/A/X',
                           'C0-3120P/3120A': 'C0-3120 P/A',
                           'C0-5110P/5120D': 'C0-5110P',
                           'C0-7120P/7120X/7120': 'C0-7120 P/A/X/D'}
        mySku = deprecationDict.get(self.mic_sku(), self.mic_sku())
        mySku = mySku.replace('QS', '')
        mySku = mySku.replace('PRQ', '')

        otherSku = deprecationDict.get(other.mic_sku(), other.mic_sku())
        otherSku = otherSku.replace('QS', '')
        otherSku = otherSku.replace('PRQ', '')
        return mySku == otherSku

    def is_same_hw(self, other):
        """method used by micperf-pt"""
        return self.system_hw_hash() == other.system_hw_hash()

    def is_lower_mpss_version(self, other):
        """method used by micperf-pt"""
        if distutils.version.LooseVersion(self.mpss_version()) < other.mpss_version():
            return True
        else:
            return False

class InfoKNXLB(InfoKNXXB):
    """
    This class stores all the information related to a KNX Coprocessor
    configuration. See InfoKNXXB class definition for further details.
    """

    # mandatory constants (see InfoKNXXB)
    _MIC_MEMORY_SIZE = 'GDDR Size'
    _MIC_FAMILY = 'Coprocessor Family'
    _MIC_VENDOR_ID = 'Vendor ID'
    _MIC_MODEL = 'Coprocessor Model'
    _MIC_STEPPING = 'Coprocessor Stepping'
    _MIC_SOFTWARE_VERSION = 'MPSS Version'
    _MIC_SPEED = 'Frequency'

    # additional info only for KNX Coprocessors
    _MIC_MEMORY_VENDOR = 'GDDR Vendor'
    _MIC_MEMORY_SPEED = 'GDDR Speed'
    _MPSS_DEFAULT_VERSION = '4.0'
    _HOST = 'host'

    def __init__(self, devIdx=0):
        """Initialize mandatory members, see InfoKNXXB class definition."""
        self._devIdx = devIdx
        self._init_command_dict()
        self._init_micinfo_dict()

    def get_device_name(self):
        """
        returns 'micN' if device index points to card N
        returns 'localhost' if device index points to -1
        """
        if self._devIdx == -1:
            return 'localhost'
        else:
            return 'mic{0}'.format(self.get_device_index())

    def set_device_name(self, name):
        """
        valid names:
          - 'micN' where N is number of the card
          - 'localhost'
        """
        if name == 'localhost':
            self._devIdx = -1
        elif name.startswith('mic'):
            self._devIdx = int(name[3:])
        else:
            raise NameError('Unknown device name {0}'.format(name))

    def micinfo_basic(self):
        """
        returns the following string:
          Core Freq: <speed>
          Mem Speed: <memory speed>
          Board SKU: <stepping> <sku>*

        *only if available
        on failure returns an empty string
        """
        devID = self.get_device_name()
        result = 'Core Freq: {0}\nMem Speed: {1}\nBoard SKU: {2} {3}'
        try:
            result = result.format(self._micinfoDict[devID][self._MIC_SPEED],
                               self._micinfoDict[devID][self._MIC_MEMORY_SPEED],
                               self.mic_stepping(),
                               self._micinfoDict[devID].get(self._MIC_SKU, ''))
        except KeyError:
            result = ''
        return result

    def system_hw_hash(self):
        """
        Use some of the most remarkable hardware specs of a KNC card
        and the host to compute a hash that 'represents' the system.
        The hash is computed by the base class.
        """
        criticalKeys = [self._HOST_PHYSICAL_MEMORY,
                        self._HOST_FAMILY,
                        self._HOST_CPU_SPEED,
                        self._MIC_VENDOR_ID,
                        self._MIC_DEVICE_ID,
                        self._MIC_SUBSYSTEM_ID,
                        self._MIC_STEPPING_ID,
                        self._MIC_PCI_WIDTH,
                        self._MIC_PCI_SPEED,
                        self._MIC_PCI_MAX_PAYLOAD,
                        self._MIC_MODEL,
                        self._MIC_MODEL_EXT,
                        self._MIC_TYPE,
                        self._MIC_FAMILY,
                        self._MIC_FAMILY_EXT,
                        self._MIC_ACTIVE_CORES,
                        self._MIC_SPEED,
                        self._MIC_MEMORY_VENDOR,
                        self._MIC_MEMORY_SIZE,
                        self._MIC_MEMORY_SPEED]

        return super(InfoKNXLB, self).system_hw_hash(criticalKeys)

    def mpss_version(self):
        """
        get the MPSS version

        DO NOT USE. This method is only for backward compatibility
        with KNC micperf use micperf_version() instead.
        """
        return self.micp_version()

    def micperf_version(self):
        """
        for KNX coprocessors the version matches the MPSS version
        """
        return self._micinfoDict[self._HOST][self._MIC_SOFTWARE_VERSION]

    def _get_command_list(self):
        """
        returns a list of commands (OS dependant) that InfoKNXSB
        uses to intialize the _commandDict dictonary
        see InfoKNXXB class definition.

        Internally calls _get_command_list() provided by the base InfoKNXXB
        """
        commands = super(InfoKNXLB, self)._get_command_list()
        commands.append('micinfo')

        if not micp_common.is_platform_windows():
            commands.extend(['micsmc-cli show-data --freq',
                             'micsmc-cli show-data --info',
                             'micsmc-cli show-data --mem',
                             'micsmc-cli show-data --temp',
                             'rpm -qa intel-mic\\* '])

            fileName = '/etc/mpss/mic{0}.conf'
            confFiles = ['/etc/modprobe.d/mic.conf',
                         '/etc/mpss/default.conf']
            index = 0
            while os.path.exists(fileName.format(index)):
                confFiles.append(fileName.format(index))
                index = index + 1
            commands.extend(['egrep -v "^[ \t]*$|^#" {0}'.format(cf)
                                   for cf in confFiles])
        return commands

    def _get_micinfo_canonicalized_output(self):
        """returns standardized KNX micinfo output, this is required since
        different version of micinfo print some fields differently"""

        output = self.__str__('micinfo')
        output = output.replace('MIC Processor', 'Coprocessor')
        output = output.replace('MIC Silicon', 'Coprocessor')
        output = output.replace('MIC Board', 'Coprocessor')
        output = output.replace('coprocessor', 'Coprocessor')
        output = output.replace('PCie Max payload size', self._MIC_PCI_MAX_PAYLOAD)
        output = output.replace('PCie Max read req size', self._MIC_PCI_MAX_READ)
        output = output.replace('Subsystem ID', self._MIC_SUBSYSTEM_ID)

        # To keep backward compatibility with KNC micperf 'GDDR'
        # will be use to replace both 'DRAM' and 'MCDRAM'
        # IMPORTANT: order matters first replace instances of MCDRAM
        output = output.replace('MCDRAM', 'GDDR')
        output = output.replace('DRAM', 'GDDR')

        return output

    def _init_micinfo_dict(self):
        """
        Use micinfo* to initialize _micinfoDict, this dictionary contains
        at least two dictionaries:
          - _HOST: information related to the host OS name, MPSS version, etc.
          - mic0: information related to mic0 e.g. cores, memory size, sku, etc.

        If there's more than one card installed, _micinfoDict will contain a
        'micN' dictionary per card.

        *If micinfo is not available _init_micinfo_dict() will use alternate
        sources to get the information required by micperf.
        """
        self._micinfoDict = {}

        micinfo_output = self._get_micinfo_canonicalized_output()
        micInfo = micinfo_output.split('Device No:')

        # if micinfo is not available use 'lspci' to look for micN devices
        numDevices = len(micInfo) - 1
        if numDevices == 0:
            numDevices = self._num_mics_pci()
            micInfo = ['']*(numDevices+1)

        infoDict = {}
        # on windows get host information from micinfo
        if micp_common.is_platform_windows():
            infoDict = dict([tuple([keyValue.strip() for keyValue in line.strip().split(':')])
                             for line in micInfo[0].splitlines()
                             if line.find(':') != -1 and line.find(':') == line.rfind(':')])
            if self._MIC_SOFTWARE_VERSION not in infoDict:
                warning_msg = 'WARNING:  Unknown MPSS Version, setting to {0}\n'
                sys.stderr.write(warning_msg.format(self._MPSS_DEFAULT_VERSION))
                infoDict[self._MIC_SOFTWARE_VERSION] = self._MPSS_DEFAULT_VERSION
        # otherwise use standard linux routines for host information
        else:
            infoDict[self._HOST_OS_NAME] = platform.uname()[0]
            infoDict[self._HOST_OS_VERSION] = platform.uname()[2]
            infoDict[self._MIC_SOFTWARE_VERSION] = self._get_mpss_version_from_rpm()
            infoDict[self._HOST_PHYSICAL_MEMORY] = \
                    str(self._get_memory_size_from_meminfo(-1)/(1024**2)) + ' MB'
            infoDict[self._HOST_FAMILY] = self._get_cpu_family_from_cpuinfo(-1)
            infoDict[self._HOST_CPU_SPEED] = str(self._get_cpu_mhz_from_cpuinfo(-1))
        self._micinfoDict[self._HOST] = infoDict

        # verify if micinfo provides all the information required by micperf
        # if micinfo is not available or doesn't provide the information required
        # use alternative sources
        nonDecimal = re.compile(r'[^\d.]+')
        for devIdx in range(numDevices):
            infoDict = dict(
                [tuple([keyValue.strip() for keyValue in line.strip().split(':')])
                 for line in micInfo[devIdx+1].splitlines()
                 if line.find(':') != -1 and line.find(':') == line.rfind(':')])

            # remove leading '0x' from some fields
            prefixed_values = (self._MIC_VENDOR_ID,
                               self._MIC_DEVICE_ID,
                               self._MIC_SUBSYSTEM_ID)
            for field in prefixed_values:
                if (field in infoDict and infoDict[field].startswith('0x')):
                    infoDict[field] = infoDict[field][2:]

            # if micinfo is not available use the sysfs to get the number of active
            if (self._MIC_ACTIVE_CORES not in infoDict or
                nonDecimal.sub('', infoDict[self._MIC_ACTIVE_CORES]) == ''):
                infoDict[self._MIC_ACTIVE_CORES] = \
                        str(self._get_num_cores_from_cpuinfo(devIdx))

            # if micinfo is not available use the sysfs to the GDDR memory size
            if (self._MIC_MEMORY_SIZE not in infoDict or
                 nonDecimal.sub('', infoDict[self._MIC_MEMORY_SIZE]) == ''):
                infoDict[self._MIC_MEMORY_SIZE] = \
                    str(self._get_memory_size_from_meminfo(devIdx)/(1024**2)) + ' MB'

            if self._MIC_MEMORY_VENDOR in infoDict:
                # Make sure Hynix is not HYNIX
                if infoDict[self._MIC_MEMORY_VENDOR] == 'HYNIX':
                    infoDict[self._MIC_MEMORY_VENDOR] = 'Hynix'

            if (self._MIC_PCI_WIDTH not in infoDict or
                nonDecimal.sub('', infoDict[self._MIC_PCI_WIDTH]) == ''):
                infoDict[self._MIC_PCI_WIDTH] = '16'

            if (self._MIC_PCI_SPEED not in infoDict or
                 nonDecimal.sub('', infoDict[self._MIC_PCI_SPEED]) == ''):
                infoDict[self._MIC_PCI_SPEED] = '5 GT/s'

            if (self._MIC_PCI_MAX_PAYLOAD not in infoDict or
                nonDecimal.sub('', infoDict[self._MIC_PCI_MAX_PAYLOAD]) == ''):
                if self.micperf_version().startswith('2.0'):
                    infoDict[self._MIC_PCI_MAX_PAYLOAD] = '64 bytes'
                else:
                    infoDict[self._MIC_PCI_MAX_PAYLOAD] = '256 bytes'

            if (self._MIC_PCI_MAX_READ not in infoDict or
                nonDecimal.sub('', infoDict[self._MIC_PCI_MAX_READ]) == ''):
                if self.micperf_version().startswith('2.0'):
                    infoDict[self._MIC_PCI_MAX_READ] = '128 bytes'
                else:
                    infoDict[self._MIC_PCI_MAX_READ] = '512 bytes'

            self._micinfoDict['mic{0}'.format(devIdx)] = infoDict

    def _get_mpss_version_from_rpm(self):
        """
        try to use the MPSS' rpms to determine the version of MPSS
        on failure return _MPSS_DEFAULT_VERSION
        """
        result = None
        cmdList = ["rpm -qa --queryformat '%{version}' mpss-release",
                   "rpm -qa --queryformat '%{version}' mpss-daemon",
                   "rpm -qa --queryformat '%{version}' mpss-micperf"]

        for cmd in cmdList:
            pid = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, shell=True)
            out, err = pid.communicate()
            if pid.returncode == 0 and out.strip():
                return out.strip()

        warning_msg = ("WARNING: unable to determine "
                      "MPSS version from installed RPM's, setting to {0}\n")
        sys.stderr.write(warning_msg.format(self._MPSS_DEFAULT_VERSION))
        return self._MPSS_DEFAULT_VERSION

    def gddr_size(self):
        """
        DO NOT USE. This method is only for backward compatibility
        with KNC micperf use mic_memory_size() instead
        """
        return self.mic_memory_size()

    def get_ddr_memory_size(self):
        """Coprocessor does not have any DDR memory available"""
        return 0


class InfoKNXSB(InfoKNXXB):
    """
    This class stores all the information related to a KNL
    Processor configuration running linux.
    See InfoKNXXB class definition for further details.
    """

    # mandatory constants (see InfoKNXXB)
    _MIC_FAMILY = 'CPU Family'
    _MIC_VENDOR_ID = 'Vendor ID'
    _MIC_MODEL = 'CPU Model'
    _MIC_STEPPING = 'CPU Stepping'
    _MIC_MEMORY_SIZE = 'MCDRAM Size'
    _MIC_SOFTWARE_VERSION = 'micperf Version'
    _MIC_SPEED = 'CPU Speed'

    # additional constants for KNL Processors only
    _MIC_MODEL_NAME = 'CPU Model Name'
    _SB_HOST = 'selfboot'
    _SYSFS_NUMA_BASE_PATH = '/sys/devices/system/node/'

    def __init__(self, devIdx=-1):
        """Initialize mandatory members, see InfoKNXXB class definition."""
        self._devIdx = devIdx
        self._is_mcdram_available = False
        self._devIP = {}
        self._init_command_dict()

        self._nodes_with_cpus = 0
        self._count_nodes_with_cpus()

        if micp_common.is_platform_windows():
            self._windows_init_micinfo_dict()
        else:
            self._linux_init_micinfo_dict()


    def get_device_name(self):
        """returns the default SB device _SB_HOST, see set_device_name()"""
        return self._SB_HOST

    def set_device_name(self, name):
        """
        only for compatibility, internally there's a
        single KNL Processor device defined by _SB_HOST
        """
        pass

    def mic_sku(self):
        """Returns the Intel(R) Xeon Phi(TM) SKU (Family 7200)."""
        host_id = self.get_device_name()
        sku = re.search('(72\d\d)', self._micinfoDict[host_id][self._MIC_MODEL_NAME])

        if sku:
            return sku.group()
        return "NotAvailable"

    def micinfo_basic(self):
        """
        returns the following string:
          Core Freq: <speed>
          Board SKU: <stepping>

        On failure returns an empty string
        """
        devID = self.get_device_name()
        result = 'Core Freq: {0}\nBoard SKU: {1}'
        try:
            result = result.format(self._micinfoDict[devID][self._MIC_SPEED],
                                   self.mic_stepping())
        except KeyError:
            result = ''
        return result

    def micperf_version(self):
        """
        for KNL Processors the version matches the lates MPSS release
        """
        device =  self.get_device_name()
        return self._micinfoDict[device][self._MIC_SOFTWARE_VERSION]

    def system_hw_hash(self):
        """
        Use some of the most remarkable hardware specs of a KNL
        Processor to compute a hash that 'represents' the system.
        The hash is computed by the base class.
        """
        criticalKeys = [self._MIC_FAMILY,
                        self._MIC_VENDOR_ID,
                        self._MIC_MODEL,
                        self._MIC_MODEL_NAME,
                        self._MIC_STEPPING,
                        self._MIC_SPEED,
                        self._MIC_ACTIVE_CORES,
                        self._MIC_MEMORY_SIZE]
        return super(InfoKNXSB, self).system_hw_hash(criticalKeys)


    @staticmethod
    def _raw_wmic_query(component, properties):
        """Run a wmic query and return output in a list (only non-empty lines)"""
        wmic_query = r'wmic {0} get {1} /FORMAT:CSV'
        wmic_query = wmic_query.format(component, properties)
        local_shell = micp_connect.LocalConnect()

        pid = local_shell.Popen(wmic_query)
        stdout, stderr = pid.communicate()

        if pid.returncode:
            raise ValueError(stderr)

        stdout = stdout.strip()
        return [line for line in stdout.splitlines() if line.strip()]


    @staticmethod
    def _windows_is_ddr_memory(formfactor, memorytype, locator):
        """auxiliary method to determine if given memory specs correspond to a
        DDR memory"""

        # constants are defined based on Win32_PhysicalMemory documentation
        _MCDRAM_LOCATOR = 'mcdram'
        _FLAT_MCDRAM_TYPE = '3'
        _CACHE_MCDRAM_TYPE = '1'
        _MCDRAM_FORMFACTOR = '0'

        # if any of the following conditions is true memory is not MCDRAM
        # check is redudant to deal with custom BIOS'es
        not_mcdram_locator = _MCDRAM_LOCATOR not in locator.lower()
        not_mcdram_type = memorytype != _FLAT_MCDRAM_TYPE and memorytype != _CACHE_MCDRAM_TYPE
        not_mcdram_form_factor = formfactor != _MCDRAM_FORMFACTOR

        return not_mcdram_locator or not_mcdram_type or not_mcdram_form_factor


    def _win_get_size_ddr_memory(self):
        """use wmic to get the size of the DDR memory available, result in megabytes """

        # Memory information comes from Win32_PhysicalMemory which is populated
        # with information from the SMBIOS table 17. size is given in bytes
        # according to documentation.

        raw_output = self._raw_wmic_query('memorychip', 'Capacity,DeviceLocator,FormFactor,SMBIOSMemoryType')

        # ignore first line (column titles)
        all_memories_info = raw_output[1:]

        total_size = 0
        for memory_info in all_memories_info:
            __, size, locator, formfactor, memorytype = memory_info.split(',')
            if self._windows_is_ddr_memory(formfactor, memorytype, locator) and size:
                total_size += int(size)

        total_size = total_size / 1024**2
        return '{0} MB'.format(total_size)


    def _win_get_size_mcdram_memory(self):
        """use a wmic query to get the size of (flat) MCDRAM memory available,
        return size in megabytes"""

        # wmic info comes frow Win32_PhysicalMemoryArray which in turn comes from
        # SMBIOS table 16, following constants serve to identify flat MCDRAM memory.
        # Size is given in kilobytes according to documentation.
        _MCDRAM_LOCATION = '1'
        _FLAT_MCDRAM_USE = '3'

        raw_output = self._raw_wmic_query('memphysical', 'Location,MaxCapacityEx,Use')

        # ignore first line (colum names)
        all_memory_info = raw_output[1:]

        total_size = 0
        for memory_info in all_memory_info:
            # line format: Node, Location, MaxCapacityEx, Use
            __, location, max_capacity_ex, use = memory_info.split(',')

            if use == _FLAT_MCDRAM_USE and location == _MCDRAM_LOCATION:
                max_capacity_ex = int(max_capacity_ex)
                if max_capacity_ex:
                    total_size += max_capacity_ex

        if total_size:
            self._is_mcdram_available = True
            total_size = total_size / 1024
            return '{0} MB'.format(total_size)

        # this point is reached only if no MCDRAM memory is available
        raise ValueError('NO Flat MCDRAM Found!')


    def _win_get_num_physical_cores(self):
        """returns number of physical cores"""
        raw_output = self._raw_wmic_query('cpu', 'NumberOfCores,NumberOfLogicalProcessors')

        # ignore header (colum names)
        raw_output = raw_output[1:]

        total_cores = 0
        total_logical_processors = 0
        for line in raw_output:
            if line:
                # line format: node, cores
                __, _cores, _logical_processors = line.split(',')
                total_cores += int(_cores)
                total_logical_processors += int(_logical_processors)

        # for Xeon Phi there are 4 treads per core
        is_hyper_threading_enabled = total_logical_processors > total_cores
        if is_hyper_threading_enabled:
            return total_logical_processors / 4
        return total_logical_processors


    def _win_get_vendor_id(self):
        """get CPU vendor ID"""
        raw_output = self._raw_wmic_query('cpu', 'manufacturer')

        # try to return vendor ID of the first CPU (element 0 is the column name)
        try:
            __, vendor = raw_output[1].split(',')
            return vendor
        except IndexError:
            return 'Unknown'


    def _win_get_cpu_freq(self):
        """get CPU frequency"""
        raw_output = self._raw_wmic_query('cpu', 'name')

        # check only CPU 0
        cpu0_name = raw_output[1]

        # expected string 'Intel(R) Genuine Intel(R) CPU XXXX @ X.XXHz'
        try:
            __, raw_freq = cpu0_name.split('@')
        except IndexError, ValueError:
            return 'Unknown'

        freq = re.match('[\d.]+', raw_freq.strip())
        if freq:
            return freq.group()
        return 'Unknown'


    def _win_get_cpu_sku(self):
        """return CPU SKU"""
        raw_output = self._raw_wmic_query('cpu', 'name')

        # check only CPU 0
        # expected string 'Intel(R) Genuine Intel(R) CPU XXXX @ X.XXHz'
        cpu0_name = raw_output[1]

        # Xeon Phi belongs to the Family 7200
        sku = re.search('72\d\d', cpu0_name)

        if sku:
            return sku.group()
        return 'NotAvailable'


    def _win_get_cpu_stepping(self):
        """return CPU stepping"""
        raw_output = self._raw_wmic_query('cpu', 'description')

        # check only CPU 0
        # expected string 'Intel(R) Genuine Intel(R) CPU XXXX @ X.XXHz'
        cpu0_description = raw_output[1]

        # expected description: Intel64 Family 6 Model 87 Stepping X
        stepping = re.search('stepping\s+(\d+)', cpu0_description, re.I)

        if stepping:
            return stepping.groups()[0]
        return 'NotAvailable'


    def _windows_init_micinfo_dict(self):
        """ """
        self._micinfoDict = {}
        infoDict = {}
        local_shell = micp_connect.MPSSConnect(self._devIdx)

        # os information
        infoDict[self._HOST_OS_NAME] = platform.system()
        infoDict[self._HOST_OS_VERSION] = platform.version()
        infoDict[self._MIC_SOFTWARE_VERSION] = micp_version.__version__

        # family and model are always the same for the Xeon Phi Processor
        infoDict[self._MIC_FAMILY] = micp_common.XEON_PHI_PROCESSOR_FAMILY
        infoDict[self._MIC_MODEL] = micp_common.XEON_PHI_PROCESSOR_MODEL

        infoDict[self._MIC_VENDOR_ID] = self._win_get_vendor_id()
        infoDict[self._MIC_MODEL_NAME] = self._win_get_cpu_sku()
        infoDict[self._MIC_STEPPING] = self._win_get_cpu_stepping()

        infoDict[self._MIC_SPEED] = self._win_get_cpu_freq()
        infoDict[self._HOST_PHYSICAL_MEMORY] = self._win_get_size_ddr_memory()
        infoDict[self._MIC_ACTIVE_CORES] = self._win_get_num_physical_cores()

        try:
            infoDict[self._MIC_MEMORY_SIZE] = self._win_get_size_mcdram_memory()
        except ValueError as err:
            print str(err)
            infoDict[self._MIC_MEMORY_SIZE] = infoDict[self._HOST_PHYSICAL_MEMORY]

        self._micinfoDict[self.get_device_name()] = infoDict


    def _linux_init_micinfo_dict(self):
        """
        Initialize _micinfoDict, this dictionary contains another dictionary
        '_SB_HOST' where the system information required by micperf is stored.
        """
        self._micinfoDict = {}
        infoDict = {}
        connect = micp_connect.MPSSConnect(self._devIdx)

        # gather OS info
        pid = connect.Popen('uname -o')
        os_name, __ = pid.communicate()
        infoDict[self._HOST_OS_NAME] = os_name.lower()
        pid = connect.Popen('uname -r')
        kernel_version, __ = pid.communicate()
        infoDict[self._HOST_OS_VERSION] = kernel_version.lower()
        infoDict[self._MIC_SOFTWARE_VERSION] = micp_version.__version__

        # gather CPU info
        pid = connect.Popen(micp_common.READ_CPUINFO_PROCFS)
        cpuinfo_output, __ = pid.communicate()
        infoDict[self._MIC_FAMILY] = \
            self._get_field_from_cpuinfo_output(r'cpu family', cpuinfo_output)
        infoDict[self._MIC_VENDOR_ID] = \
            self._get_field_from_cpuinfo_output(r'vendor_id', cpuinfo_output)
        infoDict[self._MIC_MODEL] = \
            self._get_field_from_cpuinfo_output(r'model', cpuinfo_output)
        infoDict[self._MIC_MODEL_NAME] = \
            self._get_field_from_cpuinfo_output(r'model name', cpuinfo_output)
        infoDict[self._MIC_STEPPING] = \
            self._get_field_from_cpuinfo_output(r'stepping', cpuinfo_output)
        infoDict[self._MIC_SPEED] = \
            str(self._get_cpu_mhz_from_cpuinfo(self._devIdx))
        infoDict[self._HOST_PHYSICAL_MEMORY] = \
            str(self._get_memory_size_from_meminfo(self._devIdx)/(1024**2)) + ' MB'
        infoDict[self._MIC_ACTIVE_CORES] = \
            str(self._get_num_cores_from_cpuinfo(self._devIdx))

        # gather MCDRAM info
        try:
            infoDict[self._MIC_MEMORY_SIZE] = str(self._get_mcdram_size(connect)) + ' MB'
        except (OSError, IOError, ValueError) as err:
            if micp_common.is_selfboot_platform():
                mp_print("Unable to find MCDRAM numa nodes:", CAT_INFO)
                mp_print(" - the memkind library may not installed or may be improperly installed,", wrap=False)
                mp_print(" - or MCDRAM may be configured by the BIOS to be used as all Cache", wrap=False)
                mp_print(" - or the Xeon Phi Processor may have NO MCDRAM", wrap=False)
                mp_print("If MCDRAM is configured as Cache, the benchmarks will execute in external DRAM and use MCDRAM as Cache.")
            infoDict[self._MIC_MEMORY_SIZE] = infoDict[self._HOST_PHYSICAL_MEMORY]

        self._micinfoDict[self.get_device_name()] = infoDict


    def _get_mcdram_size(self, connect):
        """
        returns the MCDRAM size in megabytes.

        It assumes memkind is running on the system and uses its
        configuration file to identify high bandwidth nodes.
        """

        # Use memkind's memkind-hbw-nodes to find high bandwidth nodes
        localhost = micp_connect.LocalConnect()
        pid_get_hwb_nodes = localhost.Popen('memkind-hbw-nodes')
        stdout, __ = pid_get_hwb_nodes.communicate()

        hwb_nodes = stdout.rstrip()
        if pid_get_hwb_nodes.returncode or not hwb_nodes:
            raise ValueError()

        # memkind-hbw-nodes returns a comma separated list of high bandwidth nodes
        hwb_nodes = hwb_nodes.split(',')

        # create regex to find numa nodes
        mcdram_nodes_regex = [r'node {0} size\s*:.*\n'.format(node_id)
                              for node_id in hwb_nodes]
        mcdram_nodes_regex = re.compile(r'|'.join(mcdram_nodes_regex))

        # 'numactl --hardware' shows the size of all the numa nodes in the system
        #  mcdram_nodes_regex is used to filter out non-mcdram nodes.
        try:
            pid = connect.Popen('numactl --hardware')
        except OSError:
            raise OSError('WARNING: numactl may not be installed on this system, unable'
                          ' to determine if MCDRAM is available. Using only DDR memory.')

        numa_nodes, __ = pid.communicate()
        mcdram_nodes = mcdram_nodes_regex.findall(numa_nodes)

        if not mcdram_nodes:
            raise ValueError("INFO: MCDRAM seems to be configured in cache mode,"
                             " MCDRAM memory cannot be explicitly allocated in this mode."
                             " Using only DDR memory.")

        # mdcram_size = mdcram_size_node_1 + ... + mdcram_size_node_n
        mcdram_size = 0
        for node in mcdram_nodes:
            # "node 1 size: 16384 MB"  <- node's size as displayed by numactl
            node_size = node.split(':')[1]
            node_size = node_size.strip()
            value, units = node_size.split()
            mcdram_size += self._convert_to_xbytes(value, units, self._MBYTES)

        self._is_mcdram_available = True
        return mcdram_size


    def is_processor_mcdram_available(self):
        """returns true only when mcdram can be allocated (platform is
        either in flat or hybrid mode)"""
        return self._is_mcdram_available


    def set_use_only_ddr_memory(self, ddr):
        """receives a boolean that indicates whether or not DDR memory should be
        used, this method should be called before creating any kernel object"""
        if ddr and self._is_mcdram_available:
            host_id = self.get_device_name()
            ddr_size = self._micinfoDict[host_id][self._HOST_PHYSICAL_MEMORY]
            self._micinfoDict[host_id][self._MIC_MEMORY_SIZE] = ddr_size
            self._is_mcdram_available = False
            mp_print("Using only DDR memory.", CAT_INFO)


    def _count_nodes_with_cpus(self):
        """count the number of NUMA nodes with CPUs, this help identify the
        cluster mode"""

        # TODO: Add support for windows, using 1 as default is safe for now.
        if micp_common.is_platform_windows():
            self._nodes_with_cpus = 1
            return

        is_valid_node_name = re.compile("node\d+",).match
        nodes_with_cpus = 0
        all_nodes = [node for node in os.listdir(self._SYSFS_NUMA_BASE_PATH)
                     if is_valid_node_name(node)]

        for node in all_nodes:
            with open(os.path.join(self._SYSFS_NUMA_BASE_PATH, node, 'cpulist')) as cpulist:
                cpus = cpulist.readline().strip()
                if cpus:
                    nodes_with_cpus += 1

        if not nodes_with_cpus:
            warning = ('WARNING: Unable to count the number of NUMA nodes with CPUs,'
                       ' assuming there only one node with all the CPUs')
            sys.stderr.write(warning)
            self._nodes_with_cpus = 1
        else:
            self._nodes_with_cpus = nodes_with_cpus


    def is_in_sub_numa_cluster_mode(self):
        """returns true if cluster mode is SNC2 or SNC4"""

        # Cluster Mode, NUMA nodes with CPUs
        # All2All     , 1
        # Quadrant    , 1
        # SNC2        , 2
        # SNC4        , 4

        return self._nodes_with_cpus > 1

    def get_hbw_nodes(self):
        """returns comma separated list of HBW nodes if they exist,
        empty string otherwise; note: the function uses memkind"""

        localhost = micp_connect.LocalConnect()
        pid_get_hwb_nodes = localhost.Popen('memkind-hbw-nodes')
        stdout, __ = pid_get_hwb_nodes.communicate()

        hwb_nodes = stdout.rstrip()
        if pid_get_hwb_nodes.returncode or not hwb_nodes:
            return ''
        else:
            return hwb_nodes

    def get_number_of_nodes_with_cpus(self):
        """returns the number of NUMA nodes with CPUs"""
        return self._nodes_with_cpus


    def snc_max_threads_per_quadrant(self):
        """returns the maximum number of threads (1 thread per core) that can
        be scheduled to run in a given quadrant or hemisphere (SNC4 and SNC2
        respectively) to get the best performance. Threads should be set using
        the environment variable KMP_HW_SUBSET=Nc,1t where N is the number of
        threads"""

        cores = self.num_cores()
        cpu_numa_nodes = self.get_number_of_nodes_with_cpus()

        # Intel(R) Xeon phi processor SKU 7290 can accommodate additional threads:
        # 4 in SNC2 cluster mode and 2 in SNC4 cluster mode.
        if cpu_numa_nodes == SNC2_CPU_NUMA_NODES:
            max_threads = MAX_THREADS_SNC2+4 if cores == 72 else MAX_THREADS_SNC2
        elif cpu_numa_nodes == SNC4_CPU_NUMA_NODES:
            max_threads = MAX_THREADS_SNC4+2 if cores == 72 else MAX_THREADS_SNC4
        else:
            raise ValueError("ERROR: System doesn't seem to be SNC2 or SNC4 mode")

        return max_threads


    def get_ddr_memory_size(self):
        """returns size of DDR memory available in MB"""
        host_id = self.get_device_name()
        mem_size = self._micinfoDict[host_id][self._HOST_PHYSICAL_MEMORY]
        mem_size, __ = mem_size.split()     # expected string: 'SIZE MB'
        return int(mem_size)


class Borg:
    """Infrastructure to create an Info monostate object"""
    _sharedState = {}
    def __init__(self):
        self.__dict__ = self._sharedState


class Info(InfoKNXLB, Borg):
    """
    This is the only class intended to be used by external modules.

    An instance of Info (monostate object) hides all the specific details about
    the underlying hardware platform while providing a unique interface to
    external modules. Internally Info delegates the actual work to either
    an InfoKNXLB or an InfoKNXSB object.

    Due to compatibility issues with KNC micperf, this class also inherits
    from InfoKNXLB since the Info object should be able to deal with KNC data
    directly.
    """
    def __init__(self, devIdx=0):
        """create an InfoKNXLB or an InfoKNXSB object"""
        Borg.__init__(self)
        if self.__dict__ == {}:
            self._device = InfoKNXSB()

    def __str__(self, categories=None):
        """
        try to use the _device object to perform the action
        on failure delegate task to base class
        """
        try:
            return self._device.__str__(categories)
        except AttributeError:
            return super(Info, self).__str__(categories)

    def get_device_index(self):
        """
        try to use the _device object to perform the action
        on failure delegate task to base class
        """
        try:
            return self._device.get_device_index()
        except AttributeError:
            return super(Info, self).get_device_index()

    def set_device_index(self, devIdx):
        """
        try to use the _device object to perform the action
        on failure delegate task to base class
        """
        try:
            self._device.set_device_index(devIdx)
        except AttributeError:
            super(Info, self).set_device_index(devIdx)

    def get_device_name(self):
        """
        try to use the _device object to perform the action
        on failure delegate task to base class
        """
        try:
            return self._device.get_device_name()
        except AttributeError:
            return super(Info, self).get_device_name()

    def set_device_name(self, name):
        """
        try to use the _device object to perform the action
        on failure delegate task to base class
        """
        try:
            self._device.set_device_name(name)
        except AttributeError:
            return super(Info, self).set_device_name(name)

    def num_cores(self):
        """
        try to use the _device object to perform the action
        on failure delegate task to base class
        """
        try:
            return self._device.num_cores()
        except AttributeError:
            return super(Info, self).num_cores()

    def mic_memory_size(self):
        """
        try to use the _device object to perform the action
        on failure delegate task to base class
        """
        try:
            return self._device.mic_memory_size()
        except AttributeError:
            return super(Info, self).mic_memory_size()

    def mic_stepping(self):
        """
        try to use the _device object to perform the action
        on failure delegate task to base class
        """
        try:
            return self._device.mic_stepping()
        except AttributeError:
            return super(Info, self).mic_stepping()

    def mic_sku(self):
        """
        try to use the _device object to perform the action
        on failure delegate task to base class
        """
        try:
            return self._device.mic_sku()
        except AttributeError:
            return super(Info, self).mic_sku()

    def micinfo_basic(self):
        """
        try to use the _device object to perform the action
        on failure delegate task to base class
        """
        try:
            return self._device.micinfo_basic()
        except AttributeError:
            return super(Info, self).micinfo_basic()

    def get_app_list(self):
        """
        try to use the _device object to perform the action
        on failure delegate task to base class
        """
        try:
            return self._device.get_app_list()
        except AttributeError:
            return super(Info, self).get_app_list()

    def get_processor_codename(self):
        """Returns codename of Intel(R) Xeon Phi(TM) processor detected
        in the system. Returns None if processor is not supported"""
        try:
            return self._device.get_processor_codename()
        except AttributeError:
            return super(Info, self).get_processor_codename()

    def system_hw_hash(self):
        """
        try to use the _device object to perform the action
        on failure delegate task to base class
        """
        try:
            return self._device.system_hw_hash()
        except AttributeError:
            return super(Info, self).system_hw_hash()

    def mpss_version(self):
        """
        DO NOT USE. This method is only for backward compatibility
        with KNC micperf use micperf_version() instead.

        delegate task to base class
        """
        return super(Info, self).mpss_version()

    def micperf_version(self):
        """
        returns the version of the tool as string

        Regardless of the platform (processor or coprocessor) the version
        always matches the version of the latest release of MPSS.
        """
        try:
            return self._device.micperf_version()
        except AttributeError:
            return super(Info, self).micperf_version()

    def is_processor_mcdram_available(self):
        """
        ONLY FOR KNL Processors

        try to use the _device object to perform the action
        on failure delegate task to base class
        """
        try:
            return self._device.is_processor_mcdram_available()
        except AttributeError:
            return False

    def set_use_only_ddr_memory(self, value):
        """
        ONLY FOR KNL Processors

        try to use the _device object to perform the action
        on failure delegate task to base class
        """
        try:
            self._device.set_use_only_ddr_memory(value)
        except AttributeError:
            pass


    def is_in_sub_numa_cluster_mode(self):
        """returns true when CPU is in SNC2 or SNC4 mode

        try to use the _device object to perform the action
        on failure return default value (False)
        """
        try:
            return self._device.is_in_sub_numa_cluster_mode()
        except AttributeError:
            return False

    def get_hbw_nodes(self):
        """returns comma separated list of HBW nodes if they exist,
        empty string otherwise; note: the function uses memkind"""
        try:
            return self._device.get_hbw_nodes()
        except AttributeError:
            return ''

    def get_number_of_nodes_with_cpus(self):
        """returns number of NUMA nodes with CPUs

        try to use the _device object to perform the action
        on failure return default value (1)
        """
        try:
            return self._device.get_number_of_nodes_with_cpus()
        except AttributeError:
            return 1


    def snc_max_threads_per_quadrant(self):
        """returns number of threads required (1 thread per core)
        to saturate CPU in SNC modes.

        try to use the _device object to perform the action
        on failure return number of (CPU) cores.
        """
        try:
            return self._device.snc_max_threads_per_quadrant()
        except AttributeError:
            return self.num_cores()
    def ddr_memory_size(self):
        """returns size of DDR memory available in MB, if information is not
        available returns 0, callers should handle such case"""
        try:
            return self._device.get_ddr_memory_size()
        except AttributeError:
            return 0
