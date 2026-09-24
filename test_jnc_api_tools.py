"""Unit tests for jnc_api_tools: data classes, JNCUtils helpers, and the JNClient API calls."""
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from jnc_api_tools import (ArgumentError, JNCApiError, JNCBook, JNCCoinOptions, JNCSeries,
                           JNClient, JNCUserData, JNCUnauthorizedError, JNCUtils, NoCoinsError)
from jnc_test_support import (PAST_PUBLISH, FakeResponse, api_library_item, api_series_aggregate,
                              api_user_json, api_volume, epub_download, make_book)


class JNCUserDataTests(unittest.TestCase):
    def test_premium_accounts_get_15_percent_coin_discount(self) -> None:
        user = JNCUserData('u1', 'tester', 'tok', 10, 'PREMIUM')
        self.assertEqual(15, user.coin_discount)

    def test_regular_accounts_get_5_percent_coin_discount(self) -> None:
        user = JNCUserData('u1', 'tester', 'tok', 10, 'REGULAR')
        self.assertEqual(5, user.coin_discount)

    def test_other_account_types_get_no_coin_discount(self) -> None:
        user = JNCUserData('u1', 'tester', 'tok', 10, 'FANCLUB')
        self.assertEqual(0, user.coin_discount)

    def test_account_type_matching_is_case_insensitive(self) -> None:
        user = JNCUserData('u1', 'tester', 'tok', 10, 'premium membership')
        self.assertEqual(15, user.coin_discount)


class JNCBookTests(unittest.TestCase):
    def test_parses_dates_from_api_strings(self) -> None:
        book = JNCBook(book_id='B1', title='Book One', title_slug='book-one', volume_id='v1', volume_num=1,
                       publish_date='2020-01-02T03:04:05.000000Z', series_id='S1', series_slug='my-series',
                       updated_date='2021-02-03T04:05:06.000000Z', purchase_date='2022-03-04T05:06:07.000000Z')
        self.assertEqual(datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc), book.publish_date)
        self.assertEqual(datetime(2021, 2, 3, 4, 5, 6, tzinfo=timezone.utc), book.updated_date)
        self.assertEqual(datetime(2022, 3, 4, 5, 6, 7, tzinfo=timezone.utc), book.purchase_date)

    def test_defaults_for_optional_fields(self) -> None:
        book = JNCBook(book_id='B1', title='Book One', title_slug='book-one', volume_id='v1', volume_num=1,
                       publish_date=PAST_PUBLISH, series_id='S1', series_slug='my-series')
        self.assertIsNone(book.updated_date)
        self.assertIsNone(book.purchase_date)
        self.assertIsNone(book.download_link)
        self.assertIsNone(book.is_owned)
        self.assertIsNone(book.is_preorder)
        self.assertEqual(0, book.price)

    def test_price_is_a_plain_attribute_without_hidden_http(self) -> None:
        book = make_book('B1', 'Book One')
        with mock.patch('jnc_api_tools.requests.get',
                        side_effect=AssertionError('price must not be fetched lazily')) as get_mock:
            self.assertEqual(0, book.price)
            book.price = 550
            self.assertEqual(550, book.price)
            get_mock.assert_not_called()


class JNCCoinOptionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.packs = [
            {'coins': 500, 'currentCentsCost': 250, 'originalCentsCost': 500},
            {'coins': 1000, 'currentCentsCost': 500, 'originalCentsCost': 1000},
            {'coins': 2000, 'currentCentsCost': 1000, 'originalCentsCost': 2000},
        ]
        self.options = JNCCoinOptions(coinPriceInCents=100, purchaseMinimumCoins=500,
                                      purchaseMaximumCoins=1000, packs=self.packs)

    def test_coin_discount_is_derived_from_the_first_pack(self) -> None:
        self.assertEqual(50, self.options.coinDiscount)

    def test_nearest_pack_returns_the_next_bigger_pack(self) -> None:
        self.assertEqual((1000, 500), self.options.nearest_pack(600))

    def test_nearest_pack_skips_a_pack_of_the_exact_amount(self) -> None:
        self.assertEqual((1000, 500), self.options.nearest_pack(500))

    def test_nearest_pack_falls_back_to_the_largest_pack(self) -> None:
        self.assertEqual((2000, 1000), self.options.nearest_pack(99999))


