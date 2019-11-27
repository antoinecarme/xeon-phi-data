#  Copyright 2012-2017, Intel Corporation, All Rights Reserved.
#
# This software is supplied under the terms of a license
# agreement or nondisclosure agreement with Intel Corp.
# and may not be copied or disclosed except in accordance
# with the terms of that agreement.
#
#  Author:  Christopher M. Cantalupo

"""
Module for collecting and presenting performance statistics.
"""

import sys
import os
import re
import math
import cPickle
import distutils.version
import platform

from micp.common import mp_print, CAT_DESC, CAT_PERF

try:
    import matplotlib.pyplot
    _disablePlotting = False
except (ImportError, RuntimeError):
    _disablePlotting = True

import info as micp_info
import common as micp_common
import version as micp_version

class Stats(object):
    """
    Class stores the statistics gathered from a single call to a kernel
    """
    def __init__(self, params, desc, perf):
        self.params = params
        self.desc = desc
        if (type(perf) is not dict or
            not all([type(dd) is dict for dd in perf.values()])):
            raise TypeError('Stats must be initialized with a nested dictionary')
        if not all(['value' in dd and 'units' in dd for dd in perf.values()]):
            raise KeyError('perf dictionary must contain "value", and "units" keys')
        self.perf = perf

    def __str__(self, rolledUp=True):
        result = []
        result.append(self.desc)
        result.append('Parameters:  ' + self.params.__str__())
        result.extend(['{0}      {1}'.format(self.perf[tag]['value'], self.perf[tag]['units'])
                       for tag in self.perf if rolledUp == False or self.perf[tag].get('rollup', True)])
        return '\n'.join(result)

    def csv(self, rolledUp=True):
        result = []
        result.append('{0}'.format(self.desc))
        result.append(self.params.csv())
        result.extend([str(self.perf[tag]['value'])
                       for tag in self.perf if rolledUp == False or self.perf[tag].get('rollup', True)])
        return ', '.join(result)

    def csv_header(self, rolledUp=True):
        result = []
        result.append('DESCRIPTION')
        result.append(self.params.csv_header())
        result.extend(['{0} ({1})'.format(tag, self.perf[tag]['units'])
                       for tag in self.perf if rolledUp == False or self.perf[tag].get('rollup', True)])
        return ', '.join(result)

    def csv_short_form(self, offload):
        result = []
        result = [', '.join([self.desc,
                             offload,
                             str(self.perf[tag]['value']),
                             '{0} ({1})'.format(tag, self.perf[tag]['units']),
                             str(self.params)])
                  for tag in self.perf if self.perf[tag].get('rollup', True)]
        result = '\n'.join(result)
        return result

    def __sub__(self, ref, rolledUp=True):
        result = None
        for tag in self.perf:
            if rolledUp == False or self.perf[tag].get('rollup', True):
                if tag.find('Time') != -1:
                    sign = -1.0
                else:
                    sign = 1.0
                relError = sign * (float(self.perf[tag]['value']) - float(ref.perf[tag]['value'])) / float(ref.perf[tag]['value'])
                if result is None or relError < result:
                    result = relError
        return result


    def statistical_comparison(self, model, kernel, offload):
        """
        Given a statistical model (mean and stdev) for a particular kernel and
        offload method, calculates if the result is statistically speaking
        correct, returns None if it is or returns the relative error if is not.
        """
        for tag in self.perf:
            mean = None
            stdev = None
            try:
                mean, stdev = model[kernel][offload][self.desc]
            except KeyError:
                error_msg = ("ERROR: Statistical information"
                             " for is '{0}' not available")
                print error_msg.format(self.desc)
                raise

            # using 3 standard deviations for comparison to cover ~99.7% of cases
            max_expected = float(mean) + 3*float(stdev)
            min_expected = float(mean) - 3*float(stdev)
            actual_performance = float(self.perf[tag]['value'])

            perf_greater_than_min = actual_performance > min_expected
            perf_less_than_max = actual_performance < max_expected
            if perf_greater_than_min and perf_less_than_max:
                return None
            elif not perf_greater_than_min:
                return (actual_performance-min_expected)/min_expected
            else:
                return (actual_performance-max_expected)/max_expected


    def reprint(self):
        mp_print(self.desc, CAT_DESC)
        for tag in sorted(self.perf.keys()):
            perf_text = '{0} {1} {2}'.format(tag, self.perf[tag]['value'], self.perf[tag]['units'])
            if self.perf[tag].get('rollup', True):
                perf_text = perf_text + " R"
            mp_print(perf_text, CAT_PERF)

