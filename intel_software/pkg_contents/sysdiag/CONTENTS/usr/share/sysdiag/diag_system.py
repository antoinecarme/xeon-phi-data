# Copyright 2012-2017 Intel Corporation.
# 
# This software is supplied under the terms of a license agreement or
# nondisclosure agreement with Intel Corporation and may not be copied
# or disclosed except in accordance with the terms of that agreement.
import os
import time
import platform
import sys
import shutil
import stat
import tempfile
import glob
import sys_utils

# Global variables
RUNNING_UT = False
PARENT_DIRECTORY = tempfile.gettempdir()

# File and directory names that will be created
TEMP_DIR_PREFIX = "knl_debug."
TRACE_FILE_NAME = "trace.txt"
MACHINE_INFO_FILE_NAME = "machine_info.txt"
DMESG_FILE_NAME = "dmesg.txt"
BIOS_FILE_NAME = "dmidecode.txt"
CPU_INFO_FILE_NAME = "cpuinfo.txt"
PACKAGES_FILE_NAME = "list_packages.txt"
IFCONFIG_OPA_FILE_NAME = "ifconfigOPA.txt"
LSPCI_FILE_NAME = "lspci.txt"
LSMOD_FILE_NAME = "lsmod.txt"
OPA_FILE_NAME = "opainfo.txt"
IBV_FILE_NAME = "ibv_devinfo.txt"
OFED_FILE_NAME = "ofed_info.txt"
IBSTAT_FILE_NAME = "ibstat.txt"
IBDIAGNET_FILE_NAME = "ibdiagnet.txt"
TAR_FILE_NAME = "knl_debug_dump-{0}-{1}.{2}"

