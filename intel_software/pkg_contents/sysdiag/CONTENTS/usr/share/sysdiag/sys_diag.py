#!/usr/bin/python
# Copyright 2012-2017 Intel Corporation.
# 
# This software is supplied under the terms of a license agreement or
# nondisclosure agreement with Intel Corporation and may not be copied
# or disclosed except in accordance with the terms of that agreement.

__version__ = "0.93"
import sys
import argparse
import sys_utils
import diag_memory
import diag_pcie
import diag_power
import diag_system


INTERACTIVE = True
TEST_RESULTS = []


if not sys_utils.am_i_root():
    sys.exit(1)


if not sys_utils.dependencies():
    sys.stderr.write("Warning, not all required tools are installed in the system.\n")
    sys.stderr.write("This will affect the verification provided by this script.\n")
    sys.stderr.write("Please install the required dependencies.\n")
    # ToDO. Decide if we are going to exit from the script or what?


class TestType:
    auto, manual = range(2)


########
# Manage input and launch section
########

def run_test(test_name, test_function, args):
    """
    """
    test_info = dict()
    print '#############   STARTED   ' + test_name + '   #############'
    test_info[test_name] = test_function(args)
    if test_info[test_name] == 0:
        print '#############   PASSED  ' + test_name + '   #############'
    else:
        print '#############   FAILED    ' + test_name + '   #############'
    TEST_RESULTS.append(test_info)
    return test_info[test_name]


def run_all_tests(args):
    failed = 0
    for item in TESTS:
        # omit first and last which should be 'Exit' and 'All'
        if item[5] == TestType.auto:
            sys_utils.debug_log(3, "Running " + item[0])
            if run_test(item[1], item[2], args) != 0:
                failed += 1
    return failed

def print_menu():
    print
    for i, val in enumerate(TESTS):
        print str(i) + ": " + val[3]


def get_answer():
    ret = 0
    while True:
        try:
            ret = int(raw_input("Select option: "))
        except ValueError:
            print "Please enter an integer."
        else:
            if 0 <= ret < len(TESTS):
                break
            else:
                print "Invalid option. Try again."

    return ret


def process_options(args):
    global INTERACTIVE
    arg = vars(args)
    sys_utils.debug_log(4, "args = " + str(arg))
    for key, value in arg.iteritems():
        if key == 'output' and value is not None:
            INTERACTIVE = False
        if value:
            for _test in TESTS:
                if key == _test[0]:
                    sys_utils.debug_log(3, "Found test to run " + key)
                    INTERACTIVE = False
                    run_test(_test[1], _test[2], args)
                    break


def exit(_):
    sys_utils.debug_log(1, "Exiting.")
    sys.exit(0)


# Tests fields:
# key (used as an cmd arg), short name, function called, help string, action for arg, automatic vs. manual test
TESTS = [
    ['exit', "Exit", exit, "End script", 'store_true', TestType.manual],
    ['mem', "Memory info", diag_memory.test_memory_info, "Run DDR/MCDRAM diagnostics",
     'store_true', TestType.auto],
    ['pci', "PCIExpress info", diag_pcie.test_pcie_info, "Run PCIExpress diagnostics",
     'store_true', TestType.auto],
    ['t_cpu_info', "CPU-Info", diag_power.test_cpu_info, "Show CPU detailed information.",
     'store_true', TestType.auto],
    ['r_pstates', "P-States", diag_power.test_pstates, "Show detail P-States information per CPU Core",
     'store_true', TestType.auto],
    ['system', "System info", diag_system.dump_system_info, "Stores debug system information to a compressed file.",
     'store_true', TestType.auto],
    ['all', "All", run_all_tests, "Runs all tests sequentially", 'store_true', TestType.manual],
]


def main():
    global INTERACTIVE
    exit_code = 0

    parser = argparse.ArgumentParser(description="SYS Diagnosing tool.")

    # Common optional parameters
    parser.add_argument("-v", "--version", action='version',
                        version=__version__)

    parser.add_argument("-d", "--debug",
                        dest="verbosity", default=2, type=int,
                        choices=[1, 2, 3, 4], help="Increase debug level")

    parser.add_argument("-o", "--output", help='Redirect the tests output to a file <OUTPUT>',
                        dest="output")

    parser.add_argument("-i", "--interval", default="00:05:00",
                        help="Runtime interval for tests. Format: 'HH:MM:SS'. Default: 00:05:00")

    parser.add_argument("-n", "--numactl",
                        help='Run benchmark tool with numactl argument(s).'
                             'Warning: you must use \'=\' when passing argument(s), i.e. -n=\'--all\'')

    for val in TESTS:
        if val[0] != 'exit':
            sys_utils.debug_log(4, "Adding argument " + val[0])
            parser.add_argument('-' + val[0][0], '--' + val[0], help=val[3], action=val[4])

    args = parser.parse_args()


    # TODO check the arguments here
    if not sys_utils.is_xeon_phi_200():
        print 'WARNING!!!'
        print 'Running on a non-supported platform. This script is intended for Intel(R) Xeon Phi(TM) 200 hardware!'
        raw_input('Type <Enter> to continue...')

    try:
        if args.output:
            sys.stdout = open(args.output, 'w')
    except AttributeError as e:
        pass
    except IOError as e:
        sys.stderr.write("Error: Cannot open file: " + args.output + "\n")
        sys.exit(-550)

    sys_utils.set_debug_level(args.verbosity)

    process_options(args)

    sys_utils.debug_log(3, "Interactive = " + str(INTERACTIVE))
    if INTERACTIVE:
        while True:
            print_menu()
            answer = get_answer()
            print "\nSelected " + str(answer)
            run_test(TESTS[answer][1], TESTS[answer][2], args)

    for _dict in TEST_RESULTS:
        for test, test_result in _dict.iteritems():
            if test_result is not 0:
                if test_result is None:
                    test_result = 1
                exit_code += test_result

    return exit_code

if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
