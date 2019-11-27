# Copyright 2012-2017 Intel Corporation.
# 
# This software is supplied under the terms of a license agreement or
# nondisclosure agreement with Intel Corporation and may not be copied
# or disclosed except in accordance with the terms of that agreement.
import copy
import ctypes
import os
import pprint
import struct
import sys
from sys_utils import run, FIND_LIBRARY_CMD, MEMKIND_LIBRARY

RUNNING_UT = False
MESSAGE_UNAVAILABLE = "Not Available"
MESSAGE_AVAILABLE = "Available"
MESSAGE_NOT_RESERVED = "Unable to reserve {0} memory"

# dmi_sysfs global variables
DMI_SYSFS_ROOT = "/sys/firmware/dmi/entries"
DMI_FILENAME = DMI_SYSFS_ROOT + "/{0}/raw"
DMI_GROUP_ASSOCIATIONS_TYPE = "14-{0}"
DMI_GROUP_STRING = "Group: "
DMI_SYS_KNL_GROUP_NAME = "Knights Landing Information"
DMI_SYS_KNM_GROUP_NAME = "Knights Mill Information"
DMI_SYS_GENERAL_INFO_TYPE = "{0}-0"

# smbios enum values
TYPE_16_LOCATION_OTHER = 0x01
TYPE_16_LOCATION_SYSTEM = 0x03
TYPE_16_USE_SYSTEM = 0x03
TYPE_16_USE_CACHE = 0x07
TYPE_17_FORM_FACTOR_CHIP = 0x05
TYPE_17_TYPE_DETAIL_CACHE_DRAM = 0x800

class DMITable(object):
    """Base class for Table Type objects
    """
    def __init__(self, table_type):
        self.table_type = table_type
        self.entries = list()
        self._process_dmi_table()

    def __iter__(self):
        for entry in self.entries:
            yield entry

    def __len__(self):
        return len(self.entries)

    def _process_dmi_table(self):
        """Function that reads dmi table information.
        """
        fd = None
        table_file_format = "{0}-".format(os.path.join(DMI_SYSFS_ROOT, str(self.table_type)))
        for top_dir, _, _ in os.walk(DMI_SYSFS_ROOT):
            if not top_dir.startswith(table_file_format):
                continue
            file_name = os.path.join(top_dir, "raw")
            try:
                fd = os.open(file_name, os.O_RDONLY)
                self._process_dmi_file(fd)
            except (OSError, NameError) as e:
                err_msg = "Error processing DMI Type {0}: {1}\n".format(self.table_type, e)
                raise DMIException(err_msg)
            except:
                err_msg = "Unknown Error while processing DMI Type {0}: {1}\n".format(self.table_type, sys.exc_info()[0])
                raise DMIException(err_msg)
            finally:
                if fd:
                    os.close(fd)

    def _process_dmi_file(self, fd):
        """Function needs to be implemented by child classes
        """
        raise NotImplementedError



    def _get_strings_info(self, fd, length):
        """Function that gathers the strings on the smbios table being parsed
           According to SMBIOS Spec: The strings are a series of characters
                                     followed by the null char (value 0). If two
                                     null chars are read, then there are no more
                                     strings for the table.
        """
        strings = ["",]
        chars = list()
        null_found = False
        os.lseek(fd, length, os.SEEK_SET)
        while True:
            char = struct.unpack('1B', os.read(fd, 1))[0]
            if not char:
                if chars:
                    strings.append("".join(chars))
                    chars[:] = []
                if null_found:
                    break;
                null_found = True
                continue;
            null_found = False
            chars.append(chr(char))
        return strings

