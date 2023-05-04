# Copyright (c) 2010 Resolver Systems Ltd, PythonAnywhere LLP
# See LICENSE.md
#

from .cell import undefined
from .utils.cell_name_utils import coordinates_to_cell_name


class CycleError(Exception):

    def __init__(self, path):
        self.path = path


    def __str__(self):
        return ' -> '.join(coordinates_to_cell_name(*loc) for loc in self.path)


    def __repr__(self):
        return f'CycleError({str(self)})'


    def __eq__(self, other):
        return self.path == other.path if isinstance(other, CycleError) else False


    def __ne__(self, other):
        return not self.__eq__(other)


def report_cell_error(worksheet, loc, exc):
    worksheet[loc].value = undefined
    worksheet[loc].error = f"{exc.__class__.__name__}: {str(exc)}"
    worksheet.add_console_text("%s\n    Formula '%s' in %s\n" % (
    worksheet[loc].error, worksheet[loc].formula, coordinates_to_cell_name(*loc)))

