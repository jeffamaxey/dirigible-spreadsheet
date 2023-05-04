# Copyright (c) 2010 Resolver Systems Ltd.
# All Rights Reserved
#
from __future__ import print_function

from contextlib import contextmanager
from email.parser import Parser
from functools import wraps
from textwrap import dedent
from threading import Thread
from urlparse import urljoin, urlparse, urlunparse
import datetime
import hashlib
import os
import re
import time
import urllib
import urllib2

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY, HASH_SESSION_KEY
from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys

from sheet.sheet import Sheet

USER_PASSWORD = 'p4ssw0rd'

DEFAULT_WAIT_FOR_TIMEOUT = 2
DEFAULT_TYPING_WAIT = 0.1

CURRENT_API_VERSION = '0.1'
SCREEN_DUMP_LOCATION = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'screendumps')
)
IMAP_HOST = ""
IMAP_USERNAME = ""
IMAP_PASSWORD = ""


def _debug(text):
    msg = f'{round(time.time(), 2)}   {text}'
    print(msg)
    # print(msg, file=sys.stderr)


class Url(object):
    ROOT = 'http://localhost:8081/'
    LOGIN = urljoin(ROOT, '/login/')
    LOGOUT = urljoin(ROOT, '/logout')
    NEW_SHEET = urljoin(ROOT, '/new_sheet')
    SIGNUP = urljoin(ROOT, '/signup/register/')
    DOCUMENTATION = urljoin(ROOT, '/documentation/')
    API_DOCS = urljoin(DOCUMENTATION, 'builtins.html')


    @classmethod
    def user_page(cls, username):
        return urljoin(Url.ROOT, f'/user/{username}/')

    @classmethod
    def sheet_page(cls, username, sheet_id):
        return urljoin(cls.user_page(username), f'sheet/{sheet_id}/')

    @classmethod
    def api_url(cls, username, sheet_id):
        return urljoin(
            cls.sheet_page(username, sheet_id), f'v{CURRENT_API_VERSION}/json/'
        )



def snapshot_on_error(test):

    @wraps(test)
    def inner(*args, **kwargs):
        try:
            test(*args, **kwargs)
        except:
            test_object = args[0]

            try:
                filename = test_object.get_dump_filename()
                _debug('screenshot to {}.png'.format(filename))
                test_object.browser.get_screenshot_as_file(f'{filename}.png')
                _debug('page source dump  to {}.html'.format(filename))
                with open(f'{filename}.html', 'w') as f:
                    f.write(test_object.browser.page_source.encode('utf8'))
                _debug('page text dump  to {}.txt'.format(filename))
                with open(f'{filename}.txt', 'w') as f:
                    body_text = test_object.browser.find_element_by_tag_name('body').text
                    f.write(body_text.encode('utf8'))
            except:
                _debug('Exception writing screenshots')
            raise

    return inner


def humanesque_delay(length=DEFAULT_TYPING_WAIT):
    time.sleep(length)


def humanise_with_delay(action):
    @wraps(action)
    def inner(*args, **kwargs):
        humanesque_delay()
        result = action(*args, **kwargs)
        humanesque_delay()
        return result
    return inner


class Bounds(object):
    def __init__(self, width, height, top, left):
        self.width = width
        self.height = height
        self.top = top
        self.left = left

    bottom = property(lambda self: self.top + self.height)

    right = property(lambda self: self.left + self.width)


RGB_RE = re.compile('^rgba?\((\d+), (\d+), (\d+)(, (\d+))?\)')

def convert_rgb_to_hex(value):
    match = RGB_RE.match(value)
    r, g, b = match.group(1), match.group(2), match.group(3)
    return '#%X%X%X' % (int(r), int(g), int(b))