class DMITableType16(DMITable):
    """Class that reads DMI Table Type 16
    """

    def __init__(self):
        DMITable.__init__(self, 16)

    def __str__(self):
        header = "\tTable Type 16 Content (Num Ele: {0}): \n".format(len(self.entries))
        footer = "\tEnding table Type 16.\n"
        contents =list()
        for entry in self.entries:
            entry_contents = (
                             "Type: {0}\n"
                             "Length: {1}\n"
                             "Handle: {2}\n"
                             "Location: {3}\n"
                             "Use: {4}\n"
                             "Mem Err Corr: {5}\n"
                             "MaxCap: {6}\n"
                             "Mem Err Inf: {7}\n"
                             "Num Mem Dev: {8}\n"
                             "Ext Max Cap: {9}\n\n").format(entry["table_type"],
                                                            hex(entry["lenght"]),
                                                            hex(entry["handle"]),
                                                            hex(entry["location"]),
                                                            hex(entry["use"]),
                                                            hex(entry["mem_err_corr"]),
                                                            entry["max_cap"],
                                                            hex(entry["mem_err_inf"]),
                                                            entry["num_mem_dev"],
                                                            entry["ext_max_cap"])
            contents.append(entry_contents)
        contents_str = "".join(contents)
        output = "{0} {1} {2}".format(header, contents_str, footer)
        return output

    def _process_dmi_file(self, fd):
        """ Function that parses information from DMI File Type 16
        """
        os.lseek(fd, 0, os.SEEK_SET)
        table_type = struct.unpack('1B', os.read(fd, 1))[0]
        length = struct.unpack('1B', os.read(fd, 1))[0]
        handle = struct.unpack('1H', os.read(fd, 2))[0]
        location = struct.unpack('1B', os.read(fd, 1))[0]
        use = struct.unpack('1B', os.read(fd, 1))[0]
        mem_err_corr = struct.unpack('1B', os.read(fd, 1))[0]
        max_cap = struct.unpack('1I', os.read(fd, 4))[0]
        mem_err_inf = struct.unpack('1H', os.read(fd, 2))[0]
        num_mem_dev = struct.unpack('1H', os.read(fd, 2))[0]
        ext_max_cap = struct.unpack('1Q', os.read(fd, 8))[0]
        strings = self._get_strings_info(fd, length)
        self.entries.append({"table_type": table_type,
                           "lenght": length,
                           "handle": handle,
                           "location": location,
                           "use": use,
                           "mem_err_corr": mem_err_corr,
                           "max_cap": max_cap, # In KB
                           "mem_err_inf":  mem_err_inf,
                           "num_mem_dev": num_mem_dev, # if value = 0xFFFE no error information
                           "ext_max_cap": ext_max_cap}) # Only available if max_cap = 0x80000000. in B