class SystemInfo(object):
    """ Class that creates a temporary directory under 'PARENT_DIRECTORY' and
        then gathers System information in files inside that directory. After the
        gathering finishes, a tar file is created from the directory and zipped.

        The tar file created can be sent to Intel(R) Customer Service for problem solving.

        The information gathered in the file includes:

            * General info      : OS Version, Kernel Version, NUMA Topology, BOOT Type, etc.
            * DMESG info        : Contents of the dmesg.
            * BIOS info         : Contents of the dmidecode tables.
            * CPU info          : Contents of the /proc/cpuinfo file.
            * Packages info     : List of the packages installed.
            * ACPI info         : Contents of the acpi tables.
            * Messages info     : Data from the /var/log/messages.
            * Mellanox(R) info  : Information for the Mellanox(R) card (if installed)
            * Intel(R) OPA info : Information for the Intel(R) OPA card (if installed)
    """
    def __init__(self, args):
        self.args = args
        self.trace_file = None
        self.dir_name = tempfile.mkdtemp(prefix=TEMP_DIR_PREFIX, dir=PARENT_DIRECTORY)
        self.suffix = self.dir_name.split(".")[-1]
        self.tar_file_name = os.path.join(PARENT_DIRECTORY,
                                          TAR_FILE_NAME.format(platform.node(),
                                                               time.strftime("%d_%b_%Y_%H_%M_%S"),
                                                               self.suffix))
        if not RUNNING_UT and self.args.verbosity >= 4: # If the debug level is high enough, print info
            sys.stdout.write("Suffix: {0}\n".format(self.suffix))
            sys.stdout.write("Directory name: {0}\n".format(self.dir_name))
            sys.stdout.write("Tar filename: {0}.tar.gz\n".format(self.tar_file_name))

    def _set_trace_file(self, trace_file):
        self.trace_file = trace_file

    def _create_sub_dir(self, sub_dir):
        dir_name = os.path.join(self.dir_name, sub_dir)
        os.makedirs(dir_name)

    def _exe_cmd(self, cmd, file_write, post_ret_msg={}):
        stdout, stderr, ret_code = sys_utils.run(cmd)
        if ret_code in post_ret_msg.keys():
             sys.stdout.write(post_ret_msg[ret_code])
        elif ret_code:
             err_msg = "Error! ret_code: {0}; stderr: {1}".format(ret_code, stderr)
             sys.stderr.write(err_msg)
             file_write.write(err_msg)
        file_write.write(stdout)
        return ret_code

    def _read_file(self, filename, file_write):
        try:
            with open(filename, "r") as file_read:
                file_write.write(file_read.read())
        except IOError as e:
            err_msg = "Error! Opening file '{0}': {1}\n".format(filename, e.message)
            sys.stderr.write(err_msg)
            file_write.write(err_msg)

    def _cp_cmd_stdout_to_file(self, filename, command, pre_msg=None, post_ret_msg={}):
        file_name = os.path.join(self.dir_name, filename)
        with open(file_name, "a") as fd:
            if pre_msg:
                fd.write(pre_msg)
            ret_code = self._exe_cmd(command, fd, post_ret_msg)
            if ret_code in post_ret_msg.keys():
                fd.write(post_ret_msg[ret_code])

    def _cp_file_info_to_file(self, filename_write, filename_read, message=None):
        file_name_write = os.path.join(self.dir_name, filename_write)
        with open(file_name_write, "a") as fw:
            if message:
                fw.write(message)
            self._read_file(filename_read, fw)

    def _cp_files_to_dir(self, dir_in, dir_out, pattern=None, ignore=False):
        files_copied = 0
        if pattern:
            glob_pattern = "*{0}*".format(pattern)
            files = glob.glob(os.path.join(dir_in, glob_pattern))
        else:
            files = os.listdir(dir_in)
        for file_name in files:
            full_file_name = os.path.join(dir_in, file_name)
            if os.path.isfile(full_file_name):
                try:
                    shutil.copy(full_file_name, dir_out)
                    files_copied+=1
                except IOError as e:
                    if not ignore:
                        err_msg = "Error copying file '{0}' to '{1}'\n{2}\n".format(full_file_name, dir_out, str(e))
                        sys.stderr.write(err_msg)
                        if self.trace_file:
                            self.trace_file.write(err_msg)
        return files_copied

    def change_files_permissions(self):
        try:
            for root, dirs, files in os.walk(self.dir_name):
                for d in dirs:
                    os.chmod(os.path.join(root, d), stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
                for f in files:
                    os.chmod(os.path.join(root, f), stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
        except OSError:
            pass

    def delete_parent_dir(self):
        shutil.rmtree(self.dir_name)

    def create_tar_file(self):
        shutil.make_archive(self.tar_file_name, "gztar", PARENT_DIRECTORY, self.dir_name)

    def get_all(self):
        sys.stdout.write("\nGetting all system info\n")
        trace_file_name = os.path.join(self.dir_name, TRACE_FILE_NAME)
        with open(trace_file_name, 'a') as trace_file:
            self._set_trace_file(trace_file)
            trace_file.write(time.strftime("%c %Z\n"))
            self.get_general_info()
            self.get_dmesg_info()
            self.get_bios_info()
            self.get_cpu_info()
            self.get_packages_info()
            self.get_acpi_info()
            self.get_messages_info()
            self.get_kernel_config_info()
            self.get_fabric_info()
            trace_file.write(time.strftime("%c %Z\n"))
        sys.stdout.write("\nPacking content\n")
        self.change_files_permissions()
        self.create_tar_file()
        self.delete_parent_dir()
        sys.stdout.write("\nPlease save {0}.tar.gz and contact Customer Support.\n\n".format(self.tar_file_name))

    def get_general_info(self):
        sys.stdout.write("\nGetting general system info\n")
        self._cp_cmd_stdout_to_file(MACHINE_INFO_FILE_NAME, "uname -a", "uname: ")
        self._cp_file_info_to_file(MACHINE_INFO_FILE_NAME, "/proc/version", "Kernel Version: ")
        self._cp_cmd_stdout_to_file(MACHINE_INFO_FILE_NAME, "nproc", "No. of CPUs: ")
        self._cp_cmd_stdout_to_file(MACHINE_INFO_FILE_NAME, "numactl -H", "NUMA topology\n")
        self._cp_cmd_stdout_to_file(MACHINE_INFO_FILE_NAME, "ls -alR /var/crash", "Content of the /var/crash\n")

    def get_dmesg_info(self):
        sys.stdout.write("\nGetting dmesg\n")
        self._cp_cmd_stdout_to_file(DMESG_FILE_NAME, "dmesg")

    def get_bios_info(self):
        sys.stdout.write("\nGetting BIOS dump\n")
        self._cp_cmd_stdout_to_file(BIOS_FILE_NAME, "dmidecode 2>&1")

    def get_cpu_info(self):
        sys.stdout.write("\nGetting /proc/cpuinfo\n")
        self._cp_file_info_to_file(CPU_INFO_FILE_NAME, "/proc/cpuinfo")

    def get_packages_info(self):
        sys.stdout.write("\nGetting list of installed packages\n")
        list_packages_cmd = ""
        _, _, ret_code = sys_utils.run("which rpm")
        if ret_code == 0:
            list_packages_cmd = "rpm -qa"
        else:
            _, _, ret_code = sys_utils.run("which dpkg")
            if ret_code == 0:
                list_packages_cmd = "dpkg -l"
            else:
                sys.stderr.write("\nUnable to get list of installed packages\n")
                return
        self._cp_cmd_stdout_to_file(PACKAGES_FILE_NAME, list_packages_cmd)

    def get_acpi_info(self):
        sys.stdout.write("\nCopying ACPI tables\n")
        acpi_dynamic = "dynamic"
        acpi_in_dir = "/sys/firmware/acpi/tables/"
        acpi_in_dynamic_dir = os.path.join(acpi_in_dir, acpi_dynamic)
        acpi_dir_name = "acpi_tables"
        acpi_dynamic_dir_name = os.path.join(acpi_dir_name, acpi_dynamic)
        acpi_dir = os.path.join(self.dir_name, acpi_dir_name)
        acpi_dynamic_dir = os.path.join(self.dir_name, acpi_dynamic_dir_name)
        self._create_sub_dir(acpi_dynamic_dir_name)
        self._cp_files_to_dir(acpi_in_dir, acpi_dir)
        self._cp_files_to_dir(acpi_in_dynamic_dir, acpi_dynamic_dir, ignore=True)

    def get_messages_info(self):
        sys.stdout.write("\nCopying /var/log/messages\n")
        messages_dir = "/var/log"
        messages_pattern = "messages"
        self._cp_files_to_dir(messages_dir, self.dir_name, messages_pattern)

    def get_kernel_config_info(self):
        sys.stdout.write("\nCopying kernel config\n")
        dir_name = "/proc"
        config_file = "config.gz"
        if not self._cp_files_to_dir(dir_name, self.dir_name, config_file):
            dir_name = "/boot"
            config_file = "config-{0}".format(platform.release())
            self._cp_files_to_dir(dir_name, self.dir_name, config_file)

    def get_fabric_info(self):
        mellanox = "Mellanox"
        opa = "HFI"
        mell_found = False
        opa_found = False
        self.get_lspci_info()
        lspci_file_name = os.path.join(self.dir_name, LSPCI_FILE_NAME)
        with open(lspci_file_name, "r") as lspci_file:
            for line in lspci_file:
                if not mell_found and mellanox in line:
                    mell_found = True
                if not opa_found and opa in line:
                    opa_found = True
                if mell_found and opa_found:
                    break
        if mell_found or opa_found:
            self.get_ifconfig_info()
            self.get_lsmod_info()
        if mell_found:
            self.get_mellanox_info()
        if opa_found:
            self.get_opa_info()

    def get_lspci_info(self):
        sys.stdout.write("\nGetting lspci\n")
        self._cp_cmd_stdout_to_file(LSPCI_FILE_NAME, "lspci -k -vvv -mm")

    def get_ifconfig_info(self):
        sys.stdout.write("\nGetting ifconfig\n")
        self._cp_cmd_stdout_to_file(IFCONFIG_OPA_FILE_NAME, "ifconfig -a 2> /dev/null | grep -i -A4 -B3 infiniband",
                                    post_ret_msg={1: "Warning: cannot find infiniband in ifconfig"})

    def get_lsmod_info(self):
        sys.stdout.write("\nGetting lsmod\n")
        self._cp_cmd_stdout_to_file(LSMOD_FILE_NAME, "lsmod")

    def get_mellanox_info(self):
        sys.stdout.write("\nGetting MLNX info\n")
        mell_dir_name = "mlnx"
        self._create_sub_dir(mell_dir_name)
        self._cp_cmd_stdout_to_file(os.path.join(mell_dir_name, OFED_FILE_NAME), "ofed_info",
                                    post_ret_msg={127: "Warning: cannot get Mellanox info. "
                                                       "Binary: 'ofed_info' not found\n"})
        self._cp_cmd_stdout_to_file(os.path.join(mell_dir_name, IBSTAT_FILE_NAME), "ibstat",
                                    post_ret_msg={127: "Warning: cannot get Mellanox info. "
                                                       "Binary: 'ibstat' not found\n"})
        self._cp_cmd_stdout_to_file(os.path.join(mell_dir_name, IBDIAGNET_FILE_NAME), "ibdiagnet -o",
                                    post_ret_msg={127: "Warning: cannot get Mellanox info. "
                                                       "Binary: 'ibdiagnet' not found\n"})

    def get_opa_info(self):
        sys.stdout.write("\nGetting HFI info\n")
        opa_dir_name = "opa"
        self._create_sub_dir(opa_dir_name)
        self._cp_cmd_stdout_to_file(os.path.join(opa_dir_name, OPA_FILE_NAME), "opaconfig -V", "OPA version: ",
                                    post_ret_msg={127: "Warning: cannot get HFI info. "
                                                       "Binary: 'opaconfig' not found\n"})
        self._cp_cmd_stdout_to_file(os.path.join(opa_dir_name, OPA_FILE_NAME), "opainfo",
                                    post_ret_msg={127: "Warning: cannot get HFI info. "
                                                       "Binary: 'opainfo' not found\n"})
        self._cp_cmd_stdout_to_file(os.path.join(opa_dir_name, IBV_FILE_NAME), "ibv_devinfo",
                                    post_ret_msg={127: "Warning: cannot get HFI info. "
                                                       "Binary: 'ibv_devinfo' not found\n"})


def dump_system_info(args):
    """ Function that calls SystemInfo class for gathering all the system information
        so it can be archived in a file that can be sent to Intel(R) Customer Service
        for problem solving.
    """
    try:
        sys_info = SystemInfo(args)
        sys_info.get_all()
        return 0
    except Exception as e:
        sys.stderr.write("Exception caught while getting system info: \"")
        sys.stderr.write(str(e))
        sys.stderr.write("\"\n")
        return 1
