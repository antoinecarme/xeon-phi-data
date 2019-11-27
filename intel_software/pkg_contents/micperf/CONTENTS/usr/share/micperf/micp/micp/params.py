#  Copyright 2012-2017, Intel Corporation, All Rights Reserved.
#
# This software is supplied under the terms of a license
# agreement or nondisclosure agreement with Intel Corp.
# and may not be copied or disclosed except in accordance
# with the terms of that agreement.
#
#  Author:  Christopher M. Cantalupo

"""
Module containing the fully featured Params class, a positional only
ParamsPos class and the decorator class ParamsDrop which removes some
parameters.
"""

import shlex
import copy
import getopt
import re

import micp.common as micp_common

# available parameters type validators
XGEMM_VALIDATOR = 'gemm'
STREAM_VALIDATOR = 'stream'
SHOC_VALIDATOR = 'shoc'
LINPACK_VALIDATOR = 'linpack'
HPLINPACK_VALIDATOR = 'hplinpack'
HPCG_VALIDATOR = 'hpcg'
NO_VALIDATOR = 'none'

class MicpParamsHelpError(micp_common.MicpException):
    """request help message"""
    def micp_exit_code(self):
        return micp_common.E_PARSE

class UnknownParamError(micp_common.MicpException):
    """requested kernel parameters are incorrect"""
    def micp_exit_code(self):
        return micp_common.E_PARSE

class InvalidParamTypeError(micp_common.MicpException):
    """Will be raised to indicate a parameter doesn't have the right type"""
    def micp_exit_code(self):
        return micp_common.E_PARSE

class Params(object):
    """
    Stores the parameters for a particular run and will
    return the parameters in a variety of formats.
    """
    def __init__(self, params, paramNames, defaults={}, paramQuiet=[], paramValidatorName=NO_VALIDATOR):
        self._paramNames = list(paramNames)
        self._params = dict([(pn,None) for pn in paramNames])
        self._defaults = dict(defaults)
        self._paramQuiet = list(paramQuiet)


        if isinstance(params, str):
            try:
                params = shlex.split(params)
            except ValueError as err:
                message = ('ERROR: Unable to parse input parameters "{0}": {1}.')
                raise UnknownParamError(message.format(params, str(err)))

        is_short_option = re.compile('^-[a-zA-Z]$').match
        paramValidator = ParamTypeValidatorFactory(paramValidatorName)

        if not any([pp.startswith('--') or is_short_option(pp) for pp in params]):
            for pn, pp in zip(self._paramNames, params):
                self._params[pn] = paramValidator.validate_param(pn, pp)
        else:
            i = 0
            while i < (len(params)):
                if params[i].startswith('--'):
                    thisName = params[i][2:]
                    if thisName == 'help':
                        raise MicpParamsHelpError
                    if thisName not in self._paramNames:
                        raise UnknownParamError('Unknown kernel parameter: {0}'.format(thisName))
                    i += 1
                    if i < len(params) and not params[i].startswith('-'):
                        self._params[thisName] = paramValidator.validate_param(thisName, params[i])
                        i += 1
                    else:
                        self._params[thisName] = paramValidator.validate_param(thisName, '')
                elif is_short_option(params[i]):
                    thisFlag = params[i][1]
                    if thisFlag == 'h':
                        raise MicpParamsHelpError
                    thisName = [pn for pn in self._paramNames if pn.startswith(thisFlag)]
                    if len(thisName) == 0:
                        raise UnknownParamError('Unknown kernel flag: {0}'.format(thisFlag))
                    if len(thisName) > 1:
                        error = ('INTERNAL ERROR: Initializing with flags, but more than'
                                ' one parameter name starts with the same character {0}')
                        raise NameError(error.format(thisName))
                    thisName = thisName[0]
                    i += 1
                    if i < len(params) and not is_short_option(params[i]):
                        self._params[thisName] = paramValidator.validate_param(thisName, params[i])
                        i += 1
                    else:
                        self._params[thisName] = paramValidator.validate_param(thisName, '')
                else:
                    message = 'Malformed parameters, invalid token \'{0}\' found at position {1}'
                    raise UnknownParamError(message.format(params[i], i))


        for pp in paramNames:
            if self._params[pp] is None:
                try:
                    self._params[pp] = self._defaults[pp]
                except KeyError:
                    self._params[pp] = None

    def __str__(self):
        return ' '.join(['--' + pn + ' ' + self._params[pn]
                         for pn in self._paramNames
                         if self._params[pn] != None])

    def csv(self):
        return ', '.join([value_to_print(self._params[pn])
                          for pn in self._paramNames])

    def csv_header(self):
        return ', '.join(self._paramNames)

    def pos_list(self):
        return  [self._params[pn] if self._params[pn] != '' else '1'
                 for pn in self._paramNames
                 if self._params[pn] != None and pn not in self._paramQuiet]


    def pos_str(self):
        return ' '.join(self.pos_list())

    def value_list(self):
        return self.value_str().split()

    def value_str(self):
        return ' '.join(['--' + pn + ' ' + self._params[pn]
                         for pn in self._paramNames
                         if self._params[pn] != None and pn not in self._paramQuiet])

    def flag_list(self):
        return self.flag_str().split()

    def flag_str(self):
        return ' '.join(['-' + pn[0] + ' ' + self._params[pn]
                         for pn in self._paramNames
                         if self._params[pn] != None and pn not in self._paramQuiet])

    def num_param(self):
        return len(self.pos_list())

    def get_named(self, name):
        try:
            return self._params[name]
        except KeyError:
            raise NameError

    def set_named(self, name, value):
        if name in self._paramNames:
            self._params[name] = value
        else:
            raise NameError