class DMITableType17(DMITable):
    """Class that reads DMI Table Type 17
    """

    def __init__(self):
        DMITable.__init__(self, 17)

    def __str__(self):
        header = "\tTable Type 17 Content (Num Ele: {0}): \n".format(len(self.entries))
        footer = "\tEnding table Type 17.\n"
        contents = list()
        for entry in self.entries:
            entry_contents = (
                             "Type: {0}\n"
                             "Length: {1}\n"
                             "Handle: {2}\n"
                             "Phys Memory Loc: {3}\n"
                             "Mem Error Inf: {4}\n"
                             "Total Width: {5}\n"
                             "Data Width: {6}\n"
                             "Size: {7}\n"
                             "Form Factor: {8}\n"
                             "Device Set: {9}\n"
                             "Device Locator: {10}\n"
                             "Bank Locator: {11}\n"
                             "Memory Type: {12}\n"
                             "Type Detail: {13}\n"
                             "Speed: {14}\n"
                             "Manufacturer: {15}\n"
                             "Serial Number: {16}\n"
                             "Asset Tag: {17}\n"
                             "Part Number: {18}\n"
                             "Attributes: {19}\n"
                             "Ext Size: {20}\n"
                             "Conf Memory Speed: {21}\n"
                             "Min Volt: {22}\n"
                             "Max Volt: {23}\n"
                             "Conf Volt: {24}\n\n").format(entry["table_type"],
                                                           hex(entry["length"]),
                                                           hex(entry["handle"]),
                                                           entry["phys_mem"],
                                                           hex(entry["mem_err_info"]),
                                                           entry["total_width"],
                                                           entry["data_width"],
                                                           entry["size"],
                                                           hex(entry["form_factor"]),
                                                           hex(entry["dev_set"]),
                                                           entry["dev_locator"],
                                                           entry["bank_locator"],
                                                           hex(entry["mem_type"]),
                                                           hex(entry["type_det"]),
                                                           entry["speed"],
                                                           entry["manufacturer"],
                                                           entry["serial_num"],
                                                           entry["asset_tag"],
                                                           entry["part_num"],
                                                           hex(entry["attributes"]),
                                                           hex(entry["ext_size"]),
                                                           entry["conf_mem_speed"],
                                                           entry["min_volt"],
                                                           entry["max_volt"],
                                                           entry["conf_volt"])
            contents.append(entry_contents)
        contents_str = "".join(contents)
        output = "{0} {1} {2}".format(header, contents_str, footer)
        return output

    def _process_dmi_file(self, fd):
        """ Function that parses information from DMI File Type 17
        """
        os.lseek(fd, 0, os.SEEK_SET)
        table_type = struct.unpack('1B', os.read(fd, 1))[0]
        length = struct.unpack('1B', os.read(fd, 1))[0]
        handle = struct.unpack('1H', os.read(fd, 2))[0]
        phys_mem = struct.unpack('1H', os.read(fd, 2))[0]
        mem_err_info = struct.unpack('1H', os.read(fd, 2))[0]
        total_width = struct.unpack('1H', os.read(fd, 2))[0]
        data_width = struct.unpack('1H', os.read(fd, 2))[0]
        size = struct.unpack('1H', os.read(fd, 2))[0]
        form_factor = struct.unpack('1B', os.read(fd, 1))[0]
        dev_set = struct.unpack('1B', os.read(fd, 1))[0]
        dev_locator = struct.unpack('1B', os.read(fd, 1))[0]
        bank_locator = struct.unpack('1B', os.read(fd, 1))[0]
        mem_type = struct.unpack('1B', os.read(fd, 1))[0]
        type_det = struct.unpack('1H', os.read(fd, 2))[0]
        speed = struct.unpack('1H', os.read(fd, 2))[0]
        manufacturer = struct.unpack('1B', os.read(fd, 1))[0]
        serial_num = struct.unpack('1B', os.read(fd, 1))[0]
        asset_tag = struct.unpack('1B', os.read(fd, 1))[0]
        part_num = struct.unpack('1B', os.read(fd, 1))[0]
        attributes = struct.unpack('1B', os.read(fd, 1))[0]
        ext_size = struct.unpack('1I', os.read(fd, 4))[0]
        conf_mem_speed = struct.unpack('1H', os.read(fd, 2))[0]
        min_volt = struct.unpack('1H', os.read(fd, 2))[0]
        max_volt = struct.unpack('1H', os.read(fd, 2))[0]
        conf_volt = struct.unpack('1H', os.read(fd, 2))[0]
        strings = self._get_strings_info(fd, length)
        self.entries.append({"table_type": table_type,
                           "length": length,
                           "handle": handle,
                           "phys_mem": phys_mem,
                           "mem_err_info": mem_err_info,
                           "total_width": total_width,
                           "data_width": data_width,
                           # size Value Note:
                           # if Bit15 = 0 units are MB, else units are KB.
                           # if value = 0x7FFF atual size is in "ext_size"
                           # if value = 0xFFFF size unknown.
                           "size": size,
                           "form_factor": form_factor,
                           "dev_set": dev_set,
                           "dev_locator": strings[dev_locator].strip() if dev_locator < len(strings) else "",
                           "bank_locator": strings[bank_locator].strip() if bank_locator < len(strings) else "",
                           "mem_type": mem_type,
                           "type_det": type_det,
                           "speed": speed, # In MHz
                           "manufacturer": strings[manufacturer].strip() if manufacturer < len(strings) else "",
                           "serial_num": strings[serial_num].strip() if serial_num < len(strings) else "",
                           "asset_tag": strings[asset_tag].strip() if asset_tag < len(strings) else "",
                           "part_num": strings[part_num].strip() if part_num < len(strings) else "",
                           "attributes": attributes,
                           "ext_size": ext_size, # Only usable if size value = 0x7FFF. In MB
                           "conf_mem_speed": conf_mem_speed,
                           "min_volt": min_volt, # In mV
                           "max_volt": max_volt, # In mV
                           "conf_volt": conf_volt}) # In mV