class FunctionalTest(StaticLiveServerTestCase):
    user_count = 1

    def wait_for(
        self, condition_function, msg_function,
        timeout_seconds=DEFAULT_WAIT_FOR_TIMEOUT, allow_exceptions=False
    ):
        start = time.time()
        end = start + timeout_seconds
        exception_raised = False
        tries = 0
        while tries < 2 or time.time() < end:
            _debug('Waiting for {}'.format(msg_function()[:30]))
            try:
                tries += 1
                if condition_function():
                    return
                exception_raised = False
            except Exception, e:
                if not allow_exceptions:
                    raise e
                exception_raised = True
            time.sleep(0.1)
        if exception_raised:
            raise
        self.fail("Timeout waiting for condition: %s" % (msg_function(),))

    def get_dump_filename(self):
        timestamp = datetime.datetime.now().isoformat().replace(':', '.')[:19]
        return '{folder}/{test_id}-{timestamp}'.format(
            folder=SCREEN_DUMP_LOCATION,
            test_id=self.id(),
            timestamp=timestamp
        )

    session_keys = {}

    def create_users(self):
        for username in self.get_my_usernames():
            user = User.objects.create(username=username)
            user.set_password('p4ssw0rd')
            user.save()
            profile = user.get_profile()
            profile.has_seen_sheet_page = True
            profile.save()

            # create sessions we can use for login too
            session = SessionStore()
            session[SESSION_KEY] = user.pk
            session[BACKEND_SESSION_KEY] = settings.AUTHENTICATION_BACKENDS[0]
            session[HASH_SESSION_KEY] = user.get_session_auth_hash()
            session.save()
            self.session_keys[username] = session.session_key



    def setUp(self):
        self.create_users()
        _debug(f"{datetime.datetime.now()} ##### Running test {self.id()}")
        self.browser = webdriver.Firefox()
        self.browser.implicitly_wait(DEFAULT_WAIT_FOR_TIMEOUT)
        self.browser.set_window_size(1024, 768)


    def tearDown(self):
        _debug('quitting browser')
        self.browser.quit()
        _debug(f"{datetime.datetime.now()} ##### Finished test {self.id()}")


    def login(
        self, username=None, password=USER_PASSWORD, manually=False
    ):
        if username is None:
            username = self.get_my_username()

        if manually:
            self.get_element('id=id_username').clear()
            self.get_element('id=id_password').clear()
            self.get_element('id=id_username').send_keys(username)
            self.get_element('id=id_password').send_keys(password)
            self.click_link('id_login')
            return

        session_key = self.session_keys[username]
        ## to set a cookie we need to first visit the domain.
        ## 404 pages load the quickest!
        self.browser.get(urljoin(Url.ROOT, "/404_no_such_url/"))
        self.browser.add_cookie(dict(
            name=settings.SESSION_COOKIE_NAME,
            value=session_key,
            path='/',
        ))
        self.go_to_url(Url.ROOT)


    def logout(self):
        self.go_to_url(Url.LOGOUT)


    def get_element(self, locator):
        if locator.startswith('css='):
            return self.browser.find_element_by_css_selector(locator[4:])
        elif locator.startswith('id='):
            return self.browser.find_element_by_id(locator[3:])



    def is_element_focused(self, locator):
        element = self.get_element(locator)
        focused_element = self.browser.switch_to_active_element()
        return element == focused_element


    def is_element_present(self, locator):
        try:
            self.get_element(locator)
            return True
        except NoSuchElementException:
            return False


    def get_text(self, locator):
        return self.get_element(locator).text


    def get_value(self, locator):
        return self.get_element(locator).get_attribute('value')


    def human_key_press(self, key_code):
        _debug('pressing key %r' % (key_code,))
        self.browser.switch_to_active_element().send_keys(key_code)


    @contextmanager
    def key_down(self, key_code):
        _debug('key down %r' % (key_code,))
        self.browser.switch_to_active_element().send_keys(key_code)
        ActionChains(self.browser).key_down(key_code).perform()
        yield
        # apparently there's no need for a key up??
        # ActionChains(self.browser).key_up(key_code).perform()


    def click_to_and_blur_from(self, click_to_locator, blur_from_locator):
        self.selenium.fire_event(blur_from_locator, 'blur')
        self.selenium.click(click_to_locator)


    def get_element_bounds(self, locator):
        return Bounds(
            self.selenium.get_element_width(locator),
            self.selenium.get_element_height(locator),
            self.selenium.get_element_position_top(locator),
            self.selenium.get_element_position_left(locator)
        )


    def get_css_property(self, jquery_locator, property_name):
        property_value = self.selenium.get_eval(
            f'window.$("{jquery_locator}").css("{property_name}")'
        )
        if property_value == 'rgba(0, 0, 0, 0)': # transparent in chrome
            return 'transparent'
        if property_value.startswith('rgb'):
            property_value = convert_rgb_to_hex(property_value)
        if property_value.startswith('#'):
            property_value = property_value.upper()
            if len(property_value) == 4:
                _, r, g, b = property_value
                property_value = f'#{r}{r}{g}{g}{b}{b}'
        return property_value


    def assert_urls_are_same(self, actual, expected):
        loc = self.browser.current_url
        canonicalised_actual = urljoin(loc, actual)
        canonicalised_expected = urljoin(loc, expected)
        self.assertEquals(canonicalised_actual, canonicalised_expected)


    def assert_HTTP_error(self, url, error_code):
        self.browser.get(url)
        possible_error_locators = ('id=summary', 'id=id_server_error_title')
        for error_locator in possible_error_locators:
            if self.is_element_present(error_locator) and str(error_code) in self.get_text(error_locator):
                return
        self.fail('%d not raised, got: %s' % (error_code, self.browser.title))


    def assert_redirects(self, from_url, to_url):
        self.go_to_url(from_url)
        self.assert_urls_are_same(
            urlunparse(urlparse(self.browser.current_url)[:4] + ('', '')),
            to_url
        )

    def is_element_enabled(self, element_id):
        #self.selenium.get_attribute is unreliable (Harry, Jonathan)
        disabled = self.selenium.get_eval(
            f'window.$("#{element_id}").attr("disabled")'
        )
        return disabled not in ("true", "disabled")


    def wait_for_element_presence(
        self, locator, present=True, timeout_seconds=DEFAULT_WAIT_FOR_TIMEOUT
    ):
        if present:
            failure_message = (f"Element {locator} to be present", )
        else:
            failure_message = (f"Element {locator} to not exist", )
        self.wait_for(
            lambda: self.is_element_present(locator) == present,
            lambda: failure_message,
            timeout_seconds=timeout_seconds
        )


    def wait_for_element_to_appear(self, locator, timeout_seconds=DEFAULT_WAIT_FOR_TIMEOUT):
        self.wait_for_element_presence(locator, True, timeout_seconds)


    def wait_for_element_text(self, locator, text, timeout_seconds=DEFAULT_WAIT_FOR_TIMEOUT):
        self.wait_for(
            lambda: self.get_text(locator) == text,
            lambda: "Element %s to contain text %r. Contained %r" % (locator, text, self.get_text(locator)),
            timeout_seconds=timeout_seconds
        )


    def wait_for_element_visibility(self, locator, visibility, timeout_seconds=DEFAULT_WAIT_FOR_TIMEOUT):
        self.wait_for(
            lambda: self.selenium.is_visible(locator) == visibility,
            lambda: f"Element {locator} to become{visibility and ' ' or ' in'}visible",
            timeout_seconds=timeout_seconds,
        )


    def get_url_with_session_cookie(self, url, data=None):
        opener = urllib2.build_opener()
        session_cookie = self.selenium.get_cookie_by_name('sessionid')
        opener.addheaders.append(('Cookie', f'sessionid={session_cookie}'))
        if data is None:
            return opener.open(url)
        encoded_data = urllib.urlencode(data)
        return opener.open(url, encoded_data)


    def create_new_sheet(self, username=None, manually=False):
        if username is None:
            username = self.get_my_username()
        user = User.objects.get(username=username)
        sheet = Sheet(owner=user)
        sheet.save()
        self.browser.get(Url.sheet_page(username, sheet.id))
        return sheet.id



    def login_and_create_new_sheet(self, username=None):
        self.login(username=username)
        return self.create_new_sheet(username=username)


    def get_my_usernames(self):
        usernames = []
        for user_index in range(self.user_count):
            capture_test_details = re.compile(r'test_(\d+)_[^\.]*\.[^\.]*\.test_(.*)$')
            match = re.search(capture_test_details, self.id())
            test_task_id = match[1]
            test_method_name = match[2]
            test_method_hash = hashlib.md5(test_method_name).hexdigest()[:7]

            usernames.append(
                f"tstusr_{test_task_id}_{test_method_hash}"[:29] + str(user_index)
            )
        return usernames


    def get_my_username(self):
        return self.get_my_usernames()[0]


    def _check_page_link_home(self):
        if self.browser.current_url.startswith(Url.DOCUMENTATION):
            return

        link = None
        for possible_id in ('id_small_header_logo', 'id_big_logo'):
            try:
                link = self.browser.find_element_by_xpath(
                    "//a[img[@id='{img_id}']]".format(img_id=possible_id)
                )
                self.assertEqual(link.get_attribute('href'), Url.ROOT)
                return
            except NoSuchElementException:
                pass

        self.fail(
            f"Could not find a logo that is also a link on page {self.browser.current_url}"
        )


    def check_page_load(self, link_destination=None):
        self._check_page_link_home()


    def go_to_url(self, url):
        _debug(f'going to url {url}')
        self.browser.get(url)
        self.check_page_load(url)


    def refresh_sheet_page(self):
        self.browser.refresh()
        self.wait_for_grid_to_appear()


    def click_link(self, element_id):
        link = self.browser.find_element_by_id(element_id)
        link.click()


    def set_sheet_name(self, name):
        self.selenium.click('id=id_sheet_name')
        self.wait_for(
            lambda: self.is_element_present('id=edit-id_sheet_name'),
            lambda: 'editable sheetname to appear')
        self.selenium.type('id=edit-id_sheet_name', name)
        self.human_key_press('\n')
        self.wait_for(
            lambda: self.get_text('id=id_sheet_name') == name,
            lambda: 'sheet name to be updated'
        )


    def assert_sends_to_login_page(self, requested_url):
        self.assert_redirects(requested_url, Url.LOGIN)


    def assert_sends_to_root_page(self, requested_url):
        self.assert_redirects(requested_url, Url.ROOT)


    def assert_page_title_contains(self, link_url, title):
        original_page = self.browser.current_url
        self.go_to_url(link_url)
        self.assertTrue(title in self.browser.title)
        self.go_to_url(original_page)


    def assert_has_useful_information_links(self):
        self.browser.find_elements_by_link_text('Terms & Conditions')
        self.browser.find_elements_by_link_text('Privacy Policy')
        self.browser.find_elements_by_link_text('Contact Us')


    def get_cell_css(self, column, row, must_be_active=False):
        active_classes = '.active' if must_be_active else ''
        return 'div.slick-row[row="%d"] div.slick-cell.c%d%s' % (
            row - 1, column, active_classes
        )


    def get_cell_locator(self, column, row, must_be_active=False):
        return f'css={self.get_cell_css(column, row, must_be_active)}'


    def get_cell_formatted_value_locator(self, column, row, raise_if_cell_missing=True):
        cell_css = self.get_cell_css(column, row)
        if not self.is_element_present(f'css={cell_css}'):
            if raise_if_cell_missing:
                raise Exception(f"Cell not present at {column}, {row}")
            else:
                return None
        return f'css={cell_css} span.grid_formatted_value'



    cell_editor_css = 'input.editor-text'

    def get_active_cell_editor_locator(self):
        return f'css={self.cell_editor_css}'


    def get_cell_editor_locator(self, column, row):
        cell_css = self.get_cell_css(column, row)
        return f'css={cell_css} {self.cell_editor_css}'


    def get_cell_editor(self):
        return self.get_element(self.get_active_cell_editor_locator())


    def is_cell_visible(self, column, row):
        tries = 0
        while tries < 4:
            try:
                return (
                    self.selenium.get_eval(
                        dedent(
                            '''     #                        (function () {     #                            var viewport = window.grid.getViewport();     #                            if (viewport.top > %(row)s || %(row)s > viewport.bottom) {     #                                return false;     #                            }     #     #                            var $canvasDiv = window.$('div.grid-canvas');     #                            var $viewportDiv = window.$('div.slick-viewport');     #                            var viewableLeft = -$canvasDiv.position().left;     #                            var viewableRight = viewableLeft + $viewportDiv.width();     #                            var $currentCell = window.$('%(current_cell_css)s');     #                            var currentCellLeft = $currentCell.position().left;     #                            var currentCellRight = currentCellLeft + $currentCell.outerWidth();     #                            if (viewableLeft > currentCellLeft || currentCellRight > viewableRight) {     #                                return false;     #                            }     #     #                            return true;     #                        })()     #                    '''
                            % dict(
                                row=row,
                                col=column,
                                current_cell_css=self.get_cell_css(column, row),
                            )
                        )
                    )
                    == 'true'
                )
            except:
                time.sleep(1)
                tries += 1

        self.fail(
            f"Could not check for cell visibility at {column}, {row} after {tries} tries"
        )


    def assert_cell_visible(self, column, row):
        self.assertTrue(
            self.is_cell_visible(column, row), f'cell {column}, {row} not visible'
        )


    def wait_for_cell_to_be_visible(
        self, column, row, timeout_seconds=DEFAULT_WAIT_FOR_TIMEOUT
    ):
        self.wait_for(
            lambda: self.is_cell_visible(column, row),
            lambda: f"Cell at {column}, {row} to become visible",
            allow_exceptions=True,
            timeout_seconds=timeout_seconds,
        )


    def get_formula_bar_id(self):
        return "id_formula_bar"


    def get_formula_bar_locator(self):
        return f"id={self.get_formula_bar_id()}"


    def is_formula_bar_enabled(self):
        return self.is_element_enabled(self.get_formula_bar_id())


    def scroll_cell_row_into_view(self, column, row):
        self.browser.execute_script(
            'window.grid.scrollRowIntoView({row}, true);'.format(row=row - 1)
        )
        self.wait_for_element_to_appear(self.get_cell_locator(column, row))


    def go_to_cell(self, column, row):
        self.selenium.get_eval(f'window.grid.gotoCell({row - 1}, {column}, false)')
        self.wait_for_element_to_appear(self.get_cell_locator(column, row))


    @humanise_with_delay
    def click_on_cell(self, column, row):
        self.scroll_cell_row_into_view(column, row)
        self.get_element(self.get_cell_locator(column, row)).click()


    def select_range_with_shift_click(self, start, end):
        self.click_on_cell(*start)
        with self.key_down(key_codes.SHIFT):
            self.click_on_cell(*end)
        self.assert_current_selection(start, end)


    def mouse_drag(self, cell_from, cell_to):
        from_locator = self.get_cell_locator(*cell_from)
        to_locator = self.get_cell_locator(*cell_to)

        pixel_offset = "10,30"
        #pixel offset fixes selenium weird tendency to click too far north-west.
        #may cause problems if column widths are reduced...

        self.selenium.mouse_down_at(from_locator, pixel_offset)
        humanesque_delay(1)
        self.selenium.mouse_move_at(from_locator, pixel_offset)
        humanesque_delay(1)
        self.selenium.mouse_move_at(to_locator, pixel_offset)
        humanesque_delay(1)
        self.selenium.mouse_up_at(to_locator, pixel_offset)
        humanesque_delay(1)


    def assert_current_selection(self, topleft, bottomright, thoroughly=True):
        if thoroughly:
            for row in range(topleft[1],bottomright[1] + 1):
                for col in range(topleft[0],bottomright[0] + 1):
                    locator = f'{self.get_cell_locator(col, row)}.selected'
                    self.wait_for_element_to_appear(locator)
        else:
            topleft_locator = f'{self.get_cell_locator(*topleft)}.selected'
            bottomright_locator = f'{self.get_cell_locator(*bottomright)}.selected'
            self.wait_for_element_to_appear(topleft_locator)
            self.wait_for_element_to_appear(bottomright_locator)


    def open_cell_for_editing(self, column, row):
        self.scroll_cell_row_into_view(column, row)
        ActionChains(self.browser).double_click(
            self.get_element(self.get_cell_locator(column, row))
        ).perform()
        self.wait_for_cell_to_enter_edit_mode(column, row)


    def type_into_cell_editor_unhumanized(self, text):
        self.get_cell_editor().send_keys(text)


    @humanise_with_delay
    def enter_cell_text(self, col, row, text):
        self.enter_cell_text_unhumanized(col, row, text)


    def enter_cell_text_unhumanized(self, col, row, text):
        self.open_cell_for_editing(col, row)
        self.type_into_cell_editor_unhumanized(text)
        self.type_into_cell_editor_unhumanized('\n')
        # self.wait_for_cell_to_contain_formula(text)


    def get_current_cell(self):
        row = int(self.browser.execute_script(
            'return window.grid.getActiveCell().row;')
        ) + 1
        column = int(self.browser.execute_script(
            'return window.grid.getActiveCell().cell;'
        ))
        return column, row


    def get_cell_text(self, column, row):
        self.scroll_cell_row_into_view(column, row)
        return self.get_text(self.get_cell_locator(column, row))


    def get_cell_editor_content(self):
        return self.get_cell_editor().get_attribute('value')


    def get_cell_shown_formula_locator(self, column, row, raise_if_cell_missing=True):
        cell_css = self.get_cell_css(column, row)
        if not self.is_element_present(f'css={cell_css}'):
            if raise_if_cell_missing:
                raise Exception(f"Cell not present at {column}, {row}")
            else:
                return None
        return f'css={cell_css} span.grid_formula'


    def get_cell_shown_formula(self, column, row, raise_if_cell_missing=True):
        formula_locator = self.get_cell_shown_formula_locator(
            column, row, raise_if_cell_missing
        )
        return (
            self.get_text(formula_locator)
            if self.is_element_present(formula_locator)
            else None
        )


    def assert_cell_shown_formula(self, column, row, formula):
        self.assertEquals(self.get_cell_shown_formula(column, row), formula)


    def wait_for_cell_shown_formula(self, column, row, formula, timeout_seconds=DEFAULT_WAIT_FOR_TIMEOUT):
        def generate_failure_message():
            return (
                "cell %d, %d to show formula '%s', was %r -- text is %r" % (
                column, row, formula, self.get_cell_shown_formula(column, row), self.get_cell_text(column, row))
            )

        self.wait_for(
            lambda : self.get_cell_shown_formula(column, row, raise_if_cell_missing=False) == formula,
            generate_failure_message,
            allow_exceptions=True,
            timeout_seconds=timeout_seconds
        )


    def wait_for_cell_to_contain_formula(self, column, row, formula):
        self.open_cell_for_editing(column, row)
        self.wait_for_cell_editor_content(formula)
        self.get_cell_editor().send_keys('\n')


    error_img_locator = 'id=id_{col}_{row}_error'

    def get_cell_error(self, column, row):
        if self.is_element_present(self.error_img_locator.format(col=column, row=row)):
            return self.get_element(self.error_img_locator.format(col=column, row=row)).get_attribute('title')


    def assert_cell_has_error(self, column, row, error_text):
        self.wait_for_element_to_appear(self.error_img_locator.format(col=column, row=row))
        self.assertEquals(self.get_cell_error(column, row), error_text)


    def assert_cell_has_no_error(self, column, row):
        self.assertFalse(
            self.is_element_present(self.error_img_locator.format(col=column, row=row)),
            'Error present for (%d, %d)' % (column, row)
        )


    def assert_cell_is_current_but_not_editing(self, col, row):
        self.wait_for_cell_to_become_active(col, row)
        self.assertFalse(
            self.is_element_focused(self.get_cell_editor_locator(col, row))
        )


    def assert_cell_is_current_and_is_editing(self, col, row):
        self.wait_for_cell_to_become_active(col, row)
        self.assertTrue(
            self.is_element_focused(self.get_cell_editor_locator(col, row))
        )


    def wait_for_cell_value(
        self, column, row, value_or_regex,
        timeout_seconds=DEFAULT_WAIT_FOR_TIMEOUT
    ):
        _debug('waiting for cell {},{} value {}'.format(
            column, row, value_or_regex,
        ))

        def match(text):
            if hasattr(value_or_regex, 'match'):
                return value_or_regex.match(text)
            else:
                return text == value_or_regex

        def cell_shows_value():
            self.last_found_value = self.get_cell_text(column, row)
            return (
                match(self.last_found_value) and
                self.get_cell_shown_formula(
                    column, row, raise_if_cell_missing=False
                ) is None
            )

        def generate_failure_message():
            actual_value = self.last_found_value
            self.last_found_value = None
            actual_formula = ''
            if self.get_cell_shown_formula(column, row) is not None:
                actual_formula = self.last_found_value
                actual_value = ''
            actual_error = self.get_cell_error(column, row)

            return (
                "Cell at (%s, %s) to become %r "
                "(value=%r, shown formula=%r, error=%r)" % (
                    column, row, value_or_regex,
                    actual_value, actual_formula, actual_error)
            )

        self.last_found_value = None
        try:
            self.wait_for(
                cell_shows_value,
                generate_failure_message,
                timeout_seconds=timeout_seconds,
                allow_exceptions=True
            )
        finally:
            _debug('finished waiting for cell value')


    def wait_for_cell_to_become_active(
        self, column, row, timeout_seconds=DEFAULT_WAIT_FOR_TIMEOUT
    ):
        locator = self.get_cell_locator(column, row, must_be_active=True)
        self.wait_for(
            lambda: self.is_element_present(locator),
            lambda: f"Cell at ({column}, {row}) was not active. Selection is: {self.get_current_cell()}",
            timeout_seconds=timeout_seconds,
        )


    def wait_for_cell_to_enter_edit_mode(
        self, column, row, timeout_seconds=DEFAULT_WAIT_FOR_TIMEOUT
    ):
        self.wait_for_cell_to_become_active(column, row)
        full_editor_locator = self.get_cell_editor_locator(column, row)
        self.wait_for(
            lambda: self.is_element_focused(full_editor_locator),
            lambda: f"Editor at ({column}, {row}) to get focus",
            timeout_seconds=timeout_seconds,
        )


    def wait_for_cell_editor_content(self, content):
        self.wait_for(
            lambda: self.get_cell_editor_content() == content,
            lambda: f"Cell editor to become {content} (was '{self.get_cell_editor_content()}')",
        )


    def get_viewport_top(self):
        return int(self.selenium.get_eval(
            'window.grid.getViewport().top'
        ) ) + 1


    def get_viewport_bottom(self):
        return int(self.selenium.get_eval(
            'window.grid.getViewport().bottom'
        ) ) + 1


    def is_spinner_visible(self):
        return (
            self.is_element_present('css=#id_spinner_image')
            and not self.is_element_present('css=#id_spinner_image.hidden')
        )


    def wait_for_spinner_to_stop(self, timeout_seconds=DEFAULT_WAIT_FOR_TIMEOUT):
        self.wait_for(
            lambda : not self.is_spinner_visible(),
            lambda : "Spinner to disappear",
            timeout_seconds=timeout_seconds
        )


    def wait_for_grid_to_appear(self, timeout_seconds=DEFAULT_WAIT_FOR_TIMEOUT):
        self.wait_for_element_to_appear(self.get_cell_locator(1, 1), timeout_seconds)


    def get_usercode(self):
        return self.browser.execute_script(
            'return window.editor.session.getValue();'
        ).replace('\r\n', '\n')


    @humanise_with_delay
    def enter_usercode(self, code, commit_change=True):
        self.browser.execute_script(
            f"window.editor.session.setValue({repr(unicode(code))[1:]});"
        )
        if commit_change:
            self.human_key_press(Keys.F9)


    def append_usercode(self, code):
        self.enter_usercode("%s\n%s" % (self.get_usercode(), code))


    def prepend_usercode(self, code):
        self.enter_usercode("%s\n%s" % (code, self.get_usercode()))


    def wait_for_usercode_editor_content(
        self, content, timeout_seconds=DEFAULT_WAIT_FOR_TIMEOUT
    ):
        self.wait_for(
            lambda: self.get_usercode().strip() == content.strip(),
            lambda: (
                'Usercode editor content to become \n'
                + content
                + '\n' + '-=' * 10 + '\nwas:\n'
                + self.get_usercode()
            ),
            timeout_seconds=timeout_seconds
        )


    def sanitise_console_content(self, content):
        # IE has char 13 for return instead of the normal Unix 10.
        # Not sure why it differs from Chrome and Firefox.
        return content.replace('\r', '\n')


    def get_console_content(self):
        content = self.selenium.get_eval('window.$("#id_console").text()')
        return self.sanitise_console_content(content)


    def wait_for_console_content(self, content, timeout_seconds=DEFAULT_WAIT_FOR_TIMEOUT):
        self.wait_for(
            lambda: content in self.get_console_content(),
            lambda: f'error console to contain "{content}" (was "{self.get_console_content()}")',
            timeout_seconds=timeout_seconds,
        )


    def get_formula_bar_contents(self):
        return self.selenium.get_value(self.get_formula_bar_locator())


    def assert_formula_bar_contains(self, contents):
        self.assertEquals(self.get_formula_bar_contents(), contents)


    def wait_for_formula_bar_contents(self, contents, timeout_seconds=DEFAULT_WAIT_FOR_TIMEOUT):
        self.wait_for(
            lambda: self.get_formula_bar_contents() == contents,
            lambda: f'formula bar to contain "{contents}" (was "{self.get_formula_bar_contents()}")',
            timeout_seconds=timeout_seconds,
        )

    def click_formula_bar(self):
        self.selenium.click(self.get_formula_bar_locator())
        self.wait_for(
            lambda : self.is_element_focused(self.get_formula_bar_locator()),
            lambda : "Formula bar to gain focus"
        )


    def copy_range(self, start, end):
        self.click_on_cell(*start)
        with self.key_down(key_codes.SHIFT):
            self.click_on_cell(*end)
        self.assert_current_selection(start, end)
        with self.key_down(key_codes.CTRL):
            self.selenium.key_press_native(key_codes.LETTER_C)


    def cut_range(self, start, end):
        self.click_on_cell(*start)
        with self.key_down(key_codes.SHIFT):
            self.click_on_cell(*end)
        self.assert_current_selection(start, end)
        with self.key_down(key_codes.CTRL):
            self.selenium.key_press_native(key_codes.LETTER_X)
        self.wait_for_spinner_to_stop()


    def paste_range(self, start, end=None):
        self.click_on_cell(*start)
        if end:
            with self.key_down(key_codes.SHIFT):
                self.click_on_cell(*end)
        with self.key_down(key_codes.CTRL):
            self.selenium.key_press_native(key_codes.LETTER_V)
        self.wait_for_spinner_to_stop()


    def set_filename_for_upload(self, file_name, field_selector):
        if self.selenium.browserStartCommand == '*firefox':
            self.selenium.focus(field_selector)
            self.selenium.type(field_selector, file_name)
            self.selenium.click(field_selector)
        else:
            def handle_file_dialog():
                time.sleep(2)
                SendKeys.SendKeys('{ENTER}')
                time.sleep(2)
                escaped_filename = file_name.replace('~','{~}')
                SendKeys.SendKeys(escaped_filename)
                SendKeys.SendKeys('{ENTER}')
                time.sleep(2)

            dialog_thread = Thread(target=handle_file_dialog)
            dialog_thread.start()
            self.selenium.click(field_selector)
            self.selenium.focus(field_selector)
            dialog_thread.join()


    def pop_email_for_client(self, email_address, fail_if_none=True, content_filter=None):
        retries = 6
        while retries:
            if message := self._pop_email_for_client_once(
                email_address, content_filter=content_filter
            ):
                return message
            retries -= 1
            if retries == 0 and fail_if_none:
                self.fail('Email not received')
            time.sleep(5)


    def _pop_email_for_client_once(self, email_address, content_filter=None):
        from imapclient import IMAPClient
        message = None
        messages_to_delete = []
        server = IMAPClient(IMAP_HOST, ssl=True)
        for m_id, parsed_headers, body_text in self.all_emails(server):
            if email_address in parsed_headers['To']:
                body_text = body_text.replace('\r', '')
                body_text = body_text.replace('=\n', '')
                if content_filter is None or content_filter in body_text:
                    message = (
                        parsed_headers['From'],
                        parsed_headers['To'],
                        parsed_headers['Subject'],
                        body_text
                    )
                    messages_to_delete.append(m_id)
        server.delete_messages(messages_to_delete)
        return message


    def clear_email_for_address(self, email_address, content_filter=None):
        from imapclient import IMAPClient
        server = IMAPClient(IMAP_HOST, ssl=True)
        messages_to_delete = [
            m_id
            for m_id, parsed_headers, body_text in self.all_emails(server)
            if email_address in parsed_headers['To']
            and (content_filter is None or content_filter in body_text)
        ]
        server.delete_messages(messages_to_delete)


    def all_emails(self, server):
        server.login(IMAP_USERNAME, IMAP_PASSWORD)
        server.select_folder('INBOX')
        messages = server.search(['NOT DELETED'])
        response = server.fetch(messages, ['RFC822.TEXT', 'RFC822.HEADER'])
        parser = Parser()
        for m_id, m in response.items():
            parsed_headers = parser.parsestr(m['RFC822.HEADER'])
            body_text = m['RFC822.TEXT']
            yield (m_id, parsed_headers, body_text)

