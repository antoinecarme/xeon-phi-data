# Copyright 2012-2017 Intel Corporation.
# 
# This software is supplied under the terms of a license agreement or
# nondisclosure agreement with Intel Corporation and may not be copied
# or disclosed except in accordance with the terms of that agreement.

from collections import OrderedDict
import os
import sys
import struct
from sys_utils import run
import pickle
import ctypes

MSR_PLATFORM_INFO = 206
MSR_IA32_PERF_STATUS = 408
MSR_IA32_PERF_CTL = 409
MSR_FILE_NAME = "/dev/cpu/{0}/msr"
MSR_RATIO_UNIT = 100
PSTATE_DRIVER_FILE = "/sys/devices/system/cpu/intel_pstate"
UNIT_TEST = False
UNIT_TEST_PROCCESORS = 48
CPU_INFO_SO = "cpu-info.so"

class CPUInfoT(ctypes.Structure):
    """
    Class that mimics the C Structure that contains all the CPU Information
    that will be displayed.
    """
    _fields_= [('cpu_id', ctypes.c_uint),
               ('core_id', ctypes.c_uint),
               ('pack_id', ctypes.c_uint),
               ('cpu_freq', ctypes.c_ulonglong),
               ('core_temp', ctypes.c_uint),
               ('pack_temp', ctypes.c_uint),
               ('pack_ener', ctypes.c_double),
               ('ram_ener', ctypes.c_double),
               ('core_ener', ctypes.c_double),
               ('first_cpu_in_package', ctypes.c_ubyte),
               ('first_cpu_in_core', ctypes.c_ubyte)]

class CPUInformation(object):
    """
    Get information from the CPU from a 5 sec interval using cpu-info library.
    This is the information obtained:
        Power consumption   -> Watts consumed by the Package and DRAM, Core consumption not available.
        Temperature         -> Temperature for Core and Package.
        Core frequency      -> Current MHz frequency for each CPU in the system.

    """

    def __init__(self):
        self.cpu_info_so_file = "{0}/{1}".format(os.path.dirname(__file__),CPU_INFO_SO)
        self.cpu_info_lib = ctypes.CDLL(self.cpu_info_so_file)
        self.num_cpus = ctypes.c_uint()
        self.cpus_info = ctypes.POINTER(CPUInfoT)()
        self.summary = CPUInfoT()

    def get_cpu_info_data(self):
        """
        This function calls the get_cpu_info function from the SO library. The
        library function gathers all the information about the CPUs and stores it
        in a dinamically allocated aray of elements, it also provides a summary
        and the number of elements of the array.
        """
        get_cpu_info = self.cpu_info_lib.get_cpu_info
        get_cpu_info.restype = ctypes.c_int
        return get_cpu_info(ctypes.byref(self.num_cpus),
                            ctypes.byref(self.cpus_info),
                            ctypes.byref(self.summary))

    def free_cpu_info_data(self):
        """
        This functions calls the free_cpu_inf function from the SO library. The
        library function frees the memory that was previously allocated in the
        get_cpu_info function.
        """
        free_cpu_info = self.cpu_info_lib.free_cpu_info
        free_cpu_info.restype = ctypes.c_int
        return free_cpu_info(self.cpus_info)

    def show_power_consumption(self):
        """ Summary of the CPU power consumption
        """
        stdout = ""
        stdout += "Power consumption\n"
        stdout += "\tCPU consumption\n"
        stdout += "\t\tWhole package consumption: {0:.2f} Watts\n".format(self.summary.pack_ener)
        if self.summary.core_ener == 0:
            stdout += "\t\tCores consumption: Not Available\n"
        else:
            stdout += "\t\tCores consumption: {0:.2f} Watts\n".format(self.summary.core_ener)
        stdout += "\tRAM consumption {0:.2f} Watts\n".format(self.summary.ram_ener)
        sys.stdout.write(stdout)
        return stdout

    def show_temperature_per_core(self):
        """ Summary of the temperature of the CPU cores
        """
        stdout = ""
        stdout += "Temperature per core\n"
        for i in range(0, self.num_cpus.value):
            if self.cpus_info[i].first_cpu_in_core:
                stdout += "\tCore {0:3}: Temp: {1} Celsius\n".format(self.cpus_info[i].core_id, self.cpus_info[i].core_temp)
        sys.stdout.write(stdout)
        return stdout

    def show_temperature_per_package(self):
        """ Prints the temperature of the CPU sockets in the host.
        """
        stdout = ""
        stdout += "Package(s) temperature\n"
        for i in range(0, self.num_cpus.value):
            if self.cpus_info[i].first_cpu_in_package:
                stdout += "\tPackage #{0} temperature: {1}\n".format(self.cpus_info[i].pack_id, self.cpus_info[i].pack_temp)
        sys.stdout.write(stdout)
        return stdout

    def show_core_frequency(self):
        """ Prints the frequencies of all the CPU cores
        """
        stdout = ""
        stdout += "Core frequencies\n"
        unit = 1000
        cpu_freq_info = list()
        for i in range(0, self.num_cpus.value):
            cpu_freq_info.append((self.cpus_info[i].cpu_id, self.cpus_info[i].cpu_freq))
        cpu_freq_info.sort(key=lambda tup: tup[0])
        for cpu in cpu_freq_info:
            stdout += "\tCPU {0:4}: Frequency: {1:.2f} Ghz\n".format(cpu[0], float(cpu[1]) / unit)
        sys.stdout.write(stdout)
        return stdout