class ParamsPos(object):
    """
    Class which implements the methods of Params that require only
    positional arguments.
    """

    def __init__(self, params):
        if type(params) == str:
            self._params = params.split()
        else:
            self._params = params

    def __str__(self):
        return self.pos_str()

    def csv(self):
        return ', '.join([value_to_print(param) for param in self.pos_list()])

    def csv_header(self):
        return ', '.join(self._paramNames)

    def pos_list(self):
        return list(self._params)

    def pos_str(self):
        return ' '.join(self._params)

    def num_param(self):
        return len(self.pos_list())

    def value_str(self):
        raise NotImplementedError

    def value_list(self):
        raise NotImplementedError

    def get_named(self, name):
        raise NotImplementedError

    def set_named(self, name, value):
        raise NotImplementedError

class ParamsGetopt(object):
    """
    Class which implements the methods of Params but allows for mixing
    of short form, long form and positional arguements as is done by
    POSIX getopt.
    """
    def __init__(self, params, paramNames, options, long_options=[], defaults={}):
        """
        INPUT PARAMETERS
        ----------------
        params:       A string or list of command line arguments.

        paramNames:   A list of tuples, the first element of each
                      tuple is the name of a parameter.  The other
                      tuple elements are any short form, long form, or
                      position index that are associated with that
                      parameter name.

        options:      Option string as is specified for getopt
                      e.g. 'hxy:z:'.  See getopt.gnu_getopt
                      documentation for details.

        long_options: Long option list as is specified for getopt
                      e.g. ['help', 'foobar'].  See getopt.gnu_getopt
                      documentation for details.

        defaults:     A dictionary mapping parameter names to default
                      values.

        PRIVATE ATTRIBUTES
        ------------------
        _optionMap:   maps an option (e.g. '--num_reps' or '-n' or 3)
                      to the parameter name
        _nameMap:     maps a parameter name to the long option, or if
                      no long option the short option or if no short
                      option the position index.
        _paramNames:  a list of parameter names
        _defaults:    maps from paramter name to default value

        """
        self._optionMap = {}
        self._nameMap = {}
        self._paramNames = []
        self._defaults = dict(defaults)
        if type(params) is str:
            params = shlex.split(params)
        try:
            # Use getopt to parse params
            self._opts, self._args = getopt.gnu_getopt(params, options, long_options)
        except getopt.GetoptError:
            if ' '.join(params).strip() in ('--help', '-h'):
                # Create help message
                message = ['    options: description, default']
                for pn in paramNames:
                    name = pn[0]
                    options = ' '.join([str(option) for option in pn[1:]])
                    if name in defaults:
                        message.append('    {0}: {1}, {2}'.format(options, name, defaults[name]))
                    else:
                        message.append('    {0}: {1}'.format(options, name))
                message = '\n'.join(message)
                raise MicpParamsHelpError(message)
            else:
                raise
        # parse paramNames, and create optionMap
        posIndex = 0
        for pn in paramNames:
            if type(pn) is str:
                self._optionMap[posIndex] = pn
                self._paramNames.append(pn)
                posIndex = posIndex + 1
            elif type(pn) in (list, tuple):
                name = pn[0]
                for option in pn[1:]:
                    self._optionMap[option] = name
                self._paramNames.append(name)
            else:
                raise TypeError('paramNames elements must be of type str, list or tuple')
        # Create inverse of optionMap: nameMap
        for option, name in self._optionMap.items():
            if name not in self._nameMap:
               self._nameMap[name] = option
            elif option.startswith('--') and (type(self._nameMap[name]) is int or not self._nameMap[name].startswith('--')):
               self._nameMap[name] = option
            elif type(self._nameMap[name]) is int:
                self._nameMap[name] = option
        # Remove defaults that params has specified
        defaultUsed = dict(defaults)
        for option, val in self._opts:
            name = self._optionMap[option]
            try:
                defaultUsed.pop(name)
            except KeyError:
                pass
        for ii in range(len(self._args)):
            try:
                defaultUsed.pop(self._optionMap[ii])
            except KeyError:
                pass
        # Substitute in default values
        if defaultUsed:
            argsEnum = zip(range(len(self._args)), self._args)
            for name, value in defaultUsed.items():
                option = self._nameMap[name]
                if type(option) is int:
                    argsEnum.append((option, value))
                else:
                    self._opts.append((option, value))
            if argsEnum:
                argsEnum.sort()
                position, self._args = zip(*argsEnum)
                if position != tuple(range(len(position))):
                    raise RuntimeError('Default positional parameters not given in sequence')
        # Check to make sure that each variable name is specified only once
        found = [False for ii in range(self.num_param())]
        for option, val in self._opts:
            name = self._optionMap[option]
            index = self._paramNames.index(name)
            if found[index] == True:
                raise RuntimeError('Parameter named {0} is specified twice: {1}'.format(name, self.__str__()))
            found[index] = True

    def __str__(self):
        """
        Returns a string of the command line arguements.
        """
        result = ['{0} {1}'.format(option, val)
                  for option, val in self._opts
                  if val is not None]
        result.extend(self._args)
        return ' '.join(result)

    def csv(self):
        """
        Returns a comma separated list of the parameter values in the
        order of the parameter names.
        """
        result = ['' for ii in range(len(self._paramNames))]
        options, vals = [list(x) for x in zip(*self._opts)]
        options.extend(range(len(self._args)))
        vals.extend(self._args)
        for option, val in zip(options, vals):
            name = self._optionMap[option]
            result[self._paramNames.index(name)] = val
        return ', '.join(result)

    def csv_header(self):
        """
        Returns a comma separated list of the parameter names.
        """
        return ', '.join(self._paramNames)

    def num_param(self):
        """
        Return the total number of parameters allowed (not the number
        set).
        """
        return len(self._paramNames)

    def get_named(self, name):
        """
        Return the value of a parameter given its parameter name.
        """
        for option, val in self._opts:
            if self._optionMap[option] == name:
                return val
        for index, arg in zip(range(len(self._args)), self._args):
            if self._optionMap[index] == name:
                return arg
        return None

    def set_named(self, name, value):
        """
        Set the value of a parameter given its parameter name.
        """
        optsEnum = zip(*self._opts)
        optsEnum.append(range(len(self._opts)))
        optsEnum = zip(*optsEnum)
        for option, oldVal, ii in optsEnum:
            if self._optionMap[option] == name:
                self._opts[ii] = (option, value)
                return
        for ii in range(len(self._args)):
            if self._optionMap[ii] == name:
                self._args[ii] = value
                return
        option = self._nameMap[name]
        if type(option) is int:
            self._args.insert(option, value)
        else:
            self._opts.append((option, value))

