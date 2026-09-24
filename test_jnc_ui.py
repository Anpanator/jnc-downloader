"""Unit tests for jnc_ui: the console output and prompts of JNCConsoleUI."""
import contextlib
import io
import unittest
from typing import Callable
from unittest import mock

from jnc_api_tools import JNCUserData
from jnc_test_support import FUTURE_PUBLISH, PAST_PUBLISH, make_book
from jnc_ui import JNCConsoleUI


def run_capture(func: Callable, *args, **kwargs) -> str:
    """Runs func while capturing what it prints to stdout."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        func(*args, **kwargs)
    return out.getvalue()


class JNCConsoleUITests(unittest.TestCase):
    def setUp(self) -> None:
        self.ui = JNCConsoleUI()

    def test_info_prints_the_message(self) -> None:
        self.assertEqual('hello\n', run_capture(self.ui.info, 'hello'))

    def test_error_prints_the_message_to_stdout(self) -> None:
        self.assertEqual('oops\n', run_capture(self.ui.error, 'oops'))

    def test_confirm_accepts_only_a_literal_y(self) -> None:
        for answer, expected in [('y', True), ('n', False), ('Y', False), ('yes', False)]:
            with mock.patch('builtins.input', return_value=answer) as input_mock:
                confirmed = self.ui.confirm('Proceed?')
            self.assertEqual(expected, confirmed, f'answer {answer!r}')
            input_mock.assert_called_once_with('Proceed? (y/n)')

    def test_prompt_login_asks_for_email_and_hidden_password(self) -> None:
        with mock.patch('builtins.input', return_value='user@example.com') as input_mock, \
                mock.patch('jnc_ui.getpass', return_value='secret') as getpass_mock:
            self.assertEqual(('user@example.com', 'secret'), self.ui.prompt_login())
        input_mock.assert_called_once_with('Enter login email: ')
        getpass_mock.assert_called_once_with()

    def test_show_coin_balance_prints_the_discount_when_there_is_one(self) -> None:
        user = JNCUserData('u1', 'tester', 'tok', 42, 'PREMIUM')
        self.assertEqual('You have 42 coins.\nYou can buy coins at a 15% discount.\n',
                         run_capture(self.ui.show_coin_balance, user))

    def test_show_coin_balance_prints_only_the_balance_without_discount(self) -> None:
        user = JNCUserData('u1', 'tester', 'tok', 42, 'FANCLUB')
        self.assertEqual('You have 42 coins.\n',
                         run_capture(self.ui.show_coin_balance, user))

    def test_show_new_books_marks_available_books_and_preorders(self) -> None:
        books = [
            make_book('B1', 'Book One', price=550, publish_date=PAST_PUBLISH),
            make_book('B2', 'Future Book', price=400, publish_date=FUTURE_PUBLISH),
        ]
        self.assertEqual(
            '(550 coins) Available:\tBook One\n(400 coins) Preorder:\tFuture Book\n',
            run_capture(self.ui.show_new_books, books),
        )

    def test_show_preorders_lists_preorder_books_only(self) -> None:
        library = {
            'B1': make_book('B1', 'Future Book', is_preorder=True, publish_date=FUTURE_PUBLISH),
            'B2': make_book('B2', 'Book Two', is_preorder=False),
        }
        self.assertEqual(
            '\nCurrent preorders (Release Date / Title):\n2030-01-01 00:00:00+00:00 Future Book\n',
            run_capture(self.ui.show_preorders, library),
        )

    def test_show_preorders_prints_nothing_without_preorders(self) -> None:
        library = {'B2': make_book('B2', 'Book Two')}
        self.assertEqual('', run_capture(self.ui.show_preorders, library))


if __name__ == '__main__':
    unittest.main()