class StatsCollection(object):
    """
    Class that stores a collection of Stats and can print and plot the
    statistics.
    """
    def __init__(self, runArgs, tag=None, info=None):
        if not info:
            self.info = micp_info.Info()
        else:
            self.info = info

        self.runArgs = runArgs
        badChar = re.compile(r'[^\w.-]')
        if not tag:
            if self.runArgs['paramCat']:
                tagFmt = '{software}-{ver}_{off}_{par}'
            else:
                tagFmt = '{software}-{ver}_{off}'

            if micp_common.is_selfboot_platform():
                software_name = 'micperf'
                tagFmt = '{sku}_{os}_' + tagFmt
            else:
                software_name = 'mpss'
                # append device name for KNX coprocessors
                tagFmt = '{sku}_' + tagFmt
                tagFmt += '_mic{idx}'

            _os_name, _os_version, __ = platform.dist()
            os_name = '{0}-{1}'.format(_os_name, _os_version)

            self.tag = tagFmt.format(sku=self.info.mic_sku(),
                                     ver=micp_info.micperf_version(),
                                     off=self.runArgs['offMethod'].replace('_', '-'),
                                     par=self.runArgs['paramCat'].replace('_', '-'),
                                     idx=self.runArgs['devIdx'],
                                     software=software_name,
                                     os=os_name)
            # replace characters that don't belong in a file name with a dash
            self.tag = badChar.sub('-', self.tag)
        else:
            self.tag = badChar.sub('-', tag)
            if self.tag != tag:
                sys.stderr.write('WARNING: Replaced non-alphanumeric characters in tag.\n')
                sys.stderr.write('     IN: {0}\n'.format(tag))
                sys.stderr.write('    OUT: {0}\n'.format(self.tag))

        mcdram_available = micp_info.Info().is_processor_mcdram_available()
        if micp_common.is_selfboot_platform() and mcdram_available:
            self.tag = 'mcdram_{0}'.format(self.tag)
        elif micp_common.is_selfboot_platform() and not mcdram_available:
            self.tag = 'ddr_{0}'.format(self.tag)

        self._store = {}
        self._xName = {}
        self._extended = False

    def __str__(self, rolledUp=True):
        result = []
        if rolledUp == True:
            result.append(micp_common.star_border('ROLLED UP'))
        for kernelName in sorted(self._store.keys()):
            result.append(micp_common.star_border(kernelName))
            myOffloadList = [off for off in self._store[kernelName].keys() if split_offload(off)[1] == self.tag]
            otherOffloadList = [off for off in self._store[kernelName].keys() if split_offload(off)[1] != self.tag]
            offloadList = sorted(myOffloadList) + sorted(otherOffloadList)
            for offloadName in offloadList:
                if len(self._store[kernelName][offloadName]) > 0:
                    result.append(micp_common.star_border(offloadName))
                    if self.runArgs['paramCat'].startswith('optimal'):
                        optimalStat = self.get_optimal_stat(kernelName, offloadName)
                        result.append(optimalStat.__str__())
                    else:
                        for stats in self._store[kernelName][offloadName]:
                            result.append(stats.__str__())
                            result.append('')
                        result.append(micp_common.star_border(''))
            result.append(micp_common.star_border(''))
        result.append(micp_common.star_border(''))
        return '\n'.join(result)

    def append(self, kernelName, offloadName, xName, stats):
        offloadName = offloadName +  '__' + self.tag
        if kernelName in self._store:
            if offloadName in self._store[kernelName]:
                self._store[kernelName][offloadName].extend(stats)
            else:
                self._store[kernelName][offloadName] = list(stats)
        else:
            self._store[kernelName] = {}
            self._store[kernelName][offloadName] = list(stats)
        if kernelName not in self._xName:
            self._xName[kernelName] = xName
        elif self._xName[kernelName] != xName:
            raise NameError('xName must be the same for all stats associated with a kernel')

    def extend(self, other):
        self._extended = True
        deprecationDict = {'1dfft': 'onedfft',
                           '1dfft_streaming': 'onedfft_streaming',
                           '2dfft': 'twodfft',
                           'dgemm_mkl': 'dgemm',
                           'sgemm_mkl': 'sgemm',
                           'linpack_dp': 'linpack',
                           'stream_mccalpin': 'stream'}
        for kk in other._store:
            if kk in deprecationDict:
                other._store[deprecationDict[kk]] = other._store.pop(kk)
        for kk in other._store:
            for oo in other._store[kk]:
                if oo.startswith('linux_native'):
                    other._store[kk][oo[6:]] = other._store[kk].pop(oo)

        # update gemm tags to full name
        for gemmk in ('sgemm', 'dgemm'):
            try:
                for offTag in [offTag for offTag in other._store[gemmk]
                               if offTag.startswith('pragma')]:
                    statList = other._store[gemmk][offTag]
                    for stat in statList:
                        try:
                            stat.perf['Host.Computation.Avg'] = stat.perf.pop('Computation.Avg')
                        except KeyError:
                            pass
            except KeyError:
                pass
            try:
                for offTag in [offTag for offTag in other._store[gemmk]
                               if offTag.startswith('native')]:
                    statList = other._store[gemmk][offTag]
                    for stat in statList:
                        try:
                            stat.perf['Task.Computation.Avg'] = stat.perf.pop('Computation.Avg')
                        except KeyError:
                            pass
            except KeyError:
                pass

        kernelSet = set(self._store.keys()) & set(other._store.keys())
        for kernel in kernelSet:
            myOffloadNames = [split_offload(offload)[0]
                              for offload in self._store[kernel]]
            for otherOffload in other._store[kernel]:
                if split_offload(otherOffload)[0] in myOffloadNames:
                    offload = otherOffload
                    while offload in self._store[kernel]:
                        offload = offload + ' ext'
                    self._store[kernel][offload] = list(other._store[kernel][otherOffload])

    def csv(self, rolledUp=True):
        result = []
        if rolledUp:
            result.append('ROLLED UP\n')
        for kernelName in sorted(self._store.keys()):
            for offloadName in sorted(self._store[kernelName].keys()):
                if len(self._store[kernelName][offloadName]) > 0:
                    off, tag = split_offload(offloadName)
                    if tag is None:
                        result.append('KERNEL, OFFLOAD')
                        result.append('{0}, {1}\n'.format(kernelName, off))
                    else:
                        result.append('KERNEL, OFFLOAD, TAG')
                        result.append('{0}, {1}, {2}\n'.format(kernelName, off, tag))
                    if self.runArgs['paramCat'].startswith('optimal'):
                        optimalStat = self.get_optimal_stat(kernelName, offloadName)
                        result.append(optimalStat.csv_header(rolledUp))
                        result.append(optimalStat.csv(rolledUp))
                        result.append('')
                        result.append('')
                    else:
                        result.append(self._store[kernelName][offloadName][0].csv_header(rolledUp))
                        for stats in self._store[kernelName][offloadName]:
                            result.append(stats.csv(rolledUp))
                        result.append('')
                        result.append('')
        return '\n'.join(result)

    def csv_short_form(self):
        result = ['DESCRIPTION, OFFLOAD, PERFORMANCE, NAME (UNITS), PARAMETERS']
        for kernelName in sorted(self._store.keys()):
            for offloadName in sorted(self._store[kernelName].keys()):
                if len(self._store[kernelName][offloadName]) > 0:
                    off, tag = split_offload(offloadName)
                    if self.runArgs['paramCat'].startswith('optimal'):
                        optimalStat = self.get_optimal_stat(kernelName, offloadName)
                        result.append(optimalStat.csv_short_form(off))
                    else:
                        result.extend([stats.csv_short_form(off) for stats in self._store[kernelName][offloadName]])
        result.append('')
        return '\n'.join(result)

    def csv_write(self, outDir, rolledUp=True):
        result = self.csv()
        blocked = result.split('KERNEL, OFFLOAD, TAG')
        blocked.pop(0)
        for block in blocked:
            blockLines = block.strip().splitlines()
            blockLines.append('')
            fileName = os.path.join(outDir, blockLines[0].replace(', ', '_') + '.csv')
            fid = open(fileName, 'w')
            fid.write('\n'.join(blockLines[2:]))
            fid.close()

    def get_optimal_stat(self, kernelName, offloadName):
        statList = self.get_stat_list(kernelName, offloadName)
        if len(statList) == 0:
            return None
        optimalStat = statList[0]
        for stat in statList:
            dd = stat - optimalStat
            if dd > 0:
                optimalStat = stat
        return optimalStat

    def get_stat_list(self, kernelName, offloadName):
        if '__' in offloadName:
            return self._store[kernelName][offloadName]
        else:
            allOff = self._store[kernelName].keys()
            extensions = set([split_offload(oo)[1] for oo in allOff])
            extensions.discard(None)
            extensions = list(extensions)
            extensions.sort()
            result = []
            for ex in extensions:
                try:
                    result.extend(self._store[kernelName]['__'.join((offloadName, ex))])
                except KeyError:
                    pass
            return result

    def _pretty_x_label(self, kernelName):
        if self._xName[kernelName] == 'num_core':
            label = 'Number of Cores'
        elif (self._xName[kernelName] == 'num_thread' or
              self._xName[kernelName] == 'omp_num_threads' or
              self._xName[kernelName] == 'n_num_thread'):
            label = 'Number of Threads'
        elif (self._xName[kernelName] == 'matrix_size' or
              self._xName[kernelName] == 'f_first_matrix_size'):
            label = 'Matrix Dimension (NxN)'
        else:
            label = self._xName[kernelName]
        matplotlib.pyplot.xlabel(label)

    def _pretty_y_label(self, rolledTag, rolledUnits):
        if rolledTag.find('Time') != -1:
            matplotlib.pyplot.ylabel('Time ({0}) lower values better'.format(rolledUnits))
        else:
            matplotlib.pyplot.ylabel('Rate ({0}) higher values better'.format(rolledUnits))


    def _get_rolled_coords(self, kernelName, offloadName):
        coords = []
        rolledTag = ''
        rolledUnits = ''
        floatRe = re.compile(r'[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?')
        for stats in self._store[kernelName][offloadName]:
            try:
                # Try to get xval from the params object
                xVal = stats.params.get_named(self._xName[kernelName])
                # Find the first floating point value in the string
                xVal = floatRe.search(xVal)
                xVal = float(xVal.group())
            except (NameError, ValueError, AttributeError, TypeError):
                xVal = None
            except NotImplementedError:
                break
            for tag in stats.perf:
                if stats.perf[tag].get('rollup', True):
                    rolledTag = tag
                    rolledUnits = stats.perf[tag]['units']
                    if xVal is None:
                        # Check the perf dictionary for xVal (internal scaling)
                        xVal = float(stats.perf[tag][self._xName[kernelName]])
                    coords.append((xVal,float(stats.perf[tag]['value'])))
                    break
        coords  = zip(*coords)
        return coords, rolledTag, rolledUnits

    def _add_sku(self, fig):
        """
        Put the basic mic info onto a figure
        """
        if '_extended' not in self.__dict__ or not self._extended:
            fig.text(0.15, 0.78, self.info.micinfo_basic())

    def _pretty_legend(self, offloadName):
        skuName = {}
        skuName['a8be6b3a'] = 'ES1-SKU1'
        skuName['f9a7ba85'] = 'ES1-SKU3'
        skuName['818f4c45'] = 'ES2-A1330'
        skuName['42ce8a31'] = 'ES2-P1310'
        skuName['960d4f11'] = 'ES2-P1640'
        skuName['cedb26f1'] = 'ES2-P1750'

        skuName['3d78e18f'] = 'ES1-SKU1'
        skuName['55a17e06'] = 'ES1-SKU3'
        skuName['1b10dafb'] = 'ES2-A1330'
        skuName['86eb3645'] = 'ES2-P1310'
        skuName['67ed1134'] = 'ES2-P1640'
        skuName['6c519075'] = 'ES2-P1750'

        skuName['ef01820a'] = 'ES2-P1310'
        skuName['95d82af5'] = 'ES2-A1330'
        skuName['ca6ad37b'] = 'ES2-P1640'
        skuName['6f8a700d'] = 'ES2-P1750'
        skuName['6abf35a9'] = 'B1QS-5110P'
        skuName['ae739d23'] = 'B1QS-7110P'

        result = offloadName.replace('__', ' ')
        if (offloadName.find('__') == offloadName.rfind('__') and
            offloadName.find('__') != -1):
            off, tag = split_offload(offloadName)
            tagSplit = tag.split('_')
            if len(tagSplit) == 5:
                hwhash, version, allOff, category, devID = tuple(tagSplit)
                if hwhash in skuName:
                    hwhash = skuName[hwhash]
                elif devID != 'mic0':
                    if devID.startswith('mic0 '):
                        devID = devID[5:]
                    hwhash = ' '.join((hwhash, devID))
                if version == 'mpss-2.1.3126-14':
                    version = 'Alpha2'
                elif version == 'mpss-2.1.3653-8':
                    version = 'Beta'
                elif version == 'mpss-2.1.4346-16':
                    version = 'Gold'
                result = ' '.join((off, version, hwhash))
        return result


    def includes_results_for_single_kernel(self):
        """returns True if object includes valid (non empty) results for a
        single (kernel,offload)"""
        if not self._store.keys():
            return False

        kernel_results = 0
        for kernel in self._store:
            valid_results = [True for results in self._store[kernel].values() if results]
            kernel_results += len(valid_results)

        return kernel_results == 1


    def plot(self, outDir=''):
        global _disablePlotting
        if _disablePlotting:
            sys.stderr.write('WARNING: Plotting disabled. Either matplot could not be found, or the display could not be opened.\n')
            return

        for kernelName in sorted(self._store.keys()):
            didPlot = False
            for offloadName in sorted(self._store[kernelName].keys()):
                if len(self._store[kernelName][offloadName]) > 0:
                    coords, rolledTag, rolledUnits = self._get_rolled_coords(kernelName, offloadName)
                    if didPlot == False:
                        fig = matplotlib.pyplot.figure()
                        didPlot = True
                    if offloadName.find('__') != -1:
                        mark = 'x:'
                    else:
                        mark = 'o--'
                    if is_exp_spacing(coords[0]):
                        matplotlib.pyplot.semilogx(coords[0], coords[1], mark, label=self._pretty_legend(offloadName))
                    else:
                        matplotlib.pyplot.plot(coords[0], coords[1], mark, label=self._pretty_legend(offloadName))

                    matplotlib.pyplot.hold(True)

            if didPlot:
                try:
                    matplotlib.pyplot.title(kernelName + ' ' + rolledTag.replace('.', ' '))
                    self._pretty_x_label(kernelName)
                    self._pretty_y_label(rolledTag, rolledUnits)
                    matplotlib.pyplot.legend(loc='best', prop={'size':'x-small'})
                    self._add_sku(fig)
                    if outDir:
                        if self.tag:
                            figureName = '{output_dir}/plot_{axis_name}_{kernel}_{tag}.png'
                        else:
                            figureName = '{output_dir}/plot_{axis_name}_{kernel}.png'
                        figureName = figureName.format(
                                            output_dir=outDir,
                                            kernel=kernelName,
                                            axis_name=self._xName[kernelName],
                                            tag=self.tag)
                        matplotlib.pyplot.savefig(figureName)
                    else:
                        matplotlib.pyplot.show()
                except KeyError:
                    pass

    def plot_all(self, outDir=''):
        global _disablePlotting
        if _disablePlotting:
            sys.stderr.write('WARNING: Plotting disabled. Either matplot could not be found, or the display could not be opened.\n')
            return

        fig = matplotlib.pyplot.figure()
        aRolledTag = ''
        aRolledUnits = ''
        aKernelName = ''
        exec_kernels = []
        exec_kernels_axis = []

        for kernel in self._store.keys():
            valid_kernel_results = [True for results in self._store.get(kernel).values() if results]
            if any(valid_kernel_results):
                exec_kernels.append(kernel)
                exec_kernels_axis.append(self._xName.get(kernel))

        if len(set(exec_kernels_axis)) != 1:
            errStr = 'x axis names do not match\n'
            errStr = errStr + self._xName.values().__str__()
            raise NameError(errStr)

        for kernelName in sorted(self._store.keys()):
            for offloadName in sorted(self._store[kernelName].keys()):
                coords, rolledTag, rolledUnits = self._get_rolled_coords(kernelName, offloadName)
                if coords:
                    aRolledTag = rolledTag
                    aRolledUnits = rolledUnits
                    aKernelName = kernelName
                    if offloadName.find('__') != -1:
                        mark = 'x:'
                    else:
                        mark = 'o--'
                    legLabel = kernelName + ' ' + self._pretty_legend(offloadName)
                    if is_exp_spacing(coords[0]):
                        matplotlib.pyplot.semilogx(coords[0], coords[1], mark, label=legLabel)
                    else:
                        matplotlib.pyplot.plot(coords[0], coords[1], mark, label=legLabel)

                    matplotlib.pyplot.hold(True)
        try:
            matplotlib.pyplot.title(rolledTag.replace('.', ' '))
            self._pretty_x_label(aKernelName)
            self._pretty_y_label(aRolledTag, aRolledUnits)
            matplotlib.pyplot.legend(loc='lower right')
            self._add_sku(fig)
            if outDir:
                if self.tag:
                    figureName = '{output_dir}/plot_all_{axis_name}_{tag}.png'
                else:
                    figureName = '{output_dir}/plot_all_{axis_name}.png'
                figureName = figureName.format(
                                    output_dir=outDir,
                                    axis_name=self._xName[aKernelName],
                                    tag=self.tag)
                matplotlib.pyplot.savefig(figureName)
            else:
                matplotlib.pyplot.show()
        except KeyError:
            pass


    def _get_kernel_perf_results(self, ref, kernel, offload):
        """given the kernel name, the offload method and a the reference results
        returns the tuple (list_of_actual_results, list_of_expected_results)"""
        if self.runArgs['paramCat'].startswith('optimal'):
            return ([self.get_optimal_stat(kernel, offload)],
                    [ref.get_optimal_stat(kernel, offload)])

        return (self.get_stat_list(kernel, offload),
                ref.get_stat_list(kernel, offload))


    def _statistical_test(self, sharedKeys, statistical_model, ref):
        """performance statistical regression test"""
        max_regression = 0
        best_performance = 0
        for (kernel, offload) in sharedKeys:
            actual_res, __ = self._get_kernel_perf_results(ref, kernel, offload)
            all_valid_results = [res for res in actual_res if res is not None]
            for kernel_result in all_valid_results:
                # do performance regression test
                result = kernel_result.statistical_comparison(
                                        statistical_model, kernel, offload)

                if result is not None:
                    if result < 0:
                        self._print_regression(kernel, offload, result, kernel_result.desc)
                        if result < max_regression:
                            max_regression = result
                    else:
                        if result > best_performance:
                            best_performance = result

        test_failed = max_regression != 0
        res = max_regression if test_failed else best_performance
        self._print_perf_test_verdict(test_failed, res)

    def _relative_error_test(self, sharedKeys, margin, ref):
        """performance regression test based on relative errors"""
        maxRegr = 0
        for (kk,oo) in sharedKeys:
            selfStatList, refStatList = self._get_kernel_perf_results(ref, kk, oo)
            all_valid_results = [(actual, expected) for (actual, expected)
                                 in zip(selfStatList, refStatList)
                                 if actual is not None and expected is not None]
            for (actual, expected) in all_valid_results:
                # Difference between stats is the relative error on the rolled stats
                relError = actual - expected
                if relError < -margin:
                    if relError < maxRegr:
                        maxRegr = relError
                    self._print_regression(kk, oo, -relError, actual.desc)
                elif relError > margin and relError > maxRegr and maxRegr >= 0:
                    maxRegr = relError
        test_failed = maxRegr < -margin
        self._print_perf_test_verdict(test_failed, maxRegr)


    @staticmethod
    def _print_regression(kernel, offload, error, desc):
        """print regression result for a single value"""
        message = '[----------] {0} {1} {2:.4f}% ({3})'
        print '[----------] Performance regression'
        print message.format(kernel, offload, error*100, desc)


    @staticmethod
    def _print_perf_test_verdict(test_failed, max_regression):
        """print final performance regression test result,
        raises an exception if the test fails"""
        if test_failed:
            print '[----------] Worst regression {0:.4f}%'.format(-max_regression*100)
            print '[  FAILED  ] 1 test.'
            raise PerfRegressionError
        else:
            if max_regression != 0:
                print '[----------] Best improvement {0:.4f}%'.format(max_regression*100)
                print '[  PASSED  ] 1 test.'
            else:
                print '[----------] Measured performance within margin of reference data'
                print '[  PASSED  ] 1 test.'



    def perf_regression_test(self, margin=0.04, ref=None, statistical_model={}):
        """statistical or relative error performance tests based on input arguments"""
        if ref is None:
            scs = StatsCollectionStore()
            ref = scs.get_for_regression_test(self.runArgs['paramCat'])

        jointKernels = list(set(self._store.keys()) &
                            set(ref._store.keys()))

        # get list of valid (kernel, offload method) combinations
        sharedKeys = []
        for kk in jointKernels:
            selfOffloads = [off.split('__')[0] for off in self._store[kk].keys()]
            refOffloads = [off.split('__')[0] for off in ref._store[kk].keys()]
            jointOff = list(set(selfOffloads) &
                            set(refOffloads))
            sharedKeys.extend([(kk,oo) for oo in jointOff])

        if statistical_model:
            self._statistical_test(sharedKeys, statistical_model, ref)
        else:
            self._relative_error_test(sharedKeys, margin, ref)


