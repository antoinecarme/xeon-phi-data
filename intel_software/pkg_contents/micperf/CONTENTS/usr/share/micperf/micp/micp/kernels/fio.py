#  Copyright 2017, Intel Corporation, All Rights Reserved.
#
# This software is supplied under the terms of a license
# agreement or nondisclosure agreement with Intel Corp.
# and may not be copied or disclosed except in accordance
# with the terms of that agreement.

import os
import math
import sys
import tempfile
import subprocess
import json
import shutil
from distutils.spawn import find_executable

import micp.kernel as micp_kernel
import micp.info as micp_info
import micp.common as micp_common
import micp.params as micp_params

from micp.kernel import raise_parse_error

# FIO CONFIG FILE
# this template will be used to generate config file,
# following variables will be replaced in runtime:
# {file_size} size of single file
# {num_jobs} amount of jobs created
# {test_dir} test files directory
CONST_FIO_CONFIG_FILE = """[global]
directory={test_dir}
iodepth=32
stonewall
buffered=1
thread
group_reporting
bs=4k
rw=randread
fallocate=posix
[Multiple-files]
description=Test of paralell read from multiple files
numjobs={num_jobs}
filesize={file_size}"""

# message displayed if fio executable has not been found
CONST_NO_FIO_TEXT = """FIO was not found on this system.
please install it using a standard package manager
or visit https://github.com/axboe/fio
to download, build and install it directly.
Please make sure the directory containing the FIO
binary is added to the system PATH variable."""

# name of config file to be created
CONST_FIO_CONFIG_FILE_NAME = 'fio.cfg'

# default fio parameters for config file
CONST_FIO_PARAMS = {'numjobs':'10', 'size':'16MB'}

DEFAULT_SCORE_TAG = 'Computation.Avg'

class fio(micp_kernel.Kernel):
    """Implements kernel interface for FIO benchmark"""

    def __init__(self):
        self.name = 'fio'
        self._working_directory = None
        self.score = None

        info = micp_info.Info()
        maxCount = info.num_cores()

        self.param_validator = micp_params.NO_VALIDATOR
        self._categoryParams = {}
        self._paramNames = CONST_FIO_PARAMS.keys()
        self._paramDefaults = CONST_FIO_PARAMS

        self._categoryParams['test'] = [' ']

        args_all = ''
        args_scaling = ''
        args_scaling_core = ''

        for key in CONST_FIO_PARAMS:
            args_all += '--{0} {1} '.format(key, CONST_FIO_PARAMS[key])
            args_scaling += '--{0} {1} '.format(key,
                ('{0}' if key == 'size' else CONST_FIO_PARAMS[key]))
            args_scaling_core += '--{0} {1} '.format(key,
                ('{0}' if key == 'numjobs' else CONST_FIO_PARAMS[key]))

        core_scale = range(1, maxCount + 1, 10)
        size_scale = ['4MB', '8MB', '16MB', '32MB', '64MB']
        self._categoryParams['optimal'] = [ args_all ]
        self._categoryParams['scaling'] = [args_scaling.format(size)
                                           for size in size_scale]
        self._categoryParams['scaling_quick'] = self._categoryParams['scaling']

        self._categoryParams['optimal_quick'] = [ args_all ]
        self._categoryParams['scaling_core'] = \
            [args_scaling_core.format(core_count) for core_count in core_scale]

    def _do_unit_test(self):
        return True

    def offload_methods(self):
        return ['local']

    def path_host_exec(self, offload_method):
        # check if fio exists
        if offload_method is 'local':
            path = self._path_exec(micp_kernel.LIBEXEC_HOST, 'fio')
            if path:
                return path
            else:
                micp_common.mp_print(CONST_NO_FIO_TEXT, micp_common.CAT_ERROR)
        return None

    def path_dev_exec(self, offType):
        """returns None, Intel Xeon Phi Coprocessors not supported"""
        return None

    def param_type(self):
        """ FIO uses config file """
        return 'file'

    def clean_up(self, local, remote, remote_shell=None):
        """ extend default clean_up so it removed also fio test files directory """
        super(fio, self).clean_up(local, remote, remote_shell)

        if self._working_directory and os.path.exists(self._working_directory):
            shutil.rmtree(self._working_directory)

    def get_fixed_args(self):
        return ['--output-format=json']

    def parse_desc(self, raw):
        err_msg = "JSON parse error. [{}] in:\n{}"
        try:
            rjson = json.loads(raw)
        except ValueError as e:
            micp_common.mp_print(err_msg.format(e, raw), micp_common.CAT_ERROR,
                wrap=False)
            raise micp_kernel.SelfCheckError("")

        # workaround for ambiguous fio fix: if io_kbytes exists then io_bytes
        # is expressed in B otherwise the value is in kB
        try:
            read_node = rjson["jobs"][0]["read"]
        except KeyError:
            raise_parse_error(raw)

        if "io_kbytes" in read_node:
            total_size = rjson["jobs"][0]["read"]["io_kbytes"]
        elif "io_bytes" in read_node:
            total_size = rjson["jobs"][0]["read"]["io_bytes"]
        else:
            raise_parse_error(raw)

        try:
            desc_list = []
            desc_list += [rjson["fio version"]]
            desc_list += [rjson["jobs"][0]["desc"]]
            desc_list += ["total size: {} kB".format(total_size)]
            desc = "; ".join(desc_list)
            self.score = rjson["jobs"][0]["read"]["bw"]
        except (ValueError, KeyError) as e:
            raise_parse_error(raw)

        return desc

    def parse_perf(self, raw):
        # parsed already in parse_desc, no point parsing twice
        if self.score is None:
            raise_parse_error(raw, "Score not found in JSON output.")

        result = {}
        result[DEFAULT_SCORE_TAG] = \
            {'value':self.score, 'units':'kB/s', 'rollup':True}
        return result

    def independent_var(self, category):
        if category == 'scaling_core':
            return 'numjobs'
        return 'size'

    def param_file(self, param):
        numjobs_p = param.get_named('numjobs')
        size_p = param.get_named('size')

        self._working_directory = \
            tempfile.mkdtemp(prefix='micperf_fio_data_')

        config_file_content = CONST_FIO_CONFIG_FILE.format(file_size=size_p,
            num_jobs=numjobs_p, test_dir=self._working_directory)

        config_file_path = os.path.join(
            self._working_directory, CONST_FIO_CONFIG_FILE_NAME)

        with open(config_file_path, 'w') as fid:
            fid.write(config_file_content)

        return config_file_path

    def _ordering_key(self, stat):
        return float(stat.perf[DEFAULT_SCORE_TAG]['value'])

