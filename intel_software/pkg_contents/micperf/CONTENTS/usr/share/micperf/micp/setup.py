#! /usr/bin/python
# Copyright 2010-2017 Intel Corporation.
# 
# This library is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published
# by the Free Software Foundation, version 2.1.
# 
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.
# 
# Disclaimer: The codes contained in these modules may be specific
# to the Intel Software Development Platform codenamed Knights Ferry,
# and the Intel product codenamed Knights Corner, and are not backward
# compatible with other Intel products. Additionally, Intel will NOT
# support the codes or instruction set in future products.
# 
# Intel offers no warranty of any kind regarding the code. This code is
# licensed on an "AS IS" basis and Intel is not obligated to provide
# any support, assistance, installation, training, or other services
# of any kind. Intel is also not obligated to provide any updates,
# enhancements or extensions. Intel specifically disclaims any warranty
# of merchantability, non-infringement, fitness for any particular
# purpose, and any other warranty.
# 
# Further, Intel disclaims all liability of any kind, including but
# not limited to liability for infringement of any proprietary rights,
# relating to the use of the code, even if Intel is notified of the
# possibility of such liability. Except as expressly stated in an Intel
# license agreement provided with this code and agreed upon with Intel,
# no license, express or implied, by estoppel or otherwise, to any
# intellectual property rights is granted herein.

from distutils.core import setup
import os.path
import sys
import platform
import shutil


def unix2dos(fileName):
    fid = open(fileName, 'rb')
    content = fid.read()
    fid.close()
    unixContent = content.replace('\r\n','\n')
    dosContent = unixContent.replace('\n','\r\n')
    fid = open(fileName, 'wb')
    fid.write(dosContent)
    fid.close()


def dos2unix(fileName):
    fid = open(fileName, 'rb')
    content = fid.read()
    fid.close()
    content = content.replace('\r\n', '\n')
    fid = open(fileName, 'wb')
    fid.write(content)
    fid.close()


if os.getcwd() != os.path.dirname(os.path.abspath(__file__)):
    sys.stderr.write('ERROR:  script must be run in the directory that contains it\n')
    exit(1)

try:
    execfile('micp/version.py')
except IOError:
    sys.stderr.write('WARNING:  micp/version.py not found, setting version to 0.0.0\n')
    __version__ = '0.0.0'

# Convert line endings in text files
if platform.platform().lower().startswith('windows'):
    convert = unix2dos
else:
    convert = dos2unix
for fileName in ('CHANGES.txt', 'INSTALL.txt', 'INSTALL_WIN.txt', 'LICENSE.txt', 'micperf_faqs.txt'):
    convert(fileName)

licensePath = 'LICENSE.txt'
try:
    license = open('LICENSE.txt').read()
except IOError:
    sys.stderr.write('ERROR:  MPSS license file could not be found here:\n')
    sys.stderr.write('          {0}\n'.format(licensePath))
    exit(1)

try:
    readme = open('README.txt').read()
    blocks = readme.split('================================================================================')
    introIndex = ['1.  Introduction' in bb for bb in blocks].index(True) + 1
    longDescription = blocks[introIndex]

except IOError:
    raise IOError('Could not find README.txt file for micp')

scripts=['micprun',
         'micpinfo',
         'micpprint',
         'micpplot',
         'micpcsv']

# Add .py extensions for windows install and remove the .py extension otherwise
if platform.platform().lower().startswith('windows'):
    winScripts = [ss + '.py' for ss in scripts]
    for (src, dst) in zip(scripts, winScripts):
        if os.path.exists(src):
            shutil.copy2(src, dst)
    scripts = winScripts
else:
    winScripts = [ss + '.py' for ss in scripts]
    for (src, dst) in zip(winScripts, scripts):
        if os.path.exists(src):
            shutil.copy2(src, dst)

setup(name='micp',
      version=__version__,
      description='Intel(R) Xeon Phi(TM) OEM/ISV Workloads Package',
      author='Christopher Cantalupo',
      author_email='christopher.m.cantalupo@intel.com',
      packages=['micp', 'micp.kernels'],
      scripts=scripts,
      license=license,
      long_description=longDescription)