class DMITableFactory(object):
    """Creates DMI Table Objects
       Currently only tables 16 and 17 are supported.
    """

    supported_types = dict()
    supported_types[16] = DMITableType16
    supported_types[17] = DMITableType17

    @staticmethod
    def get_table(table_type):
        if table_type not in DMITableFactory.supported_types:
            err_msg = "Table Type {0} is not supported!\n".format(table_type)
            sys.stderr.write(err_msg)
            raise DMIException(err_msg)
        return DMITableFactory.supported_types[table_type]()

class Dimm(object):
    """Class that stores the DIMM information needed
    """
    def __init__(self, entry):
        self.type = MemType.UNKNOWN
        self.mcdram_use = MCDRAMUse.UNKNOWN
        self.size = 0 # In MB
        self.speed = 0 # In MHz
        self.conf_volt = 0 # In mV

        if entry["form_factor"] == TYPE_17_FORM_FACTOR_CHIP or "mcdram" in entry["dev_locator"].lower():
            self.type = MemType.MCDRAM
            if entry["type_det"] & TYPE_17_TYPE_DETAIL_CACHE_DRAM:
                self.mcdram_use = MCDRAMUse.CACHE
            else:
                self.mcdram_use = MCDRAMUse.SYSTEM
        else:
            self.type = MemType.DIMM
            self.mcdram_use = MCDRAMUse.UNKNOWN
        if entry["size"] == 0xFFFF:
            self.size = 0
        elif entry["size"] == 0x7FFF:
            self.size = entry["ext_size"]
        elif entry["size"] & 0x8000:
            self.size = entry["size"] / 1024 # Value in KB, convert it to MB
        else:
            self.size = entry["size"]
        self.speed = entry["speed"]
        self.conf_volt = entry["conf_volt"]

