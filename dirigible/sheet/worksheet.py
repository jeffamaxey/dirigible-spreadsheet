# Copyright (c) 2010 Resolver Systems Ltd, PythonAnywhere LLP
# See LICENSE.md
#

from cgi import escape
import csv
import json
import simplejson as json
from StringIO import StringIO
from threading import Lock
from xlrd import error_text_from_code, xldate_as_tuple, XL_CELL_DATE, XL_CELL_ERROR

from .cell import Cell, undefined
from .cell_range import CellRange
from .utils.cell_name_utils import (
    cell_name_to_coordinates, column_name_to_index,
    cell_range_as_string_to_coordinates
)



class InvalidKeyError(Exception):
    pass



class Bounds(tuple):

    def __init__(self, (left, top, right, bottom)):
        super(tuple, self).__init__((left, top, right, bottom))
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


def dump_cell_to_json_stream(stream, col, row, cell):
    stream.write('"%s,%s": { ' % (col, row))
    stream.write(f'"formula": {json.dumps(cell.formula)}, ')
    stream.write(f'"formatted_value": {json.dumps(cell.formatted_value)} ')
    if cell.python_formula:
        stream.write(f', "python_formula": {json.dumps(cell.python_formula)} ')
    if cell.dependencies:
        stream.write(f', "dependencies": {json.dumps(map(list, cell.dependencies))} ')
    if cell.error:
        stream.write(f', "error": {json.dumps(cell.error)} ')
    try:
        stream.write(', "value": %s ' % (json.dumps(cell.value, allow_nan=False),))
    except (TypeError, ValueError):
        # Not JSONifiable
        pass
    stream.write('}')


def worksheet_to_json(worksheet):
    stream = StringIO()
    stream.write("{ ")

    stream.write(f'"_console_text": {json.dumps(worksheet._console_text)}, ')
    stream.write(f'"_usercode_error": {json.dumps(worksheet._usercode_error)} ')

    for (col, row), cell in worksheet.iteritems():
        stream.write(',')
        dump_cell_to_json_stream(stream, col, row, cell)

    stream.write(" }")
    result = stream.getvalue()
    stream.close()
    return result


def worksheet_from_json(json_string):
    #use json for read ops because of better performance
    #keep simplejson for write ops as it's more robust
    worksheet_dict = json.loads(json_string)
    worksheet = Worksheet()
    for (key, value) in worksheet_dict.iteritems():
        if key == "_console_text":
            worksheet._console_text = value
        elif key == "_usercode_error":
            worksheet._usercode_error = value
        else:
            col_str, row_str = key.split(",")
            cell = Cell()
            cell._formula = value["formula"]
            cell._python_formula = value.get("python_formula")
            cell.dependencies = map(tuple, value.get("dependencies", []))
            cell.error = value.get("error")
            cell._value = value.get("value", undefined)
            cell.formatted_value = value["formatted_value"]
            worksheet[int(col_str), int(row_str)] = cell
    return worksheet


def worksheet_to_csv(worksheet, encoding):
    stream = StringIO()
    writer = csv.writer(stream)

    if worksheet:
        _, __, right, bottom = worksheet.bounds
        for row in range(1, bottom + 1):
            row_list = []
            for col in range(1, right + 1):
                value = worksheet[col, row].value
                encoded_value = ''
                if value is not undefined:
                    encoded_value = value.encode(encoding) if hasattr(value, 'encode') else value
                row_list.append(encoded_value)
            writer.writerow(row_list)

    result = stream.getvalue()
    stream.close()
    return result


def worksheet_from_excel(excel_sheet):
    worksheet = Worksheet()
    for col in range(excel_sheet.ncols):
        for row in range(excel_sheet.nrows):
            cell = excel_sheet.cell(row, col)
            if cell.ctype == XL_CELL_ERROR:
                formula = f'={error_text_from_code[cell.value]}'
            elif cell.ctype == XL_CELL_DATE:
                formula = '=DateTime(%s, %s, %s, %s, %s, %s)' % xldate_as_tuple(
                    cell.value, excel_sheet.book.datemode)
            else:
                formula = unicode(excel_sheet.cell(row, col).value)
            worksheet[col + 1, row + 1].formula = formula
    return worksheet