class ParamsDrop(object):
    """
    Decorator class for the Params and ParamsPos classes which will
    drop the last parameters.
    """
    def __init__(self, params, numDrop, paramMax):
        self._params = copy.deepcopy(params)
        if numDrop < 1:
            raise ValueError('numDrop must be greater than 0')
        self._numDrop = numDrop
        if type(params) != ParamsPos:
            self._params._paramQuiet = params._paramNames[paramMax:paramMax + numDrop]

    def __str__(self):
        return self._params.__str__()

    def csv(self):
        return ', '.join([value_to_print(param) for param in self.pos_list()])

    def csv_header(self):
        return ', '.join(self._params._paramNames[:-self._numDrop])

    def pos_list(self):
        return self._params.pos_list()

    def pos_str(self):
        return ' '.join(self._params.pos_str().split())

    def value_list(self):
        return self._params.value_list()

    def value_str(self):
        return self._params.value_str()

    def flag_list(self):
        return self._params.flag_list()

    def flag_str(self):
        return self._params.flag_str()

    def num_param(self):
        return len(self.pos_list())

    def get_named(self, name):
        return self._params.get_named(name)

    def set_named(self, name, value):
        self._params.set_named(name, value)



def value_to_print(value):
    if value is None:
        return 'False'
    elif value == '':
        return 'True'
    else:
        return value