class MemoryTopology(object):
    """Reads DMI tables 16 and 17 for memory information creates a dict for
    each dimm module (incluiding empty dimm).

    Then each dict is append to self.dimms, which can be iterated

    Also reads the dmi-sysfs information to obtain the Memory, Cluster
    and MCDRAM Cache configurations
    """

    def __init__(self, args):
        self.args = args
        self.dimms = list()
        self.mcdram_cache = 0
        self.mcdram_system = 0
        self.cluster_mode = "Unavailable"
        self.memory_mode = "Unavailable"
        self.mem_MCDRAM_cache_info = "Unavailable"
        self._read_memory_information()
        self._read_configuration_modes()

    def __iter__(self):
        for dimm in self.dimms:
            yield dimm

    def __len__(self):
        return len(self.dimms)

    def __str__(self):
        return pprint.pformat(self.dimms)

    def _read_memory_information(self):
        """Function that obtains the Memory Information and stores it in a list
           of dictionaries, each containing the information for one handle of the
           memory
        """
        self.mcdram_cache = 0
        self.mcdram_system = 0
        try:
            table_16_info = DMITableFactory.get_table(16)
            table_17_info = DMITableFactory.get_table(17)
        except DMIException as e:
            sys.stderr.write("Error obtaining SMBIOS table information: {0}\n".format(e))
            return

        if not RUNNING_UT and self.args.verbosity >= 4: # If the debug level is high enough, print SMBIOS tables
            sys.stdout.write(str(table_16_info))
            sys.stdout.write(str(table_17_info))

        for entry in table_16_info:
            if entry["location"] == TYPE_16_LOCATION_OTHER:
                if entry["max_cap"] == 0x80000000:
                    mcdram_mem = entry["ext_max_cap"] / (1024 * 1024) # Value in Bytes, convert it to MB
                else:
                    mcdram_mem = entry["max_cap"] / 1024 # Value in KB, convert it to MB
                if entry["use"] == TYPE_16_USE_SYSTEM:
                    self.mcdram_system += mcdram_mem
                if entry["use"] == TYPE_16_USE_CACHE:
                    self.mcdram_cache += mcdram_mem
            else:
                continue

        for entry in table_17_info:
            self.dimms.append(Dimm(entry))

    def _read_configuration_modes(self):
        type_file_num = 0
        while True:
            if self._process_dmi_group_file(
                    DMI_FILENAME.format(DMI_GROUP_ASSOCIATIONS_TYPE.format(type_file_num))) == 1:
                type_file_num += 1
            else:
                break

    def _process_dmi_group_file(self, filename):
        fd = None
        try:
            fd = os.open(filename, os.O_RDONLY)
            type = struct.unpack('1B', os.read(fd, 1))[0]
            length = struct.unpack('1B', os.read(fd, 1))[0]
            os.lseek(fd, length, os.SEEK_SET)
            name_str = os.read(fd, (len(DMI_GROUP_STRING) + max(len(DMI_SYS_KNL_GROUP_NAME), len(DMI_SYS_KNM_GROUP_NAME))))
            if DMI_SYS_KNL_GROUP_NAME not in name_str and \
               DMI_SYS_KNM_GROUP_NAME not in name_str:
                return 1
            members = (length - 5) / 3
            os.lseek(fd, 5, os.SEEK_SET)
            for x in range(0, members):
                grp_type = struct.unpack('1B', os.read(fd, 1))[0]
                grp_handle = struct.unpack('1H', os.read(fd, 2))[0]
                if self._process_dmi_member_file(DMI_FILENAME.format(DMI_SYS_GENERAL_INFO_TYPE.format(grp_type))) == 0:
                    break
        except OSError as e:
            sys.stderr.write("Group Knights Landing Information not found on DMI sysfs: {0}\n".format(e))
            return 2
        except:
            sys.stderr.write(
                "Unknown Error detected while getting Knights Landing Information Group from DMI sysfs: {0}\n".format(
                    sys.exc_info()[0]))
            return 2
        finally:
            if fd:
                os.close(fd)
        return 0

    def _process_dmi_member_file(self, filename):
        grp_fd = None
        try:
            grp_fd = os.open(filename, os.O_RDONLY)
            os.lseek(grp_fd, 4, os.SEEK_SET)
            member_id = struct.unpack('1B', os.read(grp_fd, 1))[0]
            if member_id != 0x0001:
                return 1
            os.lseek(grp_fd, 7, os.SEEK_SET)
            supported_cluster_mode = struct.unpack('1B', os.read(grp_fd, 1))[0]
            conf_cluster_mode = struct.unpack('1B', os.read(grp_fd, 1))[0]
            supported_memory_mode = struct.unpack('1B', os.read(grp_fd, 1))[0]
            conf_memory_mode = struct.unpack('1B', os.read(grp_fd, 1))[0]
            conf_MCDRAM_cache = struct.unpack('1B', os.read(grp_fd, 1))[0]
            self.cluster_mode = self._cluster_mode(conf_cluster_mode)
            self.memory_mode = self._memory_mode(conf_memory_mode)
            self.mem_MCDRAM_cache_info = self._memory_MCDRAM_cache(conf_MCDRAM_cache)
        except OSError as e:
            sys.stderr.write("Member Knights Landing Information not found on DMI sysfs: {0}\n".format(e))
            return 2
        except:
            sys.stderr.write(
                "Unknown Error detected while getting Knights Landing Information Member from DMI sysfs: {0}\n".format(
                    sys.exc_info()[0]))
            return 2
        finally:
            if grp_fd:
                os.close(grp_fd)
        return 0

    def _cluster_mode(self, value):
        if value == 0x01:
            cluster_mode = "Quadrant"
        elif value == 0x02:
            cluster_mode = "Hemisphere"
        elif value == 0x04:
            cluster_mode = "SNC4"
        elif value == 0x08:
            cluster_mode = "SNC2"
        elif value == 0x010:
            cluster_mode = "ALL2ALL"
        else:
            cluster_mode = "Unavailable"
        return cluster_mode

    def _memory_mode(self, value):
        if value == 0x01:
            memory_mode = "Cache"
        elif value == 0x02:
            memory_mode = "Flat"
        elif value == 0x04:
            memory_mode = "Hybrid"
        else:
            memory_mode = "Unavailable"
        return memory_mode

    def _memory_MCDRAM_cache(self, value):
        if value == 0x00:
            mem_MCDRAM_cache_info = "No MCDRAM used as Cache"
        elif value == 0x01:
            mem_MCDRAM_cache_info = "25% of MCDRAM used as Cache"
        elif value == 0x02:
            mem_MCDRAM_cache_info = "50% of MCDRAM used as Cache"
        elif value == 0x04:
            mem_MCDRAM_cache_info = "100% of MCDRAM used as Cache"
        else:
            mem_MCDRAM_cache_info = "Unavailable"
        return mem_MCDRAM_cache_info

    def get_total_memory(self, mem_type):
        size = 0
        for dimm in self.dimms:
            if dimm.type == mem_type:
                size += dimm.size
        return size

    def get_MCDRAM_mem(self, use):
        size = 0
        for dimm in self.dimms:
            if dimm.type == MemType.MCDRAM and dimm.mcdram_use == use:
                size += dimm.size
        if use == MCDRAMUse.CACHE:
            if self.mcdram_cache != size:
                sys.stdout.write("Note: MCDRAM Cache memory size '{0}'".format(self.mcdram_cache))
                sys.stdout.write(" reported in SMBIOS Table 16 is different from")
                sys.stdout.write(" the size '{0}' reported in Table 17.\n".format(size))
        elif use == MCDRAMUse.SYSTEM:
            if self.mcdram_system != size:
                sys.stdout.write("Note: MCDRAM system memory size '{0}'".format(self.mcdram_system))
                sys.stdout.write(" reported in SMBIOS Table 16 is different from")
                sys.stdout.write(" the size '{0}' reported in Table 17.\n".format(size))
        return size

    def get_freq(self, mem_type):
        freq = 0
        for dimm in self.dimms:
            if dimm.type == mem_type:
                if freq == 0 or dimm.speed < freq:
                    freq = dimm.speed
        return freq

    def get_voltage(self, mem_type):
        voltage = 0
        for dimm in self.dimms:
            if dimm.type == mem_type:
                if voltage == 0 or dimm.conf_volt > voltage:
                    voltage = dimm.conf_volt
        return voltage

    def get_access(self, mem_type, mem_size, reserve_size=512):
        access = MESSAGE_UNAVAILABLE

        try:
            stdout, stderr, return_code = run(FIND_LIBRARY_CMD.format(MEMKIND_LIBRARY))
            stdout.strip()
            stdout = stdout.splitlines()[0]
            if return_code != 0 or not stdout:
                sys.stderr.write(
                    "Error: library '{0}' not found using 'ldconfig' command. Make sure you have the library installed and that 'ldconfig' DB is updated \n".format(
                        MEMKIND_LIBRARY))
                return access
            lib_to_load = stdout.split("=>")[1].strip()
            mem_kind = ctypes.cdll.LoadLibrary(lib_to_load)
        except OSError as e:
            sys.stderr.write("OSError while loading the library: {0}\n".format(e))
            sys.stderr.write("Is library '" + MEMKIND_LIBRARY + "' correctly installed?\n")
            return access
        except Exception as e:
            sys.stderr.write("Unexpected error while loading the library '" + MEMKIND_LIBRARY + "'. Exception: " + str(e) + "\n")
            return access

        if not mem_kind:
            sys.stderr.write("Error: Library '" + MEMKIND_LIBRARY + "' was not loaded correctly\n")
            return access

        if mem_type == MemType.DIMM:
            try:
                if mem_size > 0:
                    big_list_1 = list(range(100000))
                    big_list_2 = copy.deepcopy(big_list_1)
                    del big_list_1
                    del big_list_2
                else:
                    sys.stdout.write("Note: DDR memory size is zero. Cannot reserve DDR memory.\n")
                    return access
            except:
                sys.stderr.write("Error: Could not allocate DDR memory. Exception: " + str(sys.exc_info()[0]) + "\n")
                access = MESSAGE_NOT_RESERVED.format("DDR")
                return access
            access = MESSAGE_AVAILABLE
        elif mem_type == MemType.MCDRAM:
            if self.memory_mode == "Cache" or "100%" in self.mem_MCDRAM_cache_info:
                sys.stdout.write("Note: All MCDRAM memory is being used as Cache. Cannot reserve memory.\n")
                return access
            hbw_reserve_size = ctypes.c_size_t(reserve_size * 1024)
            hbw_available = mem_kind.hbw_check_available()
            if hbw_available == 0:
                hbw_malloc = mem_kind.hbw_malloc
                hbw_malloc.restype = ctypes.c_void_p
                hbw_mem_ptr = hbw_malloc(hbw_reserve_size)
                if hbw_mem_ptr != 0:
                    access = MESSAGE_AVAILABLE
                    hbw_free = mem_kind.hbw_free
                    hbw_free.argtypes = [ctypes.c_void_p]
                    hbw_free(hbw_mem_ptr)
                else:
                    sys.stderr.write("Error: Could not allocate MCDRAM memory, libmemkind returned NULL pointer.\n")
                    access = MESSAGE_NOT_RESERVED.format("MCDRAM")
            else:
                if (
                    self.get_total_ddr_memory() == 0 and
                    self.get_memory_mode() == "Flat" and # When there are no DIMMs installed, the only supported Memory Mode is 'Flat'
                    self.get_sys_mcd_memory() > 0
                   ):
                    sys.stdout.write("Note: There are no DDR DIMMs installed on the system.")
                    sys.stdout.write(" MCDRAM is being used as the only System Memory.")
                    sys.stdout.write(" Checking access to this memory.\n")
                    try:
                        big_list_1 = list(range(100000))
                        big_list_2 = copy.deepcopy(big_list_1)
                        del big_list_1
                        del big_list_2
                    except:
                        sys.stderr.write("Error: Could not allocate MCDRAM (as the only System Memory). Exception: " + str(sys.exc_info()[0]) + "\n")
                        access = MESSAGE_NOT_RESERVED.format("MCDRAM (as the only System Memory)")
                        return access
                    access = MESSAGE_AVAILABLE
                elif mem_size > 0:
                    sys.stderr.write("Error: MCDRAM memory size is greater than zero")
                    sys.stderr.write(" but libmemkind reported that is not available.")
                    sys.stderr.write(" Return code: {0}\n".format(hbw_available))
                    access = MESSAGE_NOT_RESERVED.format("MCDRAM")
                else:
                    access = MESSAGE_UNAVAILABLE
        else:
            access = MESSAGE_UNAVAILABLE

        return access

    def get_total_ddr_memory(self):
        return self.get_total_memory(MemType.DIMM)

    def get_total_mcd_memory(self):
        return self.get_total_memory(MemType.MCDRAM)

    def get_cache_mcd_memory(self):
        return self.get_MCDRAM_mem(MCDRAMUse.CACHE)

    def get_sys_mcd_memory(self):
        return self.get_MCDRAM_mem(MCDRAMUse.SYSTEM)

    def get_ddr_freq(self):
        return self.get_freq(MemType.DIMM)

    def get_mcd_freq(self):
        return self.get_freq(MemType.MCDRAM)

    def get_ddr_voltage(self):
        return self.get_voltage(MemType.DIMM)

    def get_mcd_voltage(self):
        return self.get_voltage(MemType.MCDRAM)

    def get_ddr_access(self, mem_size):
        return self.get_access(MemType.DIMM, mem_size)

    def get_mcd_access(self, mem_size):
        return self.get_access(MemType.MCDRAM, mem_size)

    def get_cluster_mode(self):
        return self.cluster_mode

    def get_memory_mode(self):
        return self.memory_mode

    def get_MCDRAM_cache_info(self):
        return self.mem_MCDRAM_cache_info

