#  Copyright 2012-2017, Intel Corporation, All Rights Reserved.
#
# This software is supplied under the terms of a license
# agreement or nondisclosure agreement with Intel Corp.
# and may not be copied or disclosed except in accordance
# with the terms of that agreement.
#
#  Author:  Christopher M. Cantalupo

import os
import hashlib
import time
import re
import tempfile

import micp.kernel as micp_kernel
import micp.info as micp_info
import micp.common as micp_common
import micp.params as micp_params
import micp.version as micp_version

DEFAULT_SCORE_TAG = 'Computation.Avg'

paramFileFormat = \
"""\
Generated Intel(R) LINPACK data file (lininput_xeon64)
Intel(R) LINPACK data
1
{matrixSize}
{leadDim}
{numRep}
4
"""


class linpack(micp_kernel.Kernel):
    def __init__(self):
        self.name = 'linpack'
        self.param_validator = micp_params.LINPACK_VALIDATOR
        self._paramNames = ['omp_num_threads',
                            'matrix_size',
                            'num_rep',
                            'lead_dim']
        self._paramDefaults = {'omp_num_threads':'228',
                               'matrix_size':'8192',
                               'num_rep':'3',
                               'lead_dim':None}

        info = micp_info.Info()
        maxCount = info.num_cores()
        # limit the matrix to fit in memory with a GB to spare
        maxMemory = info.mic_memory_size() - 1024**3
        if maxMemory <= 0:
            raise RuntimeError('micinfo reports less than one GB of GDDR memory on card')

        self._categoryParams = {}
        # Self check always performed
        self._categoryParams['test'] = [' ']

        # Define the scaling categories
        sizeConfig = self._calculate_default_size_config()
        args = '--omp_num_threads {0} --matrix_size {1} --num_rep 3 --lead_dim {2}'
        self._categoryParams['scaling'] = [args.format(maxCount, matriz_size, leading_dim)
                                           for matriz_size, leading_dim in sizeConfig
                                           if matriz_size*leading_dim*8 < maxMemory]
        self._categoryParams['optimal'] = self._categoryParams['scaling'][-1:]

        self._categoryParams['scaling_quick'] = self._categoryParams['scaling'][:4]
        self._categoryParams['optimal_quick'] = self._categoryParams['scaling'][3:4]

        step = int(round(maxCount/10.0))
        if step < 4:
            step = 4
        coreConfig = range(step, maxCount, step)
        coreConfig.append(maxCount)
        self._categoryParams['scaling_core'] = [args.format(coreCount, 8192, 8256)
                                                for coreCount in coreConfig]

        self._leadDimMap = self._calculate_leading_dim_map()
        self._set_defaults_to_optimal()


    @staticmethod
    def _calculate_leading_dim_map():
        """creates a dictionary that maps the size of a matrix
        with its leading dimension"""
        small_matrixes = [(value, value+64) for value in range(256, 40192+512, 512)]
        large_matrixes = [(value, value+1088) for value in range(1024, 39936+1024, 1024)]
        return dict(small_matrixes + large_matrixes)


    @staticmethod
    def _calculate_default_size_config():
        """returns a list of tuples (matrix_size, matrix_leading_dimension)
        containing the default linpack parameters"""
        matrix_size = range(2048, 38912, 2048)
        leading_dim = range(2112, 38976, 2048)
        return [(size, lead) for size, lead in zip(matrix_size, leading_dim)]

    def _do_unit_test(self):
        return True

    def offload_methods(self):
        return['native', 'auto', 'local']


    def _search_path_to_file(self, directory, binary_name):
        """searches binary_name, in the given directory, returns the fullpath
        to the first match"""
        for root, dirs, files in os.walk(directory):
            if binary_name in files:
                return os.path.join(root, binary_name)
        raise micp_kernel.NoExecutableError


    def path_host_exec(self, offType):
        if offType == 'auto' or offType == 'local':
            if micp_common.is_platform_windows():
                execName = 'linpack_xeon64.exe'
            else:
                execName = 'xlinpack_xeon64'
            if 'MKLROOT' in os.environ:
                return self._search_path_to_file(os.environ['MKLROOT'], execName)
            else:
                raise micp_kernel.NoExecutableError("MKLROOT not in environment.  Source composer's compilervars.sh before running linpack")
        return None

    def path_dev_exec(self, offType):
        if offType == 'native':
            if 'MKLROOT' in os.environ:
                if micp_version.MIC_PERF_CARD_ARCH == 'k1om':
                    mic_linpack = 'xlinpack_mic'
                else:
                    mic_linpack = 'xlinpack_xeon64'
                return self._search_path_to_file(os.environ['MKLROOT'], mic_linpack)
            else:
                raise micp_kernel.NoExecutableError("MKLROOT not in environment.  Source composer's compilervars.sh before running linpack")
        return None

    def path_aux_data(self, offType):
        result = []
        if offType == 'native':
            result.append(self.mic_library_find('libiomp5.so'))
        return result

    def param_type(self):
        return 'file'

    def parse_desc(self, raw):
        failRE = re.compile('fail', re.IGNORECASE)
        # Raise exception if self check failed
        if failRE.search(raw):
            eMessage = [line for line in raw.splitlines()
                        if failRE.search(line) or
                        line.strip().endswith('Check')]
            eMessage.insert(0, '')
            eMessage = '\n'.join(eMessage)
            raise micp_kernel.SelfCheckError(eMessage)
        # Create a dictionary from lines containing one : character
        dd = dict([tuple([ll.strip() for ll in line.split(':')])
                   for line in raw.splitlines()
                   if ':' in line and line.find(':') == line.rfind(':')])
        # Pull out important keys
        matrixSize = dd['Number of equations to solve (problem size)']
        numThreads = dd['Number of threads']
        numIt = dd['Number of trials to run']
        # Create output description
        result = '{0} x {0} MKL DP LINPACK with {1} threads and {2} iterations'.format(matrixSize, numThreads, numIt)
        return result

    def parse_perf(self, raw):
        lines = [ll.strip() for ll in raw.splitlines()]
        lineNum = lines.index('Performance Summary (GFlops)') + 3
        speed = lines[lineNum].split()[3]
        result = {}
        result[DEFAULT_SCORE_TAG] = {'value':speed, 'units':'GFlops', 'rollup':True}
        return result

    def environment_dev(self):
        return {'LD_LIBRARY_PATH':'/tmp',
                'KMP_AFFINITY':'explicit,granularity=fine,proclist=[1-{0},0]'.format(micp_info.Info().num_cores()*4-1)}

    def environment_host(self):
        info = micp_info.Info()
        numThreads = info.num_cores() - 1
        maxMemory = str(int((info.mic_memory_size() - 1024**3)/(1024**3)))
        mic_lb = {'MIC_BUFFERSIZE':'256M',
                'MKL_MIC_ENABLE':'1',
                'MKL_MIC_DISABLE_HOST_FALLBACK':'1',
                'MIC_ENV_PREFIX':'MIC',
                'MIC_OMP_NUM_THREADS':str(numThreads),
                'KMP_AFFINITY':'compact,1,0',
                'MIC_KMP_AFFINITY':'explicit,granularity=fine,proclist=[1-' + str(numThreads) + ':1]',
                'MIC_USE_2MB_BUFFERS':'16K',
                'MKL_MIC_MAX_MEMORY':maxMemory + 'G'}

        mic_sb = {'KMP_AFFINITY':'compact,1,0',
                  'OMP_NUM_THREADS':str(info.num_cores()),
                  'USE_2MB_BUFFERS':'16K'}

        if micp_common.is_selfboot_platform():
            return mic_sb
        else:
            return mic_lb


    def param_file(self, param):
        matrixSize = param.get_named('matrix_size')
        numRep = param.get_named('num_rep')
        leadDim = param.get_named('lead_dim')
        if leadDim is None:
            if int(matrixSize) in self._leadDimMap:
                leadDim = self._leadDimMap[int(matrixSize)]
            else:
                raise RuntimeError('linpack lead_dim not specified and matrix size not in lda table')
        paramStr = paramFileFormat.format(matrixSize=matrixSize,
                                          leadDim=leadDim,
                                          numRep=numRep)
        hasher = hashlib.md5()
        hasher.update(paramStr)
        md5hash = hasher.hexdigest()

        paramFileName = '{0}_{1}_{2}.par'.format(os.getpid(), int(1000*time.time()), md5hash[0:8])
        paramFileName = os.path.join(tempfile.mkdtemp(), paramFileName)

        fid = open(paramFileName, 'w')
        fid.write(paramStr)
        fid.close()
        return paramFileName

    def independent_var(self, category):
        if category == 'scaling_core':
            return 'omp_num_threads'
        return 'matrix_size'


    def param_for_env(self):
        return ['omp_num_threads']


    def get_process_modifiers(self):
        """On the processor bind SMP linpack memory to node 1 when MCDRAM
        memory is available"""
        if micp_info.Info().is_processor_mcdram_available():
            return ['numactl', '--membind=1']
        else:
            return []

    def _ordering_key(self, stat):
        return float(stat.perf[DEFAULT_SCORE_TAG]['value'])