class JNCUtilsSortBooksTests(unittest.TestCase):
    def test_sorts_by_series_slug_then_volume_number(self) -> None:
        books = {
            'B2': make_book('B2', 'Vol 2', series_slug='a-series', volume_num=2),
            'B1': make_book('B1', 'Vol 1', series_slug='b-series', volume_num=1),
            'B0': make_book('B0', 'Vol 0', series_slug='a-series', volume_num=1),
        }
        self.assertEqual(['B0', 'B2', 'B1'], list(JNCUtils.sort_books(books)))

    def test_books_without_series_sort_by_title_slug(self) -> None:
        books = {
            'B1': make_book('B1', 'Standalone B', series_slug='', title_slug='standalone-b'),
            'B2': make_book('B2', 'Standalone A', series_slug='', title_slug='standalone-a'),
        }
        self.assertEqual(['B2', 'B1'], list(JNCUtils.sort_books(books)))


class JNCUtilsGetNewSeriesTests(unittest.TestCase):
    def test_returns_unknown_series_slugs_without_duplicates(self) -> None:
        library = {
            'B1': make_book('B1', 'One', series_slug='known-series'),
            'B2': make_book('B2', 'Two', series_slug='new-series'),
            'B3': make_book('B3', 'Three', series_slug='new-series'),
            'B4': make_book('B4', 'Four', series_slug='other-new-series'),
            'B5': make_book('B5', 'Five', series_slug=''),
        }
        self.assertEqual(['new-series', 'other-new-series'],
                         JNCUtils.get_new_series(library, known_series=['known-series']))


class JNCUtilsGetMatchingSeriesTests(unittest.TestCase):
    def test_matches_slugs_containing_the_term_case_insensitively(self) -> None:
        known = ['ascension', 'magic-2', 'other']
        self.assertEqual(['ascension'], JNCUtils.get_matching_series(known, 'ASC'))

    def test_returns_substring_matches_in_order(self) -> None:
        known = ['blade-of-justice', 'justice-king', 'blades-of-glory']
        self.assertEqual(['blade-of-justice', 'blades-of-glory'],
                         JNCUtils.get_matching_series(known, 'blade'))

    def test_returns_nothing_without_a_match(self) -> None:
        self.assertEqual([], JNCUtils.get_matching_series(['ascension'], 'zzz'))


class JNCUtilsGetUnownedBooksTests(unittest.TestCase):
    def test_returns_volumes_missing_from_the_library(self) -> None:
        volume_one = make_book('B1', 'Vol 1')
        volume_two = make_book('B2', 'Vol 2')
        series = JNCSeries(series_id='S1', slug='my-series', tags='', volumes={'B1': volume_one, 'B2': volume_two})
        library = {'B1': make_book('B1', 'Vol 1')}
        self.assertEqual([volume_two], JNCUtils.get_unowned_books(library, {'my-series': series}))


class JNCUtilsFetchBookPricesTests(unittest.TestCase):
    def test_fetches_prices_only_for_books_without_one(self) -> None:
        unpriced = make_book('B1', 'Book One', title_slug='book-one', price=0)
        priced = make_book('B2', 'Book Two', title_slug='book-two', price=700)
        with mock.patch('jnc_api_tools.JNClient.fetch_book_price', return_value=550) as fetch_price:
            JNCUtils.fetch_book_prices([unpriced, priced])
        fetch_price.assert_called_once_with('book-one')
        self.assertEqual(550, unpriced.price)
        self.assertEqual(700, priced.price)


class JNCUtilsUnfollowCompletedSeriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.volume = make_book('B1', 'Book One')
        self.series = JNCSeries(series_id='S1', slug='my-series', tags='fully translated,comedy',
                                volumes={'B1': self.volume})

    def test_unfollows_fully_translated_series_that_are_completely_downloaded(self) -> None:
        states = {'my-series': True}
        unfollowed = JNCUtils.unfollow_completed_series(['B1'], {'my-series': self.series}, states)
        self.assertEqual(['my-series'], unfollowed)
        self.assertFalse(states['my-series'])

    def test_keeps_series_with_missing_volumes(self) -> None:
        states = {'my-series': True}
        unfollowed = JNCUtils.unfollow_completed_series([], {'my-series': self.series}, states)
        self.assertEqual([], unfollowed)
        self.assertTrue(states['my-series'])

    def test_keeps_series_that_are_not_fully_translated(self) -> None:
        ongoing = JNCSeries(series_id='S1', slug='my-series', tags='comedy', volumes={'B1': self.volume})
        states = {'my-series': True}
        unfollowed = JNCUtils.unfollow_completed_series(['B1'], {'my-series': ongoing}, states)
        self.assertEqual([], unfollowed)
        self.assertTrue(states['my-series'])

    def test_records_previously_unknown_series_as_unfollowed(self) -> None:
        states = {}
        unfollowed = JNCUtils.unfollow_completed_series(['B1'], {'my-series': self.series}, states)
        self.assertEqual(['my-series'], unfollowed)
        self.assertIn('my-series', states)
        self.assertFalse(states['my-series'])


class JNCUtilsDownloadBookTests(unittest.TestCase):
    def test_requires_a_download_link(self) -> None:
        with self.assertRaises(RuntimeError):
            JNCUtils.download_book(target_dir='/tmp', book=make_book('B1', 'Book One'))

    def test_raises_api_error_when_the_download_fails(self) -> None:
        book = make_book('B1', 'Book One', download_link='https://dl.example/book-one.epub')
        with mock.patch('jnc_api_tools.requests.get', return_value=FakeResponse(404)):
            with self.assertRaises(JNCApiError) as ctx:
                JNCUtils.download_book(target_dir='/tmp', book=book)
        self.assertEqual('404: Book not available.', str(ctx.exception))

    def test_writes_the_epub_to_the_target_dir(self) -> None:
        book = make_book('B1', 'Book One', title_slug='book-one',
                         download_link='https://dl.example/book-one.epub')
        with tempfile.TemporaryDirectory() as target_dir:
            with mock.patch('jnc_api_tools.requests.get',
                            return_value=FakeResponse(200, content=b'epub-bytes')):
                JNCUtils.download_book(target_dir=target_dir, book=book)
            with open(os.path.join(target_dir, 'book-one.epub'), 'rb') as f:
                self.assertEqual(b'epub-bytes', f.read())


class JNClientLoginTests(unittest.TestCase):
    def test_raises_on_failed_login(self) -> None:
        with mock.patch('jnc_api_tools.requests.post',
                        return_value=FakeResponse(200, {'error': 'bad credentials'})):
            with self.assertRaises(JNCApiError) as ctx:
                JNClient.login('user@example.com', 'secret')
        self.assertEqual('Login failed!', str(ctx.exception))

    def test_logs_in_and_fetches_user_data_on_success(self) -> None:
        user = JNCUserData('u1', 'tester', 'tok-9', 5, 'PREMIUM')
        with mock.patch('jnc_api_tools.requests.post',
                        return_value=FakeResponse(200, {'id': 'tok-9'})) as post_mock, \
                mock.patch('jnc_api_tools.JNClient.fetch_user_data', return_value=user) as fetch_mock:
            self.assertIs(user, JNClient.login('user@example.com', 'secret'))
        fetch_mock.assert_called_once_with('tok-9')
        post_mock.assert_called_once_with(JNClient.LOGIN_URL, headers=mock.ANY,
                                          json={'login': 'user@example.com', 'password': 'secret'})


class JNClientFetchUserDataTests(unittest.TestCase):
    def test_raises_unauthorized_on_401(self) -> None:
        with mock.patch('jnc_api_tools.requests.get', return_value=FakeResponse(401)):
            with self.assertRaises(JNCUnauthorizedError):
                JNClient.fetch_user_data('expired-token')

    def test_raises_api_error_on_other_failures(self) -> None:
        with mock.patch('jnc_api_tools.requests.get', return_value=FakeResponse(500)):
            with self.assertRaises(JNCApiError) as ctx:
                JNClient.fetch_user_data('tok')
        self.assertEqual('Could not fetch user data!', str(ctx.exception))

    def test_returns_user_data_with_the_token(self) -> None:
        with mock.patch('jnc_api_tools.requests.get',
                        return_value=FakeResponse(200, api_user_json(coins=7, level='REGULAR'))):
            user = JNClient.fetch_user_data('my-token')
        self.assertEqual('user-1', user.user_id)
        self.assertEqual('tester', user.user_name)
        self.assertEqual('my-token', user.auth_token)
        self.assertEqual(7, user.coins)
        self.assertEqual(5, user.coin_discount)


