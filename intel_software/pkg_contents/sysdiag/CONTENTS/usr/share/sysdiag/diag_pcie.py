# Copyright 2012-2017 Intel Corporation.
# 
# This software is supplied under the terms of a license agreement or
# nondisclosure agreement with Intel Corporation and may not be copied
# or disclosed except in accordance with the terms of that agreement.
import subprocess

import sys
import sys_utils
from sys_utils import run, debug_log


def test_pcie_info(args):
    try:
        pcie_info = PCIeInformation(args)
    except RuntimeError as e:
        sys.stderr.write("Error while obtaining PCI Express information.\n")
        sys.stderr.write("{0}\n".format(e))
        return -1
    sys_utils.debug_log(4, 'Number of PCIe Devices found: {0}'.format(len(pcie_info.pcie_devices)))
    sys_utils.debug_log(4, 'PCIe Devices found: {0}'.format(pcie_info.pcie_devices))

    if len(pcie_info.pcie_devices) <= 0:
        sys.stderr.write("There were no PCIe Devices reported by 'lspci -vv'.\n")
        return -2

    for pcie in pcie_info.pcie_devices:
        pcie_dev = pcie_info.get_pcie_dev(pcie)
        if not pcie_dev.get('Bridge', None):
            continue
        prefix = "PCIExpress device " + pcie_dev['Bridge'] + " " + pcie[1]
        print prefix + "    capable link speed: " + pcie_dev['CapSpeed']
        print prefix + "    capable link width: " + pcie_dev['CapWidth']
        print prefix + " negotiated link speed: " + pcie_dev['LnkSpeed']
        print prefix + " negotiated link width: " + pcie_dev['LnkWidth']
    return 0


class PCIeInformation(object):
    """Class that parses 'lspci -vv' output and create
    a list with each of the diferent PCI Express busses found.

    Each bus found can then be uses to get the information about
    that bus from the lspci command.

    """

    def __init__(self, args):
        self.args = args
        self.pcie_devices = list()
        self._get_pcie_bus()

    def __len__(self):
        return len(self.pcie_devices)

    def _get_pcie_bus(self):
        command = "lspci -vv"
        stdout, stderr, return_code = run(command)
        if return_code != 0:
            raise RuntimeError(
                "Error: 'lspci -vv' command failed with Return Code: {0}. Stderr: {1}".format(return_code, stderr))

        devices = stdout.split("\n\n")
        for device in devices:
            line = device.splitlines()
            if line and "PCI Express" in line[0]:
                self.pcie_devices.append(line[0].split()[0])

    def get_empty_pcie(self):
        pcie_dev = {'Bridge': '',
                    'LnkSpeed': '',
                    'LnkWidth': '',
                    'CapSpeed': '',
                    'CapWidth': ''}
        return pcie_dev

    def pcie_get_speed_width(self, line, start_from):
        comma = line.find(',', start_from)  # find first comma
        s = line[line.find('Speed ') + 6:comma]
        w = line[line.find('Width ') + 6:line.find(',', comma + 1)]
        return s, w

    def get_pcie_dev(self, bus):
        p = subprocess.Popen('lspci -vv -s ' + bus, shell=True, stdout=subprocess.PIPE)
        p.wait()
        pcie_dev = self.get_empty_pcie()
        for line in p.stdout:
            line = line.strip()
            debug_log(4, 'processing ' + line)
            if "PCI bridge: " in line:
                pcie_dev['Bridge'] = line[0:line.find(' ')]
            elif line[0:7] == 'LnkSta:':
                # example: LnkSta:      Speed 5GT/s, Width x16, TrErr- Train- SlotClk+ DLActive- BWMgmt- ABWMgmt-
                (s, w) = self.pcie_get_speed_width(line, 0)
                pcie_dev['LnkSpeed'] = s
                pcie_dev['LnkWidth'] = w
            elif line[0:7] == 'LnkCap:':
                # example: LnkCap:      Port #7, Speed 8GT/s, Width x16, ASPM L1, Exit Latency L0s <512ns, L1 <16us
                (s, w) = self.pcie_get_speed_width(line, line.find(',') + 1)
                pcie_dev['CapSpeed'] = s
                pcie_dev['CapWidth'] = w

        debug_log(4, "Returning pcie_dev = " + str(pcie_dev))
        return pcie_dev
