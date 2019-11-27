#  Copyright 2012-2017, Intel Corporation, All Rights Reserved.
#
# This software is supplied under the terms of a license
# agreement or nondisclosure agreement with Intel Corp.
# and may not be copied or disclosed except in accordance
# with the terms of that agreement.
#
#  Author:  Christopher M. Cantalupo

import os

__all__=''
def _set_all():
    global __all__
    dirList = os.listdir(
              os.path.dirname(
              os.path.abspath(__file__)))
    __all__ = [dd[:-3] for dd in dirList
               if dd[-3:] == '.py' and dd != '__init__.py']
_set_all()
