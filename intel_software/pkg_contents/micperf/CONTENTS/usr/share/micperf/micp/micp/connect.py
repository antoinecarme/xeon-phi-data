#  Copyright 2012-2017, Intel Corporation, All Rights Reserved.
#
#  This software is supplied under the terms of a license
#  agreement or nondisclosure agreement with Intel Corp.
#  and may not be copied or disclosed except in accordance
#  with the terms of that agreement.
#
#  Author:  Christopher M. Cantalupo
#

import os
import sys
import getpass
import shutil
import errno
import subprocess
import shlex
import socket
import re
import xml.etree.ElementTree

import common as micp_common

"""
Environment Variables to override implementation:
    INTEL_MPSS_USER:     UID of device side user, defaults to getpass.getuser().
    INTEL_MPSS_SSH_KEY:  Path to SSH key to log into device.
"""

class Connect(object):
    def __init__(self):
        raise NotImplementedError('Abstract base class')

    def Popen(self, args):
        """
        Equivalent to running Popen on the connected system.  Note
        that the default values for stdin, stdout, and stderr are
        subprocess.PIPE and bufsize defaults to -1.
        """
        raise NotImplementedError('Abstract base class')

    def copyto(self, source, dest):
        """
        Equivalent to the Unix command "cp -rp source dest" but the
        source files are located on local system, and the dest files are
        created on the connected system.  Note that source can be a
        list if dest is a directory.
        """
        raise NotImplementedError('Abstract base class')

    def copyfrom(self, source, dest):
        """
        Equivalent to the Unix command "cp -rp source dest" but the
        source files are located on the connected system, and the dest
        files are created on the local system.  Note that source can
        be a list if dest is a directory.
        """
        raise NotImplementedError('Abstract base class')

class LocalConnect(Connect):
    def __init__(self):
        pass
    def Popen(self, args, **kwargs):
        if type(args) is str:
            args = shlex.split(args)
        kwargs['shell'] = micp_common.is_platform_windows()
        if 'stdout' not in kwargs:
            kwargs['stdout'] = subprocess.PIPE
        if 'stderr' not in kwargs:
            kwargs['stderr'] = subprocess.PIPE
        if 'stdin' not in kwargs:
            kwargs['stdin'] = subprocess.PIPE
        if 'bufsize' not in kwargs:
            kwargs['bufsize'] = -1
        return subprocess.Popen(args, **kwargs)

    def copyto(self, source, dest):
        self.copyrp(source, dest)

    def copyfrom(self, source, dest):
        self.copyrp(source, dest)

    def copyrp(self, source, dest):
        if type(source) is str:
            source = [source]
        for src in source:
            try:
               shutil.copytree(src, dest)
            except OSError as copyError:
                if copyError.errno == errno.ENOTDIR:
                    shutil.copy(src, dest)
                else:
                    raise

class SSLConnect(Connect):
    def __init__(self, host, user=None, sslkey=None):
        if micp_common.is_platform_windows():
            self._connect = WinSSLConnect(host, user, sslkey)
        else:
            self._connect = LinuxSSLConnect(host, user, sslkey)

    def Popen(self, args, **kwargs):
        if 'stdout' not in kwargs:
            kwargs['stdout'] = subprocess.PIPE
        if 'stderr' not in kwargs:
            kwargs['stderr'] = subprocess.PIPE
        if 'stdin' not in kwargs:
            kwargs['stdin'] = subprocess.PIPE
        if 'bufsize' not in kwargs:
            kwargs['bufsize'] = -1
        if 'env' in kwargs:
            env = kwargs.pop('env')
            if type(args) is str:
                args = shlex.split(args)
            envSet = ' '.join(['export {0}={1};'.format(key, val) for (key, val) in env.items()])
            envSet = shlex.split(envSet)
            envSet.extend(args)
            args = envSet
        return self._connect.Popen(args, **kwargs)

    def copyto(self, source, dest):
        return self._connect.copyto(source, dest)

    def copyfrom(self, source, dest):
        return self._connect.copyfrom(source, dest)


