import csv
import os
from datetime import datetime, timezone
from typing import List, Dict, Set

import requests


class JNClient:
    """Everything you need to talk to the JNC API"""

    BASE_URL = 'https://api.j-novel.club/api'
    LOGIN_URL = BASE_URL + '/users/login?include=user'
    LOGOUT_URL = BASE_URL + '/users/logout'
    SERIES_INFO_URL = BASE_URL + '/series/findOne'
    API_USER_URL_PATTERN = BASE_URL + '/users/%s/'  # %s is the user id
    DOWNLOAD_BOOK_URL_PATTERN = BASE_URL + '/volumes/%s/getpremiumebook'  # %s is the book id
    ORDER_URL_PATTERN_NEW = 'https://labs.j-novel.club/app/v1/me/redeem/%s'  # %s book id
    BUY_CREDITS_URL_PATTERN = BASE_URL + '/users/%s/purchasecredit'  # %s is user id

    ACCOUNT_TYPE_PREMIUM = 'PremiumMembership'

    def __init__(self, login_email, login_password) -> None:
        login_response = self.__login(login_email, login_password)

        if 'error' in login_response:
            raise JNCApiError('Login failed!')

        self.auth_token = login_response['id']
        self.user_id = login_response['user']['id']
        self.user_name = login_response['user']['username']
        self.available_credits = login_response['user']['earnedCredits'] - login_response['user']['usedCredits']

        subscription = login_response['user']['currentSubscription']

        self.account_type = subscription['plan']['id'] if 'plan' in subscription else None

    def get_owned_books(self) -> dict:
        """Requests the list of owned books from JNC.

        :return dict with information on the owned books (ids, titles, etc.)"""
        return requests.get(
            self.API_USER_URL_PATTERN % self.user_id,
            params={'filter': '{"include":[{"ownedBooks":"serie"}]}'},
            headers={'Authorization': self.auth_token}
        ).json()['ownedBooks']

    def order_book(self, book_id: str) -> None:
        """Order book on JNC side, i.e. redeem premium credit

        Notable responses:
            204: Success
            401: Unauthorized
            410: Session token expired
            404: Volume not found
            501: Can't buy manga at this time
            402: No credits left to redeem
            409: Already own this volume
            500: Internal server error (reported to us)
            Other: Unknown server error
        """
        if self.available_credits <= 0:
            raise NoCreditsError('No credits available to order book!')

        response = requests.post(
            self.ORDER_URL_PATTERN_NEW % book_id,
            headers={'Authorization': f'Bearer {self.auth_token}'}
        )

        if response.status_code == 409:
            raise JNCApiError('Book already ordered')

        if not response.ok:
            raise JNCApiError(f'Error when ordering book. Response was: {response.status_code}')

        self.available_credits -= 1

    def download_book(self, book_id: str) -> bytes:
        """Will attempt to download a book from JNC
        JNC does not respond with a standard 404 error when a book cannot be found (despite being marked as published)
        and instead will do a redirect to an error page, which itself reports a http 200

        :param book_id the id of the book.
        :return The response content
        :raise JNCApiError when the book is not available for download yet."""
        r = requests.get(
            self.DOWNLOAD_BOOK_URL_PATTERN % book_id,
            params={
                'userId': self.user_id,
                'userName': self.user_name,
                'access_token': self.auth_token
            }, allow_redirects=False
        )

        if r.status_code != 200:
            raise JNCApiError(str(r.status_code) + ': Book not available.')

        return r.content

    def get_series_info(self, series_title_slug: str) -> dict:
        """Fetch information about a series from JNC, including the volumes of the series"""
        filter_string = '{"where":{"titleslug":"%s"},"include":["volumes"]}' % series_title_slug
        return requests.get(
            self.SERIES_INFO_URL,
            params={'filter': filter_string}
        ).json()

    def buy_credits(self, amount: int) -> None:
        """Buy premium credits on JNC. Max. amount: 10. Price depends on membership status."""
        if (type(amount) is not int) or (0 >= amount > 10):
            raise ArgumentError('It is not possible to buy less than 1 or more than 10 credits.')

        response = requests.post(
            self.BUY_CREDITS_URL_PATTERN % self.user_id,
            headers={
                'Accept': 'application/json',
                'content-type': 'application/json',
                'Authorization': self.auth_token
            },
            json={'number': amount},
            allow_redirects=False
        )

        if not response.status_code < 300:
            raise JNCApiError('Could not purchase credits!')

        self.available_credits += amount

    def get_premium_credit_price(self) -> int:
        """Determines the price of premium credits based on account status"""
        if self.account_type is None:
            return None
        elif self.ACCOUNT_TYPE_PREMIUM in self.account_type:
            return 6
        else:
            return 7

    def __login(self, login_email, password) -> dict:
        """Sends a login request to JNC. This method will not work if the user uses SSO (Google, Facebook)"""
        return requests.post(
            self.LOGIN_URL,
            headers={'Accept': 'application/json', 'content-type': 'application/json'},
            json={'email': login_email, 'password': password}
        ).json()

    def __logout(self) -> None:
        """Does a logout request to JNC to invalidate the access token. Intended to be called automatically when the
        class instance is garbage collected."""
        requests.post(
            self.LOGOUT_URL,
            headers={'Authorization': self.auth_token}
        )
        print('Logged out')

    def __del__(self):
        try:
            if len(self.auth_token) > 0:
                self.__logout()
        except AttributeError:
            pass


