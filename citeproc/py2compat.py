
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import locale
import sys
import types

from io import open

__all__ = ['PY2']

PY2 = sys.version_info < (3, 0)

if PY2:
    __all__ += ['str', 'print', 'open']

    str = types.UnicodeType
    std_print = print

    def print(*objects, **kwargs):
        if kwargs.get('file', sys.stdout) == sys.stdout:
            objects = (str(obj) for obj in objects)
            if not getattr(sys.stdout, 'encoding', None):
                objects = (obj.encode(locale.getpreferredencoding())
                           for obj in objects)
        std_print(*objects, **kwargs)