class DMIException(Exception):
    pass

class MemType:
    UNKNOWN, DIMM, MCDRAM = range(3)

class MCDRAMUse:
    UNKNOWN, SYSTEM, CACHE = range(3)


def print_memory_config(memory_config, memMCDRAMCache):
    """ Prints the Memory Configuration from dmi-sysfs (BIOS)
    """
    mem_cfg = "Memory Configuration is: {0}".format(memory_config)
    mcdram_cache = "MCDRAM Configured as Cache is: {0}".format(memMCDRAMCache)
    sys.stdout.write(mem_cfg)
    sys.stdout.write("\n")
    sys.stdout.write(mcdram_cache)
    sys.stdout.write("\n")


def print_cluster_config(clusterConfig):
    """ Prints the Cluster Configuration from dmi-sysfs (BIOS)
    """
    cluster_cfg = "Cluster Configuration is: {0}".format(clusterConfig)
    sys.stdout.write(cluster_cfg)
    sys.stdout.write("\n")


def print_memory_info(mem_type, size, speed, freq, volt, access="Not Available", mcdram_cache=0, mcdram_sys=0):
    mem_header = "*************** {0} Info ***************\n".format(mem_type)
    mem_footer = "{0}\n".format(("*" * len(mem_header)))

    if 0 == size:
        size_str = "Not Available"
    else:
        size_str = "{0} MB".format(size)

    if 0 == speed:
        speed_str = "Not Available"
    else:
        speed_str = "{0} GT/s".format(speed)

    if 0 == freq:
        freq_str = "Not Available"
    else:
        freq_str = "{0} MHz".format(freq)

    if 0 == volt:
        volt_str = "Not Available"
    else:
        volt_str = "{0} V".format(volt)

    mcdram_cache_str = "{0} MB".format(mcdram_cache)
    mcdram_sys_str = "{0} MB".format(mcdram_sys)

    sys.stdout.write(mem_header)
    sys.stdout.write("Total {0} Memory: {1}\n".format(mem_type, size_str))
    if mem_type == "MCDRAM":
        sys.stdout.write("      {0} Used as Cache: {1}\n".format(mem_type, mcdram_cache_str))
        sys.stdout.write("      {0} Used as System Memory: {1}\n".format(mem_type, mcdram_sys_str))
    sys.stdout.write("{0} Speed: {1}\n".format(mem_type, speed_str))
    sys.stdout.write("{0} Frecuency: {1}\n".format(mem_type, freq_str))
    sys.stdout.write("{0} Voltage: {1}\n".format(mem_type, volt_str))
    if mem_type == "MCDRAM":
        sys.stdout.write("{0} Access(R/W) (Only for MCDRAM used as System Memory): {1}\n".format(mem_type, access))
    else:
        sys.stdout.write("{0} Access(R/W): {1}\n".format(mem_type, access))
    sys.stdout.write(mem_footer)