class CPUPerformanceStates(object):
    """ Get the Current Power State information for the CPU Cores """

    def __init__(self):
        self.num_of_cores = 0
        self.core_pstate_info = dict()
        self.pstates = dict()
        if not UNIT_TEST:
            self.__get_num_of_cores()
            self.__get_pstates()
        else:
            self.num_of_cores = UNIT_TEST_PROCCESORS
            with open("pstates.pickle", "r") as _handler:
                self.pstates = pickle.load(_handler)

            with open("core_pstates.pickle", "r") as _handler:
                self.core_pstate_info = pickle.load(_handler)

    def __get_num_of_cores(self):
        stdout, stderr, retcode = run("cat /proc/cpuinfo | grep -i \"^processor\\s*:\" | wc -l")
        if retcode != 0:
            raise OSError("Unable to get number of cores")
        self.num_of_cores = int(stdout)

    def __get_pstates(self):
        if not os.path.exists(PSTATE_DRIVER_FILE):
            sys.stdout.write("Info: intel_pstate driver is not loaded.")
            sys.stdout.write(" P-States may not be enabled or are being governed by another driver\n")

        for x in xrange(0, self.num_of_cores):
            pstate_info = list()
            # Read P-States information from MSRs
            fd = os.open(MSR_FILE_NAME.format(x), os.O_RDONLY)
            os.lseek(fd, MSR_PLATFORM_INFO, os.SEEK_SET)
            plat_info = struct.unpack('8B', os.read(fd, 8))
            os.lseek(fd, MSR_IA32_PERF_STATUS, os.SEEK_SET)
            current_pstate_ratio = struct.unpack('8B', os.read(fd, 8))
            os.lseek(fd, MSR_IA32_PERF_CTL, os.SEEK_SET)
            target_pstate_ratio = struct.unpack('8B', os.read(fd, 8))
            os.close(fd)

            pstate_info.append(plat_info[-3] * MSR_RATIO_UNIT)
            pstate_info.append(plat_info[-7] * MSR_RATIO_UNIT)
            pstate_info.append(target_pstate_ratio[-7] * MSR_RATIO_UNIT)
            pstate_info.append(current_pstate_ratio[-7] * MSR_RATIO_UNIT)
            self.core_pstate_info[x] = pstate_info

            if x == 0:
                ratio = plat_info[-7] * MSR_RATIO_UNIT
                num_of_pstates = (plat_info[-7] - plat_info[-3]) + 1
                pstate = 1
                self.pstates[0] = ratio + 1
                while pstate <= num_of_pstates:
                    self.pstates[pstate] = ratio
                    pstate += 1
                    ratio -= 100

    def print_pstates(self):
        sys.stdout.write("******* Available P-States *******\n")
        for x in xrange(0, len(self.pstates)):
            sys.stdout.write("P{0} = {1} MHz\n".format(x, self.pstates[x]))
        sys.stdout.write("**********************************\n")

    def print_core_pstate_info(self):
        sys.stdout.write("******* Current P-States *******\n")
        for x in xrange(0, len(self.core_pstate_info)):
            target_ratio = self.core_pstate_info[x][2]
            for key, value in self.pstates.iteritems():
                if (target_ratio == value) or (key == 0 and target_ratio > value):
                    sys.stdout.write("CPU{0} = P{1}:{2} MHz\n".format(x, key, value))
                    break
        sys.stdout.write("********************************\n")


def test_cpu_info(args):
    try:
        cpu_info = CPUInformation()
        if (cpu_info.get_cpu_info_data() != 0):
            raise RuntimeError("Error while obtaining the CPU Information from {0} library.".format(CPU_INFO_SO))
        cpu_info.show_power_consumption()
        cpu_info.show_temperature_per_core()
        cpu_info.show_temperature_per_package()
        cpu_info.show_core_frequency()
        if (cpu_info.free_cpu_info_data() != 0):
             raise RuntimeError("Error while freeing the CPU Information from {0} library.".format(CPU_INFO_SO))
    except RuntimeError as e:
        sys.stderr.write("{0}\n".format(e))
        return -2
    except OSError as e:
        sys.stderr.write("Error while loading 'cpu-info.so' library!\n")
        sys.stderr.write("Exception message: {0}\n".format(e))
        return -3
    return 0


def test_pstates(args):
    try:
        cpu_pstates = CPUPerformanceStates()
    except OSError as e:
        sys.stderr.write("OSError while getting P-States info: {0}\n".format(e))
        return -1
    except ValueError as e:
        sys.stderr.write("ValueError while getting P-States info: {0}\n".format(e))
        return -2
    except:
        sys.stderr.write("Unknown Error detected!: {0}\n".format(sys.exc_info()[0]))
        return -3
    cpu_pstates.print_pstates()
    cpu_pstates.print_core_pstate_info()
    return 0