class ParamTypeValidator(object):
    """Abstract class, concrete classes should derive and populate
    the dictionary _validators properly. This dictionary maps the
    name of the parameters to a function that can be used to validate
    the correct type of given parameter. e.g.

        self._validators = {'number_of_iterations' : is_integer}

    Where is_integer is a function that takes a single parameter (the
    value) and raises a ValueError exception if value is not an integer.
    """

    def __init__(self):
        """class cannot be instantiated"""
        raise NotImplementedError("Abstract Class")

    def validate_param(self, param, value):
        """receives the name of the parameter to validate and the value that
        is intended to be used, on success validate_param() will return the
        same value otherwise it will raise an InvalidParamTypeError
        exception."""

        if param not in self._validators.keys():
            message = ('INTERNAL ERROR: _validator dictionary was not'
                       ' populated correctly, missing key: "{0}"')
            raise RuntimeError(message.format(param))

        param_type_validator = self._validators[param]
        try:
            param_type_validator(value)
        except ValueError as err:
            message = 'Invalid type for {0}\'s parameter "{1}", {2}'
            raise InvalidParamTypeError(message.format(self.name, param, str(err)))

        # this point will only be reached if the type validator succeeds
        return value


class NoParamTypeValidator(ParamTypeValidator):
    """do not perform any check on the parameters type"""
    def __init__(self):
        """override base class constructor,
        nothing to be done in this case"""
        pass

    def validate_param(self, param, value):
        """override validate_param() behavior to """
        return value


class GEMMParamTypeValidator(ParamTypeValidator):
    """Parameter type validator class for SGEMM and DGEMM kernels"""
    def __init__(self):
        self.name = 'XGEMM'
        valid_mmodes = 'NN|NT|TN|TT|0|1|2|3'
        self._validators = {
            'i_num_rep' : micp_common.unsigned_int,
            'n_num_thread' : micp_common.signed_int,
            'm_mode' : lambda param: micp_common.custom_type(param, valid_mmodes),
            # M, N and K accept also -1 which means default value
            'M_size' : micp_common.unsigned_int,
            'N_size' : micp_common.unsigned_int,
            'K_size' : micp_common.unsigned_int}


class LinpackParamTypeValidator(ParamTypeValidator):
    """Parameter type validator class for the linpack kernel"""
    def __init__(self):
        self.name = 'linpack'
        self._validators = {
            'omp_num_threads' : micp_common.signed_int,
            'matrix_size' : micp_common.unsigned_int,
            'num_rep' : micp_common.unsigned_int,
            'lead_dim': micp_common.unsigned_int}


class StreamParamTypeValidator(ParamTypeValidator):
    """Parameter type validator class for the STREAM kernel"""
    def __init__(self):
        self.name = 'STREAM'
        self._validators = {'omp_num_threads' : micp_common.unsigned_int}


class SHOCParamTypeValidator(ParamTypeValidator):
    """Parameter type validator class for shoc_download and shoc_readback"""
    def __init__(self):
        self.name = 'SHOC'
        self._validators = {
            'target' : micp_common.unsigned_int,
            'passes': micp_common.unsigned_int,
            'nopinned' : micp_common.no_args}


class HPLinpackParamTypeValidator(ParamTypeValidator):
    """Parameter type validator class for the hplinpack kernel"""
    def __init__(self):
        self.name = 'hplinpack'
        self._validators = {
            'problem_size' : micp_common.unsigned_int,
            'block_size' : micp_common.unsigned_int,
            'hpl_numthreads': micp_common.unsigned_int}


class HPCGParamTypeValidator(ParamTypeValidator):
    """Parameter type validator class for the hplinpack kernel"""
    def __init__(self):
        self.name = 'hpcg'
        self._validators = {
            'problem_size' : micp_common.unsigned_int,
            'time' : micp_common.unsigned_int,
            'omp_num_threads': micp_common.unsigned_int}


def ParamTypeValidatorFactory(name):
    """Factory to instantiate ParamTypeValidator objects"""
    if name == NO_VALIDATOR:
        return NoParamTypeValidator()

    if name == XGEMM_VALIDATOR:
        return GEMMParamTypeValidator()

    if name == SHOC_VALIDATOR:
        return SHOCParamTypeValidator()

    if name == LINPACK_VALIDATOR:
        return LinpackParamTypeValidator()

    if name == STREAM_VALIDATOR:
        return StreamParamTypeValidator()

    if name == HPLINPACK_VALIDATOR:
        return HPLinpackParamTypeValidator()

    if name == HPCG_VALIDATOR:
        return HPCGParamTypeValidator()

    raise ValueError('INTERNAL ERROR: unknown validator "{0}"'.format(name))