class JNCBook:
    book_id: str
    title: str
    title_slug: str
    volume_num: int
    series_id: str
    series_slug: str = None
    release_date: datetime

    def __init__(self, book_id: str, title: str, title_slug: str, volume_num: int, series_id: str,
                 date_string_iso: str, series_slug: str = None):
        self.release_date = datetime.fromisoformat(date_string_iso.rstrip('Z')).replace(tzinfo=timezone.utc)
        self.series_id = series_id
        self.volume_num = volume_num
        self.title_slug = title_slug
        self.title = title
        self.book_id = book_id
        self.series_slug = series_slug


class JNCSeries:
    title_slug: str
    followed: bool = None
    is_detailed: bool = False

    series_id: str = None
    title: str = None
    tags: str = None
    volumes: Dict[str, JNCBook] = None

    def __init__(self, title_slug: str, followed: bool = None, series_id: str = None, is_detailed: bool = False,
                 title: str = None, volumes: Dict[str, JNCBook] = None, tags: str = None):
        self.tags = tags
        self.volumes = volumes
        self.title = title
        self.is_detailed = is_detailed
        self.series_id = series_id
        self.followed = followed
        self.title_slug = title_slug


class JNCDataHandler:
    jnclient: JNClient
    owned_books: Dict[str, JNCBook] = {}
    owned_series: Dict[str, JNCSeries] = {}
    owned_series_csv_path: str
    owned_books_csv_path: str
    download_dir: str
    no_confirm_series: bool
    no_confirm_credits: bool
    no_confirm_order: bool
    downloaded_book_ids: Set[str] = set()
    new_downloaded_books: Dict[str, str] = {}

    def __init__(self, jnclient: JNClient, owned_series_csv_path: str, owned_books_csv_path: str, download_dir: str,
                 no_confirm_series: bool = False, no_confirm_credits: bool = False, no_confirm_order: bool = False):
        self.jnclient = jnclient
        self.no_confirm_series = no_confirm_series
        self.no_confirm_credits = no_confirm_credits
        self.no_confirm_order = no_confirm_order
        self.cur_time = datetime.now(timezone.utc)
        self.download_target_dir = os.path.expanduser(download_dir)
        self.downloaded_books_list_file = os.path.expanduser(owned_books_csv_path)
        self.owned_series_file = os.path.expanduser(owned_series_csv_path)
        self.__ensure_files_exist()
        self.load_owned_books()
        self.load_owned_series()
        self.load_followed_series_details()
        self.read_downloaded_books_file()

    def load_owned_books(self) -> None:
        raw_owned_books = self.jnclient.get_owned_books()
        for raw_book in raw_owned_books:
            book = JNCUtils.build_jnc_book_from_api_response(raw_book)
            self.owned_books[book.book_id] = book

        self.owned_books = JNCUtils.sort_books(self.owned_books)

    def load_owned_series(self) -> None:
        for book in self.owned_books.values():
            if book.series_slug is not None and book.series_id not in self.owned_series:
                self.owned_series[book.series_id] = JNCSeries(book.series_slug, series_id=book.series_id)

    def handle_new_series(self) -> None:
        """"Ask the user if he wants to follow a new series he owns"""
        for series in self.owned_series.values():
            if series.followed is None:
                series.followed = self.no_confirm_series or JNCUtils.user_confirm(
                    f'{series.title} is a new series. Do you want to follow it?'
                )

    def read_owned_series_file(self) -> Dict[str, JNCSeries]:
        """Returns dictionary with series with the series title slug as key"""
        series = {}
        with open(self.owned_series_file, mode='r', newline='') as file:
            csv_reader = csv.reader(file, delimiter='\t')
            for series_row in csv_reader:
                series[series_row[0]] = JNCSeries(series_row[0], True if series_row[1] == 'True' else False)
        return series

    def read_downloaded_books_file(self) -> None:
        with open(self.downloaded_books_list_file, mode='r', newline='') as f:
            self.downloaded_book_ids = set([row[0] for row in csv.reader(f, delimiter='\t')])

    def download_book(self, book: JNCBook) -> None:
        try:
            book_content = self.jnclient.download_book(book.book_id)

            book_file_name = book.title_slug + '.epub'
            book_file_path = os.path.join(self.download_target_dir, book_file_name)

            with open(book_file_path, mode='wb') as f:
                f.write(book_content)

            self.new_downloaded_books[book.book_id] = book.title
        except JNCApiError as err:
            print(err)

    def load_followed_series_details(self) -> None:
        known_series = self.read_owned_series_file()

        for series_slug, cur_known_series in known_series.items():
            cur_owned_series = None
            for owned_series in self.owned_series.values():
                if owned_series.title_slug == series_slug:
                    cur_owned_series = owned_series
                    cur_owned_series.followed = cur_known_series.followed

            if cur_owned_series is None \
                    or cur_known_series.followed is False \
                    or cur_known_series.is_detailed is True:
                continue

            series_details = self.jnclient.get_series_info(series_slug)
            series_id = series_details['id']
            self.owned_series[series_id].title = series_details['title']
            self.owned_series[series_id].tags = series_details['tags']
            self.owned_series[series_id].is_detailed = True
            self.owned_series[series_id].volumes = {}

            for raw_book in series_details['volumes']:
                book = JNCUtils.build_jnc_book_from_api_response(raw_book)
                self.owned_series[series_id].volumes[book.book_id] = book

    def get_orderable_books(self) -> List[JNCBook]:
        orderable_books = []
        """Check for new volumes in followed series"""
        for series in self.owned_series.values():
            if series.followed is False or series.is_detailed is False:
                continue

            for book_id in series.volumes:
                if book_id not in self.owned_books:
                    orderable_books.append(series.volumes[book_id])
        return orderable_books

    def get_preorders(self) -> List[JNCBook]:
        preorders = []
        for book in self.owned_books.values():
            if book.release_date > self.cur_time:
                preorders.append(book)
        return preorders

    def download_new_books(self) -> None:
        print('\nDownloading new books:')
        preorders = self.get_preorders()
        for book in self.owned_books.values():

            if book.book_id in self.downloaded_book_ids:
                self.new_downloaded_books[book.book_id] = book.title
                continue

            # Skip preorders
            if any(book.book_id == preorder.book_id for preorder in preorders):
                continue

            print(f'{book.title} \t{book.book_id} \t{book.release_date}')

            self.download_book(book)

    def buy_credits(self, credits_to_buy) -> None:
        print(f'\nAttempting to buy {credits_to_buy} credits.')
        unit_price = self.jnclient.get_premium_credit_price()

        if unit_price is None:
            print('Inactive subscription, cannot buy credits')
            return

        print(f'Each premium credit will cost US${unit_price}')
        while credits_to_buy > 0:
            purchase_batch = 10 if credits_to_buy > 10 else credits_to_buy
            price = purchase_batch * unit_price
            if self.no_confirm_credits \
                    or JNCUtils.user_confirm(f'Do you want to buy {purchase_batch} premium credits for US${price}?'):
                self.jnclient.buy_credits(purchase_batch)
                print(f'Successfully bought {purchase_batch} premium credits. ')
                credits_to_buy -= purchase_batch
                print(f'{credits_to_buy} premium credits left to buy.')
            else:
                # abort when user does not confirm
                break
            print('\n')

    def order_unowned_books(self, buy_individual_credits) -> None:
        print('\nOrdering unowned volumes of followed series:')
        new_books_ordered = False
        for book in self.get_orderable_books():
            print(f'Order book {book.title}')
            if self.no_confirm_order or JNCUtils.user_confirm('Do you want to order?'):
                if (self.jnclient.available_credits == 0) and buy_individual_credits:
                    self.buy_credits(1)
                if self.jnclient.available_credits == 0:
                    print('No premium credits left. Stop order process.')
                    break
                self.jnclient.order_book(book.book_id)
                print(
                    f'Ordered {book.title}! Remaining credits: {self.jnclient.available_credits}\n'
                )
                new_books_ordered = True
        if new_books_ordered:
            # refresh data
            self.load_owned_books()

    def unfollow_complete_series(self) -> None:
        for series in self.owned_series.values():
            if not series.followed or 'fully translated' not in series.tags:
                continue

            for volume in series.volumes.values():
                if (volume.book_id in self.downloaded_book_ids) \
                        and not any(volume.book_id == preorder.book_id for preorder in self.get_preorders()):
                    print(f'{series.title} is fully owned and completed. Series will not be followed anymore.')
                    series.followed = False
                    continue

    def write_owned_series_file(self) -> None:
        follow_states = {}
        for series in self.owned_series.values():
            if series.followed is None:
                continue
            follow_states[series.title_slug] = series.followed

        with open(self.owned_series_file, mode='w', newline='') as f:
            series_csv_writer = csv.writer(f, delimiter='\t')
            series_csv_writer.writerows(follow_states.items())

    def write_downloaded_books_file(self) -> None:
        with open(self.downloaded_books_list_file, mode='w', newline='') as f:
            csv_writer = csv.writer(f, delimiter='\t')
            csv_writer.writerows(self.new_downloaded_books.items())

    def print_new_volumes(self) -> None:
        orderable_books = self.get_orderable_books()
        if len(orderable_books) > 0:
            print('\nThe following new books of series you follow can be ordered:')
        for book in orderable_books:
            print(book.title)

    def print_preorders(self) -> None:
        preorders = self.get_preorders()
        if len(preorders):
            print('\nCurrent preorders (Release Date / Title):')
        for book in preorders:
            print(f'{book.release_date} {book.title}')

    def __ensure_files_exist(self) -> None:
        if not os.path.isfile(self.owned_series_file):
            open(self.owned_series_file, 'a').close()
        if not os.path.isfile(self.downloaded_books_list_file):
            open(self.downloaded_books_list_file, 'a').close()


class JNCUtils:
    @staticmethod
    def user_confirm(message: str) -> bool:
        answer = input(message + ' (y/n)')
        return True if answer == 'y' else False

    @staticmethod
    def sort_books(books: Dict[str, JNCBook]) -> Dict[str, JNCBook]:
        """Sorts List of JNCBooks by their series slug and volume number and returns result"""
        sorted_book_ids = sorted(
            books,
            key=lambda k: (books[k].series_slug or books[k].title_slug, books[k].volume_num)
        )
        return {book_id: books[book_id] for book_id in sorted_book_ids}

    @staticmethod
    def build_jnc_book_from_api_response(raw_book_response: dict) -> JNCBook:
        return JNCBook(
            raw_book_response['id'],
            raw_book_response['title'],
            raw_book_response['titleslug'],
            raw_book_response['volumeNumber'],
            raw_book_response['serieId'],
            raw_book_response['publishingDate'],  # Format: 2020-07-12T05:00:00.000Z
            raw_book_response.get('serie', {}).get('titleslug', None)
        )


class JNCApiError(Exception):
    pass


class NoCreditsError(Exception):
    pass


class ArgumentError(Exception):
    pass
