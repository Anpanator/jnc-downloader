"""Unit tests for jnc.py's workflow functions (loaded without executing the script)."""
import unittest
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from unittest import mock

from jnc_api_tools import JNCApiError, JNCUserData
from jnc_test_support import FUTURE_PUBLISH, FakeConsoleUI, load_workflow_functions, make_book

# jnc.py executes its whole flow on import, so its workflow functions are
# extracted from the source instead (see jnc_test_support).
WORKFLOWS = load_workflow_functions()


class HandleNewBooksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handle_new_books = WORKFLOWS['handle_new_books']
        self.user = JNCUserData('u1', 'tester', 'tok', 1000, 'PREMIUM')
        self.owned_info = make_book('B1', 'Book One', volume_id='v1')

    def run_handle_new_books(self, ui: FakeConsoleUI, books: List[Any], **kwargs) -> Any:
        with mock.patch('jnc_api_tools.JNClient.order_book') as order_book, \
                mock.patch('jnc_api_tools.JNClient.fetch_owned_book_info',
                           return_value=self.owned_info) as fetch_info:
            ordered = self.handle_new_books(ui=ui, new_books=books, user_data=self.user, **kwargs)
        return ordered, order_book, fetch_info

    def test_orders_confirmed_books_and_returns_their_owned_infos(self) -> None:
        ui = FakeConsoleUI(confirm_answers=[True])
        book_one = make_book('B1', 'Book One', volume_id='v1', price=500)
        ordered, order_book, fetch_info = self.run_handle_new_books(ui, [book_one])
        order_book.assert_called_once_with(book=book_one, user_data=self.user)
        fetch_info.assert_called_once_with(auth_token='tok', volume_id='v1')
        self.assertEqual({'B1': self.owned_info}, ordered)
        self.assertIn('You have 1000 coins', ui.infos)
        self.assertIn('Ordered: Book One\n', ui.infos)

    def test_skips_books_the_user_declines(self) -> None:
        ui = FakeConsoleUI(confirm_answers=[False])
        book_one = make_book('B1', 'Book One', volume_id='v1', price=500)
        ordered, order_book, _ = self.run_handle_new_books(ui, [book_one])
        self.assertEqual({}, ordered)
        order_book.assert_not_called()
        self.assertEqual(['Do you want to order Book One?'], ui.confirms)
        self.assertNotIn('Ordered: Book One\n', ui.infos)

    def test_no_confirm_order_orders_without_asking(self) -> None:
        ui = FakeConsoleUI()
        book_one = make_book('B1', 'Book One', volume_id='v1', price=500)
        ordered, order_book, _ = self.run_handle_new_books(ui, [book_one], no_confirm_order=True)
        self.assertEqual([], ui.confirms)
        order_book.assert_called_once()
        self.assertEqual({'B1': self.owned_info}, ordered)

    def test_buys_coins_when_the_balance_is_empty_and_confirmed(self) -> None:
        self.user.coins = 0
        ui = FakeConsoleUI(confirm_answers=[True, True])
        book_one = make_book('B1', 'Book One', volume_id='v1', price=550)

        def buy(user_data: JNCUserData, amount: int) -> str:
            user_data.coins += amount
            return f'Purchased {amount} coins'

        with mock.patch('jnc_api_tools.JNClient.buy_coins', side_effect=buy) as buy_coins, \
                mock.patch('jnc_api_tools.JNClient.order_book') as order_book, \
                mock.patch('jnc_api_tools.JNClient.fetch_owned_book_info', return_value=self.owned_info):
            ordered = self.handle_new_books(ui=ui, new_books=[book_one], user_data=self.user, buy_coins=True)
        buy_coins.assert_called_once_with(user_data=self.user, amount=550)
        order_book.assert_called_once()
        self.assertEqual({'B1': self.owned_info}, ordered)
        self.assertEqual(['Do you want to order Book One?', 'Do you want to buy 550 coins?'], ui.confirms)
        self.assertIn('Buying 550 coins', ui.infos)
        self.assertIn('Purchased 550 coins', ui.infos)
        self.assertIn('Ordered: Book One\n', ui.infos)

    def test_does_not_buy_coins_when_the_user_declines(self) -> None:
        self.user.coins = 0
        ui = FakeConsoleUI(confirm_answers=[False])  # answer for the buy prompt
        book_one = make_book('B1', 'Book One', volume_id='v1', price=550)
        with mock.patch('jnc_api_tools.JNClient.buy_coins') as buy_coins, \
                mock.patch('jnc_api_tools.JNClient.order_book') as order_book, \
                mock.patch('jnc_api_tools.JNClient.fetch_owned_book_info', return_value=self.owned_info):
            ordered = self.handle_new_books(ui=ui, new_books=[book_one], user_data=self.user,
                                            buy_coins=True, no_confirm_order=True)
        buy_coins.assert_not_called()
        order_book.assert_not_called()
        self.assertEqual({}, ordered)
        self.assertEqual(['Do you want to buy 550 coins?'], ui.confirms)
        self.assertEqual(['Not enough coins, stopping order process!'], ui.errors)

    def test_does_not_buy_coins_when_buying_is_disabled(self) -> None:
        self.user.coins = 0
        ui = FakeConsoleUI(confirm_answers=[True])  # answer for the order prompt
        book_one = make_book('B1', 'Book One', volume_id='v1', price=550)
        with mock.patch('jnc_api_tools.JNClient.buy_coins') as buy_coins, \
                mock.patch('jnc_api_tools.JNClient.order_book') as order_book, \
                mock.patch('jnc_api_tools.JNClient.fetch_owned_book_info', return_value=self.owned_info):
            ordered = self.handle_new_books(ui=ui, new_books=[book_one], user_data=self.user, buy_coins=False)
        buy_coins.assert_not_called()
        order_book.assert_not_called()
        self.assertEqual({}, ordered)
        self.assertEqual(['Not enough coins, stopping order process!'], ui.errors)

    def test_stops_the_whole_process_when_coins_run_out(self) -> None:
        self.user.coins = 100
        ui = FakeConsoleUI()
        expensive = make_book('B1', 'Expensive', volume_id='v1', price=550)
        cheap = make_book('B2', 'Cheap', volume_id='v2', price=100)
        ordered, order_book, _ = self.run_handle_new_books(ui, [expensive, cheap], no_confirm_order=True)
        order_book.assert_not_called()
        self.assertEqual({}, ordered)
        self.assertEqual(['Not enough coins, stopping order process!'], ui.errors)


class ProcessLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.process_library = WORKFLOWS['process_library']
        self.ui = FakeConsoleUI()
        self.target_dir = '/tmp/jnc-test-downloads'

    def run_process_library(self, library: Dict[str, Any], dates: Dict[str, datetime],
                            *, include_updated: bool = False,
                            download: Optional[Callable] = None) -> Any:
        with mock.patch('jnc_api_tools.JNCUtils.download_book', side_effect=download) as download_book:
            self.process_library(ui=self.ui, library=library, downloaded_book_dates=dates,
                                 target_dir=self.target_dir, include_updated=include_updated)
        return download_book

    def test_downloads_books_that_are_due(self) -> None:
        book = make_book('B1', 'Book One', download_link='https://dl.example/book-one.epub')
        dates: Dict[str, datetime] = {}
        download_book = self.run_process_library({'B1': book}, dates)
        download_book.assert_called_once_with(target_dir=self.target_dir, book=book)
        recorded = dates['B1']
        self.assertEqual(timezone.utc, recorded.tzinfo)
        self.assertEqual(0, recorded.microsecond)
        self.assertEqual(datetime.now(tz=timezone.utc).date(), recorded.date())
        self.assertEqual(['Downloading: Book One'], self.ui.infos)

    def test_skips_preorders(self) -> None:
        book = make_book('B1', 'Future Book', is_preorder=True, download_link='https://dl.example/f.epub')
        download_book = self.run_process_library({'B1': book}, {})
        download_book.assert_not_called()
        self.assertEqual([], self.ui.infos)

    def test_skips_unpublished_books(self) -> None:
        book = make_book('B1', 'Future Book', publish_date=FUTURE_PUBLISH, download_link='https://dl.example/f.epub')
        download_book = self.run_process_library({'B1': book}, {})
        download_book.assert_not_called()

    def test_skips_books_without_a_download_link(self) -> None:
        book = make_book('B1', 'Book One')
        download_book = self.run_process_library({'B1': book}, {})
        download_book.assert_not_called()

    def test_skips_already_downloaded_books(self) -> None:
        book = make_book('B1', 'Book One', download_link='https://dl.example/book-one.epub')
        dates = {'B1': datetime(2020, 1, 1, tzinfo=timezone.utc)}
        download_book = self.run_process_library({'B1': book}, dates)
        download_book.assert_not_called()
        self.assertEqual(datetime(2020, 1, 1, tzinfo=timezone.utc), dates['B1'])

    def test_redownloads_updated_books_when_requested(self) -> None:
        book = make_book('B1', 'Book One', download_link='https://dl.example/book-one.epub',
                         updated_date='2021-06-01T00:00:00.000000Z')
        dates = {'B1': datetime(2020, 1, 1, tzinfo=timezone.utc)}
        download_book = self.run_process_library({'B1': book}, dates, include_updated=True)
        download_book.assert_called_once()
        self.assertGreater(dates['B1'], datetime(2020, 1, 2, tzinfo=timezone.utc))

    def test_does_not_redownload_when_the_update_is_older_than_the_download(self) -> None:
        book = make_book('B1', 'Book One', download_link='https://dl.example/book-one.epub',
                         updated_date='2020-06-01T00:00:00.000000Z')
        dates = {'B1': datetime(2021, 1, 1, tzinfo=timezone.utc)}
        download_book = self.run_process_library({'B1': book}, dates, include_updated=True)
        download_book.assert_not_called()
        self.assertEqual(datetime(2021, 1, 1, tzinfo=timezone.utc), dates['B1'])

    def test_continues_with_the_next_book_after_a_download_error(self) -> None:
        bad = make_book('B1', 'Bad Book', download_link='https://dl.example/bad.epub')
        good = make_book('B2', 'Good Book', download_link='https://dl.example/good.epub')
        dates: Dict[str, datetime] = {}
        download_book = self.run_process_library(
            {'B1': bad, 'B2': good}, dates,
            download=[JNCApiError('404: Book not available.'), None])
        self.assertEqual(
            [mock.call(target_dir=self.target_dir, book=bad),
             mock.call(target_dir=self.target_dir, book=good)],
            download_book.call_args_list)
        self.assertEqual(['404: Book not available.'], self.ui.errors)
        self.assertEqual(['B2'], list(dates))


if __name__ == '__main__':
    unittest.main()