class MPSSConnect(Connect):
    def __init__(self, host):
        if host in micp_common.LOCAL_HOST_ID:
            self._host = 'localhost'
            self._offloadIndex = -1
            self._connect = LocalConnect()
        else:
            if type(host) is int or host.isdigit():
                self._host = 'mic{0}'.format(host)
            else:
                self._host = host
            try:
                ipaddress = socket.gethostbyname(self._host)
                self._connect = SSLConnect(ipaddress, self.get_user(), self.get_ssl_key())
            except socket.gaierror:
                try:
                    index = int(re.sub(r'.*mic([0-9]+).*', r'\1', self._host))
                    if micp_common.is_platform_windows():
                        ipaddress = '192.168.{0}.100'.format(index + 1)
                    else:
                        ipaddress = '172.31.{0}.1'.format(index + 1)
                    self._host = ipaddress
                    self._connect = SSLConnect(ipaddress, self.get_user(), self.get_ssl_key())
                    if self._get_offload_index_from_config() != index:
                        errString = 'Default IP address "{0}" for host "{1}"\n'\
                                    'does not map to offload target number {2}'
                        errString.format(ipaddress, self._host, index)
                        raise GetIPAddressError(errString)
                except (ValueError, GetOffloadIndexError, GetIPAddressError):
                    self._connect = SSLConnect(self._host, self.get_user(), self.get_ssl_key())

    def Popen(self, args, **kwargs):
        return self._connect.Popen(args, **kwargs)

    def copyto(self, source, dest):
        self._connect.copyto(source, dest)

    def copyfrom(self, source, dest):
        self._connect.copyfrom(source, dest)

    def get_user(self):
        return os.environ.get('INTEL_MPSS_USER',
                              getpass.getuser())

    def get_ssl_key(self):
        if micp_common.is_platform_windows():
            prefix = os.environ.get('INTEL_MPSS_HOME', 'C:\\Program Files\\Intel\\MPSS')
            defaultKey = os.path.join(prefix, 'bin', 'id_rsa.ppk')
        else:
            defaultKey = None
        result = os.environ.get('INTEL_MPSS_SSH_KEY', defaultKey)
        if result and not os.path.exists(result):
            errMsg = 'Could not open ssh key {0},\n'\
                     'Set environment variable INTEL_MPSS_SSH_KEY to specify path to key.'
            errMsg = errMsg.format(result)
            raise IOError(errMsg)
        return result

    def get_offload_index(self):
        try:
            return self._offloadIndex
        except AttributeError:
            try:
                result = self._get_offload_index_from_exact_match()
            except GetOffloadIndexError as exactErr:
                try:
                    result = self._get_offload_index_from_config()
                except GetOffloadIndexError as configErr:
                    try:
                        result = self._get_offload_index_from_loose_match()
                    except GetOffloadIndexError as looseErr:
                        errStr = ' AND \n        '.join((exactErr.__str__(),
                                                         configErr.__str__(),
                                                         looseErr.__str__()))
                        raise GetOffloadIndexError(errStr)
        self._offloadIndex = result
        return result

    def _get_offload_index_from_config(self):
        if micp_common.is_platform_windows():
            return self._get_offload_index_from_xmlconfig()
        else:
            return self._get_offload_index_from_sysfs()

    def _get_offload_index_from_sysfs(self):
        try:
            serialMap = [(open('/sys/class/mic/{0}/serialnumber'.format(micName)).read(),
                          int(re.sub(r'mic([0-9]+)', r'\1', micName)))
                         for micName in os.listdir('/sys/class/mic')
                         if re.match(r'mic[0-9]+', micName)]
            pid = self._connect.Popen('cat /sys/class/micras/hwinf')
            hwinf = pid.communicate()[0]
            result = [index for (serialNo, index) in serialMap if serialNo in hwinf][0]
            return result
        except (ValueError, IOError, IndexError):
            raise GetOffloadIndexError('Could not determine mic index from sysfs entries')

    def _get_offload_index_from_xmlconfig(self):
        try:
            myIPAddress = socket.gethostbyname(self._host)
            sdk = os.environ.get('INTEL_MPSS_HOME', 'C:\\Program Files\\Intel\\MPSS')
            configList = [ff for ff in os.listdir(sdk) if re.match(r'mic[0-9]+\.xml', ff)]
            for config in configList:
                index = int(re.sub(r'mic([0-9]+)\.xml', r'\1', config))
                tree = xml.etree.ElementTree.parse(os.path.join(sdk, config))
                root = tree.getroot()
                ipaddress = [ii.text for ii in root.getiterator() if ii.tag == 'IPAddress'][0]
                if ipaddress == myIPAddress:
                    return index
        except (socket.gaierror, OSError, IndexError, IOError):
            raise GetOffloadIndexError('Could not determine mic index from Windows MPSS XML configuration file')

    def _get_offload_index_from_exact_match(self):
        """
        Interpret the "host" assuming it is an index or and index
        preceded by the string mic.
        """
        if type(self._host) is int:
            return self._host
        try:
            return int(re.sub(r'mic([0-9]+)', r'\1', self._host))
        except ValueError:
            raise GetOffloadIndexError('Could not determine mic index from exact match')

    def _get_offload_index_from_loose_match(self):
        """
        Interpret the "host" assuming it has the string mic[0-9]+
        somewhere in it and pick the last one.
        """
        try:
            return int(re.sub(r'.*mic([0-9]+).*', r'\1', self._host))
        except ValueError:
            raise GetOffloadIndexError('Could not determine mic index from loose match')


