# Copyright (c) 2010 Resolver Systems Ltd, PythonAnywhere LLP
# See LICENSE.md
#

from django.conf.urls import *

from .views import (
    calculate, clear_cells, clipboard, copy_sheet, export_csv, get_json_grid_data_for_ui,
    get_json_meta_data_for_ui, import_csv, import_xls, page, set_cell_formula,
    set_column_widths, set_sheet_name, set_sheet_security_settings,
    set_sheet_usercode
)


URL_BASE = r'^(?P<sheet_id>\d+)/'

# Included from users URLs file, so we already have a
# username parameter before any parameters we capture
# here.
urlpatterns = patterns(
    '',
    url(f'{URL_BASE}$', page, name="sheet_page"),
    url(f'{URL_BASE}calculate/$', calculate, name="sheet_calculate"),
    url(
        f'{URL_BASE}get_json_grid_data_for_ui/$',
        get_json_grid_data_for_ui,
        name="sheet_get_json_grid_data_for_ui",
    ),
    url(
        f'{URL_BASE}get_json_meta_data_for_ui/$',
        get_json_meta_data_for_ui,
        name="sheet_get_json_meta_data_for_ui",
    ),
    url(f"{URL_BASE}import_csv/$", import_csv, name="sheet_import_csv"),
    url(
        f"{URL_BASE}export_csv/(?P<csv_format>excel|unicode)/$",
        export_csv,
        name="sheet_export_csv",
    ),
    url("import_xls/$", import_xls, name="sheet_import_xls"),
    url(f"{URL_BASE}copy_sheet/$", copy_sheet, name="sheet_copy_sheet"),
    url(
        f'{URL_BASE}set_cell_formula/$',
        set_cell_formula,
        name="sheet_set_cell_formula",
    ),
    url(
        f'{URL_BASE}set_column_widths/$',
        set_column_widths,
        name="sheet_set_column_widths",
    ),
    url(
        f"{URL_BASE}set_sheet_name/$",
        set_sheet_name,
        name="sheet_set_sheet_name",
    ),
    url(
        f'{URL_BASE}set_sheet_usercode/$',
        set_sheet_usercode,
        name="sheet_set_sheet_usercode",
    ),
    url(
        f'{URL_BASE}set_sheet_security_settings/$',
        set_sheet_security_settings,
        name="sheet_set_sheet_security_settings",
    ),
    url(
        f'{URL_BASE}cut/$',
        lambda *args, **kwargs: clipboard(action='cut', *args, **kwargs),
        name="sheet_cut",
    ),
    url(
        f'{URL_BASE}copy/$',
        lambda *args, **kwargs: clipboard(action='copy', *args, **kwargs),
        name="sheet_copy",
    ),
    url(
        f'{URL_BASE}paste/$',
        lambda *args, **kwargs: clipboard(action='paste', *args, **kwargs),
        name="sheet_paste",
    ),
    url(f'{URL_BASE}clear_cells/$', clear_cells, name="sheet_clear_cells"),
    url(
        r'%sv0\.1/' % (URL_BASE,),
        include('sheet.urls_api_0_1'),
    ),
)