class Worksheet(dict):

    def __init__(self):
        self.name = None
        self._console_text = ''
        self._usercode_error = None
        self._console_lock = Lock()


    def __getitem__(self, key):
        if location := self.to_location(key):
            return self.setdefault(location, Cell())
        else:
            raise InvalidKeyError("%r is not a valid cell location" % (key,))


    def __setitem__(self, key, item):
        location = self.to_location(key)
        if not location:
            raise InvalidKeyError("%r is not a valid cell location" % (key,))

        if not isinstance(item, Cell):
            raise TypeError("Worksheet locations must be Cell objects")

        dict.__setitem__(self, location, item)


    def __getattr__(self, name):
        if location := self.to_location(name):
            return self.__getitem__(name)
        else:
            raise AttributeError("'Worksheet' object has no attribute %r" % (name,))


    def __setattr__(self, name, value):
        if location := cell_name_to_coordinates(name):
            self.__setitem__(location, value)
        else:
            super(Worksheet, self).__setattr__(name, value)


    def __repr__(self):
        return f'<Worksheet {self.name}>' if self.name else '<Worksheet>'


    def __eq__(self, other):
        return (
            isinstance(other, Worksheet) and
            dict(self) == dict(other) and
            self.name == other.name
        )


    def __ne__(self, other):
        return not self.__eq__(other)


    def to_location(self, key):
        if isinstance(key, tuple) and len(key) == 2:
            col, row = key
            if isinstance(col, basestring):
                col = column_name_to_index(col)
            if isinstance(col, (int, long)) and isinstance(row, (int, long)):
                return col, row
            return None
        elif isinstance(key, basestring):
            return cell_name_to_coordinates(key)
        return None


    def add_console_text(self, error_text, log_type='error'):
        self._console_lock.acquire()
        self._console_text += (
            f'<span class="console_{log_type}_text">{escape(error_text)}</span>'
        )
        self._console_lock.release()


    def set_cell_formula(self, col, row, formula):
        if formula:
            self[col, row].formula = formula

        elif (col, row) in self:
            del self[col, row]


    def clear_values(self):
        to_delete = []
        for location, cell in self.items():
            if cell.formula or cell.python_formula:
                cell.value = undefined
                cell.error = None
            else:
                to_delete.append(location)
        for location in to_delete:
            del self[location]


    #--methods intended for public user consumption--

    def cell_range(self, start_or_string_cellrange, end=None):
        if isinstance(start_or_string_cellrange, basestring) and end is None:
            start_and_end = cell_range_as_string_to_coordinates(start_or_string_cellrange)
            if start_and_end is None:
                raise ValueError(f"Invalid cell range '{start_or_string_cellrange}'")
            return CellRange(self, *start_and_end)

        def convert_if_needed(cell_ref):
            if isinstance(cell_ref, basestring):
                return cell_name_to_coordinates(cell_ref)
            else:
                return cell_ref

        start_tuple = convert_if_needed(start_or_string_cellrange)
        end_tuple = convert_if_needed(end)
        if start_tuple is None:
            if end_tuple is None:
                raise ValueError(
                    f'Neither {start_or_string_cellrange} nor {end} are valid cell locations'
                )
            raise ValueError(f'{start_or_string_cellrange} is not a valid cell location')
        if end_tuple is None:
            raise ValueError(f'{end} is not a valid cell location')
        return CellRange(self, start_tuple, end_tuple)


    @property
    def bounds(self):
        if not self:
            return None
        locations = self.iterkeys()
        col, row = locations.next()
        left = right = col
        top = bottom = row
        for col, row in locations:
            if col < left:
                left = col
            if row < top:
                top = row
            if col > right:
                right = col
            if row > bottom:
                bottom = row
        return Bounds((left, top, right, bottom))