class StatsCollectionStore(object):
    def __init__(self, pickleDir=None):
        if pickleDir:
            self._pickleDir = pickleDir
        else:
            self._pickleDir = os.environ.get('MIC_PERF_DATA', micp_version.MIC_PERF_DATA)

        try:
            dirList = os.listdir(self._pickleDir)
        except OSError:
            dirList = []

        self._storedTags = [fileName[15:-4] for fileName in dirList
                            if fileName[-4:] == '.pkl' and fileName[:15] == 'micp_run_stats_']
        self._storedTags.sort(reverse=True)

    def get_by_tag(self, tag):
        if tag not in self._storedTags:
            tagSplit = tag.split(':')
            if len(tagSplit) == 2 and tagSplit[0] == 'filter':
                result = self.get_by_filter(tagSplit[1])
                if len(result) > 0:
                    return result[0]
            elif len(tagSplit) == 2 and tagSplit[0] == 'test':
                return self.get_for_regression_test(tagSplit[1])
            return None
        else:
            fileName = os.path.join(self._pickleDir, 'micp_run_stats_' + tag + '.pkl')
            return cPickle.load(open(fileName, 'rb'))

    def get_by_filter(self, filt, refInfo=None):
        if refInfo is None:
            refInfo = micp_info.Info()
        result = []
        methodName = 'is_' + filt
        if methodName not in dir(refInfo):
            raise NameError('micp_stats.get_by_filter:  Filter named {0} is not valid'.format(filt))
        filt = refInfo.__getattribute__(methodName)
        for tag in self._storedTags:
            statsColl = self.get_by_tag(tag)
            if filt(statsColl.info):
                result.append(statsColl)
        return result

    def get_for_regression_test(self, testName=''):
        result = self.get_by_filter('same_sku')
        if len(result) == 0:
            raise RuntimeError('Could not find reference file with same sku')

        thisVersion = micp_info.micperf_version()
        result = [sc for sc in result if distutils.version.LooseVersion(sc.info.micperf_version()) <= thisVersion]
        if len(result) == 0:
            raise RuntimeError('Could not find reference file with same sku and lower or equal mpss version')

        thatVersion = max([distutils.version.LooseVersion(sc.info.micperf_version()) for sc in result]).vstring

        result = [sc for sc in result if sc.info.micperf_version() == thatVersion and testName in sc.tag]

        if len(result) == 0:
            raise RuntimeError('Could not find reference file with same sku and lower version and tag containing {0}'.format(testName))
        if len(result) > 1:
            raise RuntimeError('Found multiple reference files that match comparison criterion')
        return result[0]

    def get_all(self):
        return [self.get_by_tag(tag) for tag in self._storedTags]

    def stored_tags(self):
        """returns a list containing the stored tags, clients
        should validate that the list is not empty"""
        return list(self._storedTags)


    @staticmethod
    def _processor_field_names():
        """returns tuple (header, kernels, offloads, parameters) the last three
        elements are lists that indicate the name of the rows and columns used
        to populate the table micpcsv generates when invoked without arguments.
        Actual information is extracted from pickle files, notice lists have
        the same length and order matters"""

        header = [' ',
                  'SGEMM (GF/s)',
                  'DGEMM (GF/s)',
                  'STREAM (Triad) (GB/s)',
                  'HPLinpack (GF/s)',
                  'HPCG (GF/s)',
                  'SMP Linpack (GF/s)']
        header = ', '.join(header)

        kernels = ['sgemm',
                   'dgemm',
                   'stream',
                   'hplinpack',
                   'hpcg',
                   'linpack']

        offloads = [['local']*6]

        parameters = ['K_size',
                      'K_size',
                      'omp_num_threads',
                      'problem_size',
                      'problem_size',
                      'matrix_size']

        return header, kernels, offloads, parameters

    @staticmethod
    def _coprocessor_field_names():
        """returns tuple (header, kernels, offloads, parameters) the last three
        elements are lists that indicate the name of the rows and columns used
        to populate the table micpcsv generates when invoked without arguments.
        Actual information is extracted from pickle files, notice lists have
        the same length and order matters"""
        header = [' ',
                  'SGEMM pragma/native (GF/s)',
                  'DGEMM pragma/native (GF/s)',
                  'SMP Linpack native (GF/s)',
                  'PCIeDownload pragma/scif (GB/s)',
                  'PCIeReadback pragma/scif (GB/s)',
                  'STREAM (Triad) (GB/s)']
        header = ', '.join(header)

        kernels = ['sgemm',
                   'dgemm',
                   'linpack',
                   'shoc_download',
                   'shoc_readback',
                   'stream']

        offloads = [['pragma', 'native'],
                    ['pragma', 'native'],
                    ['native'],
                    ['pragma', 'scif'],
                    ['pragma', 'scif'],
                    ['native']]

        parameters = ['K_size',
                      'K_size',
                      'matrix_size',
                      'DESCRIPTION',
                      'DESCRIPTION',
                      'omp_num_threads']

        return header, kernels, offloads, parameters


    def csv(self):
        scalingTags = [tag
                       for tag in self._storedTags
                       if 'scaling' in tag]

        if micp_common.is_selfboot_platform():
            header, kernels, offloads, parameters = self._processor_field_names()
        else:
            header, kernels, offloads, parameters = self._coprocessor_field_names()

        result = []
        for tag in scalingTags:
            statsColl = self.get_by_tag(tag)
            name = statsColl.info.mic_sku()
            line = [name]
            pline = ['Parameters']
            for kernel, offload, parameter in zip(kernels, offloads, parameters):
                thisResult = []
                thisParams = []
                for thisOffload in offload:
                    offloadTag = [oo for oo in statsColl._store[kernel] if oo.startswith(thisOffload)][0]
                    stat = statsColl.get_optimal_stat(kernel, offloadTag)
                    if parameter == 'DESCRIPTION':
                        paramVal = str(int(stat.desc.split()[-1][:-2])/1024) + 'MB'
                    else:
                        paramVal = stat.params.get_named(parameter)
                    stat = float(stat.csv().split(', ')[-1])
                    stat = '{0:.2f}'.format(stat)
                    thisResult.append(stat)
                    thisParams.append(paramVal)
                thisResult = ' / '.join(thisResult)
                thisParams = ' / '.join(thisParams)
                line.append(thisResult)
                pline.append(thisParams)
            result.append(', '.join(line) + '\n' + ', '.join(pline))
        result.sort()
        result.insert(0,header)
        result = '\n'.join(result)
        return result

class PerfRegressionError(micp_common.MicpException):
    """Performance regression"""
    def micp_exit_code(self):
        return micp_common.E_PERF

    def __str__(self):
        return 'Performance regression'

def is_exp_spacing(coordList):
    if len(coordList) < 3:
        return False

    # handle case where x axis is e.g [0, 0, 0, 0], this represents a vertical line
    if len(set(coordList)) == 1:
        return False

    epsilon = 1e-6
    logCoordList = [math.log(coord) for coord in coordList]
    firstDiff = logCoordList[1] - logCoordList[0]
    if firstDiff == 0:
        return False

    diff = [b - a for a, b in zip(logCoordList,logCoordList[1:])]
    return all([abs((dd - firstDiff)/firstDiff) < epsilon for dd in diff])

def split_offload(offloadName):
    splitPos = offloadName.find('__')
    if splitPos == -1:
        off = offloadName
        tag = None
    else:
        off = offloadName[:splitPos]
        tag = offloadName[splitPos+2:]
    return off, tag