class LinuxSSLConnect(Connect):
    def __init__(self, host,  user=None, sslkey=None):
        self._host = host
        self._user = user
        self._sslkey = sslkey

    def Popen(self, args, **kwargs):
        kwargs['shell'] = False
        if type(args) is str:
            args = shlex.split(args)
        sshArgs = ['ssh']
        if self._sslkey:
            sshArgs.extend(['-i', self._sslkey])
        if self._user:
            sshArgs.extend(['-l', self._user])
        sshArgs.append(self._host)
        sshArgs.extend(args)
        return subprocess.Popen(sshArgs, **kwargs)

    def copyto(self, source, dest):
        if type(source) is str:
            source = [source]
        if self._user:
            devPath = '{0}@{1}:{2}'.format(self._user, self._host, dest)
        else:
            devPath = '{0}:{1}'.format(self._host, dest)
        scpArgs = ['scp', '-r', '-p']
        if self._sslkey:
            scpArgs.extend([ '-i', self._sslkey])
        scpArgs.extend(source)
        scpArgs.append(devPath)
        pid = subprocess.Popen(scpArgs,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               stdin=subprocess.PIPE,
                               bufsize=-1,
                               shell=False)
        out, err = pid.communicate()
        if pid.returncode != 0:
            sys.stderr.write(out)
            sys.stderr.write(err)
            raise subprocess.CalledProcessError(pid.returncode, scpArgs)

    def copyfrom(self, source, dest):
        if type(source) is str:
            source = [source]
        if len(source) > 1 and not os.path.isdir(dest):
            raise IOError('target "{0}" is not a directory'.format(dest))
        for src in source:
            if self._user:
                devPath = '{0}@{1}:{2}'.format(self._user, self._host, src)
            else:
                devPath = '{0}:{1}'.format(self._host, src)
            scpArgs = ['scp', '-r', '-p']
            if self._sslkey:
                scpArgs.extend(['-i', self._sslkey])
            scpArgs.append(devPath)
            scpArgs.append(dest)
            pid = subprocess.Popen(scpArgs,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   stdin=subprocess.PIPE,
                                   bufsize=-1,
                                   shell=False)
            out, err = pid.communicate()
            if pid.returncode != 0:
                sys.stderr.write(out)
                sys.stderr.write(err)
                raise subprocess.CalledProcessError(pid.returncode, scpArgs)


class WinSSLConnect(Connect):
    def __init__(self, host, user, sslkey):
        self._host = host
        self._user = user
        self._sslkey = sslkey

    def Popen(self, args, **kwargs):
        kwargs['shell'] = True
        if type(args) is str:
            args = shlex.split(args)
        sshArgs = ['plink.exe']
        sshArgs.extend(['-i', '"{0}"'.format(self._sslkey)])
        sshArgs.extend(['-l', self._user])
        sshArgs.append(self._host)
        sshArgs.extend(args)
        sshArgs = ' '.join(sshArgs)
        return subprocess.Popen(sshArgs, **kwargs)

    def copyto(self, source, dest):
        if type(source) is str:
            source = [source]
        sourceQuoted = ['"{0}"'.format(src) for src in source]
        devPath = '{0}@{1}:{2}'.format(self._user, self._host, dest)
        scpArgs = ['pscp.exe', '-r', '-scp']
        scpArgs.extend([ '-i', '"{0}"'.format(self._sslkey)])
        scpArgs.extend(sourceQuoted)
        scpArgs.append(devPath)
        scpArgs = ' '.join(scpArgs)
        pid = subprocess.Popen(scpArgs,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               stdin=subprocess.PIPE,
                               bufsize=-1,
                               shell=True)
        out, err = pid.communicate()
        if pid.returncode != 0:
            sys.stderr.write(out)
            sys.stderr.write(err)
            raise subprocess.CalledProcessError(pid.returncode, scpArgs)
        # Make everything executable
        pid = self.Popen('if [ -d {0} ]; then echo {0}; else dirname {0}; fi'.format(dest), stdout=subprocess.PIPE)
        destDir = pid.communicate()[0].strip()
        if destDir == dest:
            destList = ['{0}/{1}'.format(destDir, os.path.basename(src)) for src in source]
        else:
            destList = [dest]
        for dd in destList:
            pid = self.Popen('chmod u+x {0}'.format(dd))
            pid.communicate()

    def copyfrom(self, source, dest):
        if type(source) is str:
            source = [source]
        if len(source) > 1 and not os.path.isdir(dest):
            raise IOError('target "{0}" is not a directory'.format(dest))
        for src in source:
            devPath = '{0}@{1}:{2}'.format(self._user, self._host, src)
            scpArgs = ['pscp.exe', '-r', '-scp']
            scpArgs.extend(['-i', '"{0}"'.format(self._sslkey)])
            scpArgs.append(devPath)
            scpArgs.append('"{0}"'.format(dest))
            scpArgs = ' '.join(scpArgs)
            pid = subprocess.Popen(scpArgs,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   stdin=subprocess.PIPE,
                                   bufsize=-1,
                                   shell=True)
            out, err = pid.communicate()
            if pid.returncode != 0:
                sys.stderr.write(out)
                sys.stderr.write(err)
                raise subprocess.CalledProcessError(pid.returncode, scpArgs)


class GetOffloadIndexError(Exception):
    pass

class GetIPAddressError(Exception):
    pass

class CalledProcessError(subprocess.CalledProcessError):
    pass