class JNClientFetchCoinOptionsTests(unittest.TestCase):
    def test_parses_coin_options(self) -> None:
        options_json = {
            'coinPriceInCents': 99,
            'purchaseMinimumCoins': 500,
            'purchaseMaximumCoins': 2000,
            'packs': [{'coins': 500, 'currentCentsCost': 250, 'originalCentsCost': 500}],
        }
        with mock.patch('jnc_api_tools.requests.get', return_value=FakeResponse(200, options_json)):
            options = JNClient.fetch_coin_options('tok')
        self.assertEqual(99, options.coinPriceInCents)
        self.assertEqual(500, options.purchaseMinimumCoins)
        self.assertEqual(2000, options.purchaseMaximumCoins)
        self.assertEqual(50, options.coinDiscount)


class JNClientFetchBookPriceTests(unittest.TestCase):
    def test_returns_the_price_in_coins(self) -> None:
        with mock.patch('jnc_api_tools.requests.get', return_value=FakeResponse(200, {'coins': 550})):
            self.assertEqual(550, JNClient.fetch_book_price('book-one'))

    def test_raises_when_the_price_is_unavailable(self) -> None:
        with mock.patch('jnc_api_tools.requests.get', return_value=FakeResponse(404)):
            with self.assertRaises(JNCApiError) as ctx:
                JNClient.fetch_book_price('book-one')
        self.assertEqual('404: Book price not available.', str(ctx.exception))


class JNClientFetchPaymentMethodIdTests(unittest.TestCase):
    def test_returns_the_stored_payment_method_id(self) -> None:
        with mock.patch('jnc_api_tools.requests.get', return_value=FakeResponse(200, {'id': 4242})):
            self.assertEqual(4242, JNClient.fetch_payment_method_id('tok'))


class JNClientFetchSeriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.aggregate = api_series_aggregate(
            'my-series',
            [api_volume('B1', 'Vol 1', 'vol-1', 'v1', 1, PAST_PUBLISH),
             api_volume('B2', 'Vol 2', 'vol-2', 'v2', 2, PAST_PUBLISH)],
            tags=['fully translated'],
        )

    def test_builds_series_with_their_volumes(self) -> None:
        with mock.patch('jnc_api_tools.requests.get',
                        return_value=FakeResponse(200, self.aggregate)) as get_mock:
            series_by_slug = JNClient.fetch_series(['my-series'])
        get_mock.assert_called_once_with(JNClient.FETCH_SERIES_URL % 'my-series')
        series = series_by_slug['my-series']
        self.assertEqual('S1', series.id)
        self.assertEqual('my-series', series.slug)
        self.assertEqual('fully translated', series.tags)
        self.assertEqual({'B1', 'B2'}, set(series.volumes))
        volume_one = series.volumes['B1']
        self.assertEqual('Vol 1', volume_one.title)
        self.assertEqual('vol-1', volume_one.title_slug)
        self.assertEqual('v1', volume_one.volume_id)
        self.assertEqual(1, volume_one.volume_num)
        self.assertEqual('my-series', volume_one.series_slug)

    def test_raises_when_the_series_cannot_be_fetched(self) -> None:
        with mock.patch('jnc_api_tools.requests.get', return_value=FakeResponse(404)):
            with self.assertRaises(JNCApiError) as ctx:
                JNClient.fetch_series(['missing-series'])
        self.assertEqual('Could not fetch series details for missing-series', str(ctx.exception))


class JNClientFetchLibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = [
            api_library_item(api_volume('B1', 'Book One', 'book-one', 'v1', 1, PAST_PUBLISH),
                             downloads=[epub_download('https://dl.example/book-one.epub')],
                             serie={'legacyId': 'S1', 'slug': 'my-series'}),
            api_library_item(api_volume('B2', 'Future Book', 'future-book', 'v2', 2, PAST_PUBLISH),
                             status='PREORDER', downloads=[],
                             serie={'legacyId': 'S1', 'slug': 'my-series'}),
        ]

    def test_builds_the_library_keyed_by_book_id(self) -> None:
        with mock.patch('jnc_api_tools.requests.get',
                        return_value=FakeResponse(200, {'books': self.items})):
            library = JNClient.fetch_library('tok')
        self.assertEqual({'B1', 'B2'}, set(library))
        self.assertEqual('https://dl.example/book-one.epub', library['B1'].download_link)
        self.assertFalse(library['B1'].is_preorder)
        self.assertTrue(library['B2'].is_preorder)

    def test_raises_when_the_library_cannot_be_fetched(self) -> None:
        with mock.patch('jnc_api_tools.requests.get', return_value=FakeResponse(500)):
            with self.assertRaises(JNCApiError) as ctx:
                JNClient.fetch_library('tok')
        self.assertEqual('Could not fetch library!', str(ctx.exception))


class JNClientFetchOwnedBookInfoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.item = api_library_item(
            api_volume('B1', 'Book One', 'book-one', 'v1', 1, PAST_PUBLISH),
            downloads=[epub_download('https://dl.example/book-one.epub')],
            last_updated='2021-01-01T00:00:00.000000Z',
            purchased='2020-02-01T00:00:00.000000Z',
            serie={'legacyId': 'S1', 'slug': 'my-series'},
        )

    def test_fetches_the_owned_book(self) -> None:
        with mock.patch('jnc_api_tools.requests.get',
                        return_value=FakeResponse(200, self.item)) as get_mock:
            book = JNClient.fetch_owned_book_info('tok', 'v1')
        get_mock.assert_called_once_with(JNClient.FETCH_SINGLE_BOOK % 'v1', headers=mock.ANY)
        self.assertEqual('B1', book.book_id)
        self.assertEqual('book-one', book.title_slug)
        self.assertEqual('my-series', book.series_slug)
        self.assertEqual('https://dl.example/book-one.epub', book.download_link)
        self.assertIsNotNone(book.updated_date)
        self.assertIsNotNone(book.purchase_date)

    def test_raises_when_the_book_info_cannot_be_fetched(self) -> None:
        with mock.patch('jnc_api_tools.requests.get', return_value=FakeResponse(403)):
            with self.assertRaises(JNCApiError) as ctx:
                JNClient.fetch_owned_book_info('tok', 'v1')
        self.assertEqual('Could not fetch book info! Response: 403', str(ctx.exception))


class JNClientCreateBookFromApiResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.volume = api_volume('B1', 'Book One', 'book-one', 'v1', 1, PAST_PUBLISH)

    def test_picks_the_epub_download_link(self) -> None:
        item = api_library_item(self.volume, downloads=[
            {'type': 'PDF', 'link': 'https://dl.example/book.pdf'},
            epub_download('https://dl.example/book.epub'),
        ])
        book = JNClient.create_jnc_book_from_api_response_item(item)
        self.assertEqual('https://dl.example/book.epub', book.download_link)

    def test_has_no_download_link_when_only_other_formats_exist(self) -> None:
        item = api_library_item(self.volume,
                                downloads=[{'type': 'PDF', 'link': 'https://dl.example/book.pdf'}])
        self.assertIsNone(JNClient.create_jnc_book_from_api_response_item(item).download_link)

    def test_maps_the_preorder_status(self) -> None:
        item = api_library_item(self.volume, status='PREORDER')
        self.assertTrue(JNClient.create_jnc_book_from_api_response_item(item).is_preorder)


class JNClientOrderBookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = JNCUserData('u1', 'tester', 'tok', 100, 'PREMIUM')
        self.book = make_book('B1', 'Book One', volume_id='v1', price=50)

    def test_orders_the_book_and_deducts_coins(self) -> None:
        with mock.patch('jnc_api_tools.requests.post', return_value=FakeResponse(204)) as post_mock:
            JNClient.order_book(book=self.book, user_data=self.user)
        post_mock.assert_called_once_with(JNClient.ORDER_WITH_COINS_URL_PATTERN % 'v1', headers=mock.ANY)
        self.assertEqual(50, self.user.coins)

    def test_refuses_to_order_without_enough_coins(self) -> None:
        self.user.coins = 10
        with mock.patch('jnc_api_tools.requests.post') as post_mock:
            with self.assertRaises(NoCoinsError):
                JNClient.order_book(book=self.book, user_data=self.user)
        post_mock.assert_not_called()
        self.assertEqual(10, self.user.coins)

    def test_raises_when_the_book_is_already_ordered(self) -> None:
        with mock.patch('jnc_api_tools.requests.post', return_value=FakeResponse(409)):
            with self.assertRaises(JNCApiError) as ctx:
                JNClient.order_book(book=self.book, user_data=self.user)
        self.assertEqual('Book already ordered', str(ctx.exception))
        self.assertEqual(100, self.user.coins)

    def test_raises_on_server_errors(self) -> None:
        with mock.patch('jnc_api_tools.requests.post', return_value=FakeResponse(500)):
            with self.assertRaises(JNCApiError) as ctx:
                JNClient.order_book(book=self.book, user_data=self.user)
        self.assertEqual('Error when ordering book. Response was: 500', str(ctx.exception))


class JNClientBuyCoinsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = JNCUserData('u1', 'tester', 'tok', 100, 'PREMIUM')

    def test_refuses_amounts_below_the_purchase_minimum(self) -> None:
        with mock.patch('jnc_api_tools.requests.get') as get_mock, \
                mock.patch('jnc_api_tools.requests.post') as post_mock:
            with self.assertRaises(ArgumentError):
                JNClient.buy_coins(user_data=self.user, amount=499)
        get_mock.assert_not_called()
        post_mock.assert_not_called()
        self.assertEqual(100, self.user.coins)

    def test_raises_on_http_failure(self) -> None:
        with mock.patch('jnc_api_tools.requests.get', return_value=FakeResponse(200, {'id': 4242})), \
                mock.patch('jnc_api_tools.requests.post', return_value=FakeResponse(402)):
            with self.assertRaises(JNCApiError) as ctx:
                JNClient.buy_coins(user_data=self.user, amount=500)
        self.assertEqual('Could not purchase coins!', str(ctx.exception))
        self.assertEqual(100, self.user.coins)

    def test_raises_when_the_purchase_is_rejected(self) -> None:
        with mock.patch('jnc_api_tools.requests.get', return_value=FakeResponse(200, {'id': 4242})), \
                mock.patch('jnc_api_tools.requests.post',
                           return_value=FakeResponse(200, {'ok': False, 'message': 'card declined'})):
            with self.assertRaises(JNCApiError) as ctx:
                JNClient.buy_coins(user_data=self.user, amount=500)
        self.assertEqual('Could not purchase coins: card declined', str(ctx.exception))
        self.assertEqual(100, self.user.coins)

    def test_purchases_coins_and_returns_the_api_message(self) -> None:
        with mock.patch('jnc_api_tools.requests.get',
                        return_value=FakeResponse(200, {'id': 4242})) as get_mock, \
                mock.patch('jnc_api_tools.requests.post',
                           return_value=FakeResponse(200, {'ok': True, 'message': 'Purchased 500 coins'})) as post_mock:
            message = JNClient.buy_coins(user_data=self.user, amount=500)
        self.assertEqual('Purchased 500 coins', message)
        self.assertEqual(600, self.user.coins)
        get_mock.assert_called_once_with(JNClient.PAYMENT_METHOD_URL, headers=mock.ANY)
        post_mock.assert_called_once_with(
            JNClient.BUY_COINS_URL,
            headers=mock.ANY,
            json={
                'processor': 'STRIPE',
                'amount': 500,
                'stripe_payment_intent': {'payment_method': 4242},
            },
            allow_redirects=False,
        )


class ExceptionHierarchyTests(unittest.TestCase):
    def test_jnc_unauthorized_error_is_an_api_error(self) -> None:
        self.assertTrue(issubclass(JNCUnauthorizedError, JNCApiError))


if __name__ == '__main__':
    unittest.main()
