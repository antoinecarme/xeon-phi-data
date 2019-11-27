# Copyright 2012-2017 Intel Corporation.
# 
# This software is supplied under the terms of a license agreement or
# nondisclosure agreement with Intel Corporation and may not be copied
# or disclosed except in accordance with the terms of that agreement.

import subprocess
import tempfile
import os
import sys
import time
import platform
import re

# Verbosity level
HOST_SYSTEM = platform.system()
PLATFORM = platform.platform()
running_on_linux = (HOST_SYSTEM == 'Linux')
running_on_windows = (HOST_SYSTEM == 'Windows')
UNIT_TEST = False
if "sysdiag" and "ut" in os.getcwd():
    UNIT_TEST = True

# Debug
debug_level = 2
PROC_CPUINFO = '/proc/cpuinfo'

# Log directory
script_path = os.path.abspath(os.path.dirname(__file__))
TEMP_DIR = tempfile.gettempdir()
LOGS_DIR = os.path.join(TEMP_DIR, 'logs')


def am_i_root():
    euid = os.geteuid()
    if euid != 0:
        print "Error: You must be root to run this script."
        return False
    return True


if not am_i_root() and not UNIT_TEST:
    sys.exit(1)


def check_log_dir():
    if not os.path.exists(LOGS_DIR):
        try:
            os.mkdir(LOGS_DIR)
        except OSError as e:
            print e
            print "Do you have write permissions in: {0} folder?".format(script_path)
            print "Exiting from script."
            sys.exit(2)
    else:
        if not os.access(LOGS_DIR, os.W_OK):
            print "The {dir} exists but is not writeable.".format(dir=LOGS_DIR)
            # We are supposed to be root/admin so we are able to change the
            # permissions
            # but that would be intrusive, rather the user to change it.
            print "Please make the directory writeable."
            if running_on_linux:
                print "Hint: use chmod +w {dir}".format(dir=LOGS_DIR)
            sys.exit(2)


check_log_dir()


def debug_log(level, msg):
    if level <= debug_level:
        print msg
        return msg


def set_debug_level(lvl):
    global debug_level
    debug_level = lvl
    debug_log(3, "Debug level set to " + str(lvl))
    return debug_level


def is_xeon_phi_200():
    sys_models = '(87|133)'
    regexp = 'model\t\t: ' + sys_models
    with open(PROC_CPUINFO, 'r') as cpuinfo:
        for line in cpuinfo.readlines():
            if re.match(regexp, line):
                return True
        return False


def run(command, timeout=0):
    """Run command on host

    :param command: command to be executed
    :param timeout: time to wait for the command to complete, 0 for unlimited.
                    After timeout completes, the command is killed.
    :return:
    """

    # Initialize temp file for stdout. Will be removed when closed.
    outfile = tempfile.SpooledTemporaryFile()
    errfile = tempfile.SpooledTemporaryFile()

    try:
        # Invoke process
        proc = subprocess.Popen(command, stdout=outfile,
                                stderr=errfile, shell=True)
        # Wait for process completion
        # Poll for completion if wait time was set
        if timeout:
            while proc.poll() is None and timeout > 0:
                time.sleep(1)
                timeout -= 1
                # It is needed to print it with sys.stdout otherwise
                # if using print the information is printed after
                # the command is killed
                sys.stdout.write(".")
                sys.stdout.flush()
                # Kill process if wait time exceeded
                if timeout <= 0 and not proc.poll():
                    terminate_process(proc.pid, sudo=True)
                    break
            print ""

        proc.communicate()
        # Read stdout from file
        outfile.seek(0)
        errfile.seek(0)
        stdout = outfile.read()
        stderr = errfile.read()
        outfile.close()
        errfile.close()

    except:
        raise

    finally:
        # Make sure the file is closed
        outfile.close()
        errfile.close()

    retcode = proc.returncode

    return stdout, stderr, retcode


def terminate_process(process_pid, sudo=False):
    """ Terminate a running process for a given PID number

    For a given PID, tries to terminate a process by using operating system
    native tools such as "kill" in Linux or "taskkill" in Windows.

    Args:
        process_pid: PID of the process to be terminated

    Returns:
        retcode: When successful returns 0, otherwise the exit code of the
                 utility used to terminate the process.
    """
    retcode = -1

    sudo = "sudo" if sudo else ""
    cmd = "{0} kill -9 {1}".format(sudo, process_pid)

    stdout, stderr, retcode = run(cmd)

    return retcode


def modprobe(module, params=''):
    debug_log(3, 'Inserting ' + module + ' with params: (' + params + ')')
    command = "/sbin/modprobe {0} {1}".format(module, params)
    _, __, return_code = run(command)
    if return_code != 0:
        print 'Error: ' + module + ' insertion failed return code = ' + str(return_code)
    return return_code


def to_secs(_time=""):
    """ Receives a string in a form of XY: ZW: AB, representing the time
    XY : hours
    ZW : minutes
    AB : seconds
    :returns: The number of seconds in the time received
    :rtype: int
    """
    _time = _time.split(':')
    hours, minutes, seconds = _time
    hours = int(hours)
    minutes = int(minutes)
    seconds = int(seconds)
    return hours * 3600 + minutes * 60 + seconds

# libmemkind global variables
LDCONFIG_COMMAND, _, _ = run("PATH=$PATH:/sbin/:/usr/sbin; which ldconfig")
MEMKIND_LIBRARY = "libmemkind.so"
FIND_LIBRARY_CMD = LDCONFIG_COMMAND.strip() + " -p | grep \"{0}\""


def dependencies():
    """ Here are listed all the dependencies of the tool
    to be used:

        numactl
        msr module
        dmi_sysfs module
        libmemkind

    :return: True if all dependencies are installed, False otherwise.
    :rtype: bool
    """
    deps_installed = True
    if running_on_linux:
        _deps = ["numactl", ]
        modules = ["msr", "dmi_sysfs"]
        for item in _deps:
            command = 'which {0}'.format(item)
            stdout, stderr, return_code = run(command)
            if return_code != 0:
                sys.stderr.write("{0} is not in $PATH. Is it installed?".format(item))
                deps_installed = False
        for _module in modules:
            params = ''
            if "suse" in PLATFORM.lower():
                params = '--allow-unsupported'
            if modprobe(_module, params) == 0:
                continue
            else:
                sys.stderr.write("Unable to load {0} module.".format(_module))
                deps_installed = False
        # Find libmemkind.so using ldconfig command:
        stdout, stderr, return_code = run(FIND_LIBRARY_CMD.format(MEMKIND_LIBRARY))
        stdout.strip()
        if return_code != 0 or not stdout:
            sys.stderr.write("libmemkind.so does not exists, please install memkind package.\n")
            deps_installed = False

    return deps_installed