def test_memory_info(args):
    dimms = MemoryTopology(args)

    # Get Memory and Cluster configurations
    cluster_config = dimms.get_cluster_mode()
    memory_config = dimms.get_memory_mode()
    mem_MCDRAM_cache = dimms.get_MCDRAM_cache_info()

    # Get DDR Info
    ddr_size = dimms.get_total_ddr_memory()
    ddr_freq = dimms.get_ddr_freq()
    # Convert to GigaTransfers
    # TODO: Make sure this conversion is correct for all the cases
    ddr_speed = float(ddr_freq) / 1000
    ddr_volt = dimms.get_ddr_voltage()
    ddr_access = dimms.get_ddr_access(ddr_size)

    # Get MCDRAM info
    mcd_size = dimms.get_total_mcd_memory()
    mcd_cache = dimms.get_cache_mcd_memory()
    mcd_sys = dimms.get_sys_mcd_memory()
    mcd_freq = dimms.get_mcd_freq()
    # Convert to GigaTransfers
    # TODO: Make sure this conversion is correct for all the cases
    mcd_speed = float(mcd_freq) / 1000
    mcd_volt = dimms.get_mcd_voltage()
    mcd_access = dimms.get_mcd_access(mcd_size)

    sys.stdout.write("Total Memory: {0} MB\n".format(ddr_size + mcd_size))
    print_memory_config(memory_config, mem_MCDRAM_cache)
    print_cluster_config(cluster_config)
    print_memory_info("DDR", ddr_size, ddr_speed, ddr_freq, ddr_volt, ddr_access)
    print_memory_info("MCDRAM", mcd_size, mcd_speed, mcd_freq, mcd_volt, mcd_access, mcd_cache, mcd_sys)
    return 0
