import csv
from datetime import datetime, timezone
import os

import requests


class JNClient:
    """Everything you need to talk to the JNC API"""

    BASE_URL = 'https://api.j-novel.club/api'
    LOGIN_URL = BASE_URL + '/users/login?include=user'
    LOGOUT_URL = BASE_URL + '/users/logout'
    SERIES_INFO_URL = BASE_URL + '/series/findOne'
    API_USER_URL_PATTERN = BASE_URL + '/users/%s/'  # %s is the user id
    DOWNLOAD_BOOK_URL_PATTERN = BASE_URL + '/volumes/%s/getpremiumebook'  # %s is the book id
    ORDER_URL_PATTERN = BASE_URL + '/users/%s/redeemcredit'  # %s is user id
    BUY_CREDITS_URL_PATTERN = BASE_URL + '/users/%s/purchasecredit'  # %s is user id

    ACCOUNT_TYPE_PREMIUM = 'PremiumMembership'

    def __init__(self, login_email, login_password):
        login_response = self.__login(login_email, login_password)

        if 'error' in login_response:
            raise JNCApiError('Login failed!')

        self.auth_token = login_response['id']
        self.user_id = login_response['user']['id']
        self.user_name = login_response['user']['username']
        self.available_credits = login_response['user']['earnedCredits'] - login_response['user']['usedCredits']
        self.account_type = login_response['user']['currentSubscription']['plan']['id']

    def get_owned_books(self):
        """Requests the list of owned books from JNC.

        :return dict with information on the owned books (ids, titles, etc.)"""
        return requests.get(
            self.API_USER_URL_PATTERN % self.user_id,
            params={'filter': '{"include":[{"ownedBooks":"serie"}]}'},
            headers={'Authorization': self.auth_token}
        ).json()['ownedBooks']

    def order_book(self, book_title_slug):
        """Order book on JNC side, i.e. redeem premium credit

        Notable non-success responses:
            422 = book already ordered

        :param book_title_slug the full title slug of the book,
                               e.g. an-archdemon-s-dilemma-how-to-love-your-elf-bride-volume-9
        """
        if self.available_credits <= 0:
            raise NoCreditsError('No credits available to order book!')

        response = requests.post(
            self.ORDER_URL_PATTERN % self.user_id,
            json={'titleslug': book_title_slug},
            headers={'Authorization': self.auth_token}
        )

        if response.status_code == 422:
            raise JNCApiError('Book already ordered')

        if not response.ok:
            raise JNCApiError('Error when ordering book')
        self.available_credits -= 1

    def download_book(self, book_id):
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

    def get_series_info(self, series_title_slug):
        """Fetch information about a series from JNC, including the volumes of the series"""
        filter_string = '{"where":{"titleslug":"%s"},"include":["volumes"]}' % series_title_slug
        return requests.get(
            self.SERIES_INFO_URL,
            params={'filter': filter_string}
        ).json()

    def buy_credits(self, amount):
        """Buy premium credits on JNC. Max. amount: 10. Price depends on membership status."""
        if type(amount) is not int or (amount > 10) or (amount <= 0):
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

    def get_premium_credit_price(self):
        """Determines the price of premium credits based on account status"""
        if self.account_type == self.ACCOUNT_TYPE_PREMIUM:
            return 6
        else:
            return 7

    def __login(self, login_email, password):
        """Sends a login request to JNC. This method will not work if the user uses SSO (Google, Facebook)"""
        return requests.post(
            self.LOGIN_URL,
            headers={'Accept': 'application/json', 'content-type': 'application/json'},
            json={'email': login_email, 'password': password}
        ).json()

    def __logout(self):
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


class JNCDataHandler:
    def __init__(self, jnclient, owned_series_csv_path, owned_books_csv_path, download_dir, no_confirm_series=False,
                 no_confirm_credits=False, no_confirm_order=False):
        self.jnclient = jnclient
        self.owned_books = None
        self.owned_series = None
        self.followed_series_details = None
        self.series_follow_states = None
        self.downloaded_book_ids = None
        self.downloaded_books = {}
        self.preordered_books = {}
        self.unowned_books = None
        self.no_confirm_series = no_confirm_series
        self.no_confirm_credits = no_confirm_credits
        self.no_confirm_order = no_confirm_order

        self.cur_time = datetime.now(timezone.utc).isoformat()[:23] + 'Z'

        self.download_target_dir = os.path.expanduser(download_dir)
        self.downloaded_books_list_file = os.path.expanduser(owned_books_csv_path)
        self.owned_series_file = os.path.expanduser(owned_series_csv_path)

        self.__ensure_files_exist()
        self.read_downloaded_books_file()
        self.read_owned_series_file()

    def load_owned_books(self):
        owned_books = self.jnclient.get_owned_books()

        self.owned_books = sorted(
            owned_books,
            key=lambda book: (book['serie']['titleslug'], book['volumeNumber']))

    def load_owned_series(self):
        self.owned_series = set()
        for book in self.owned_books:
            self.owned_series.add(book['serie']['titleslug'])

    def handle_new_series(self):
        """"Ask the user if he wants to follow a new series he owns"""
        for series_title_slug in self.owned_series:
            if series_title_slug not in self.series_follow_states:
                self.series_follow_states[series_title_slug] = self.no_confirm_series or self.user_confirm(
                    '%s is a new series. Do you want to follow it?' % series_title_slug
                )

    def read_owned_series_file(self):
        series_follow_states = {}
        with open(self.owned_series_file, mode='r', newline='') as file:
            csv_reader = csv.reader(file, delimiter='\t')
            for series_row in csv_reader:
                series_follow_states[series_row[0]] = True if series_row[1] == 'True' else False
        self.series_follow_states = series_follow_states

    def read_downloaded_books_file(self):
        self.downloaded_book_ids = set()
        with open(self.downloaded_books_list_file, mode='r', newline='') as f:
            self.downloaded_book_ids = [row[0] for row in csv.reader(f, delimiter='\t')]

    def download_book(self, book):
        """:param book a single element from self.owned_books"""
        try:
            book_id = book['id']
            book_title = book['title']
            book_slug = book['titleslug']

            book_content = self.jnclient.download_book(book_id)

            book_file_name = book_slug + '.epub'
            book_file_path = os.path.join(self.download_target_dir, book_file_name)

            with open(book_file_path, mode='wb') as f:
                f.write(book_content)

            self.downloaded_books[book_id] = book_title
        except JNCApiError as err:
            print(err)

    def load_followed_series_details(self):
        self.followed_series_details = {}
        for series_title_slug in self.series_follow_states:
            if self.series_follow_states[series_title_slug]:
                self.followed_series_details[series_title_slug] = self.jnclient.get_series_info(series_title_slug)

    def load_unowned_books(self):
        self.unowned_books = {}
        """Check for new volumes in followed series"""
        for title_slug in self.followed_series_details:
            for volume in self.followed_series_details[title_slug]['volumes']:
                # Check if the volume is not yet owned
                if not any(d['id'] == volume['id'] for d in self.owned_books):
                    self.unowned_books[volume['id']] = {'titleslug': volume['titleslug'], 'title': volume['title']}

    def load_preordered_books(self):
        for book in self.owned_books:
            book_id = book['id']
            book_time = book['publishingDate']
            book_title = book['title']

            if book_time > self.cur_time:
                self.preordered_books[book_id] = {'title': book_title, 'id': book_id, 'time': book_time}

    def download_new_books(self):
        print('\nDownloading new books:')

        for book in self.owned_books:
            book_id = book['id']
            book_time = book['publishingDate']
            book_title = book['title']

            if book_id in self.downloaded_book_ids:
                self.downloaded_books[book_id] = book_title
                continue

            if book_id in self.preordered_books:
                continue

            print('%s \t%s \t%s' % (book_title, book_id, book_time))

            self.download_book(book)

    def buy_credits(self, credits_to_buy):
        print('\nAttempting to buy %i credits.' % credits_to_buy)
        unit_price = self.jnclient.get_premium_credit_price()
        print('Each premium credit will cost US$%i' % unit_price)
        while credits_to_buy > 0:
            purchase_batch = 10 if credits_to_buy > 10 else credits_to_buy
            price = purchase_batch * unit_price
            if self.no_confirm_credits \
                    or self.user_confirm('Do you want to buy %i premium credits for US$%i?' % (purchase_batch, price)):
                self.jnclient.buy_credits(purchase_batch)
                print('Successfully bought %i premium credits. ' % purchase_batch)
                credits_to_buy -= purchase_batch
                print('%i premium credits left to buy.\n' % credits_to_buy)
            else:
                # abort when user does not confirm
                break
            print('\n')

    def order_unowned_books(self, buy_individual_credits):
        print('\nOrdering unowned volumes of followed series:')
        new_books_ordered = False
        for book_id in self.unowned_books:
            print('Order book %s' % self.unowned_books[book_id]['title'])
            if self.no_confirm_order or self.user_confirm('Do you want to order?'):
                if (self.jnclient.available_credits == 0) and buy_individual_credits:
                    self.buy_credits(1)
                if self.jnclient.available_credits == 0:
                    print('No premium credits left. Stop order process.')
                    break
                self.jnclient.order_book(self.unowned_books[book_id]['titleslug'])
                print(
                    'Ordered %s! Remaining credits: %i\n'
                    % (self.unowned_books[book_id]['title'], self.jnclient.available_credits)
                )
                new_books_ordered = True
        if new_books_ordered:
            # refresh owned books list
            self.load_owned_books()

    def unfollow_complete_series(self):
        for series_title_slug in self.followed_series_details:
            series_has_new_volumes = False
            if 'fully translated' in self.followed_series_details[series_title_slug]['tags']:
                for volume in self.followed_series_details[series_title_slug]['volumes']:
                    book_id = volume['id']
                    if book_id not in self.downloaded_book_ids and book_id not in self.preordered_books:
                        series_has_new_volumes = True
                if not series_has_new_volumes:
                    print('%s is fully owned and completed. Series will not be followed anymore.'
                          % self.followed_series_details[series_title_slug]['title'])
                    self.series_follow_states[series_title_slug] = False

    def write_owned_series_file(self):
        with open(self.owned_series_file, mode='w', newline='') as f:
            series_csv_writer = csv.writer(f, delimiter='\t')
            series_csv_writer.writerows(self.series_follow_states.items())

    def write_downloaded_books_file(self):
        with open(self.downloaded_books_list_file, mode='w', newline='') as f:
            csv_writer = csv.writer(f, delimiter='\t')
            csv_writer.writerows(self.downloaded_books.items())

    def print_new_volumes(self):
        if len(self.unowned_books) > 0:
            print('\nThe following new books of series you follow can be ordered:')
        for book_id in self.unowned_books:
            print(self.unowned_books[book_id]['title'])

    def print_preorders(self):
        if len(self.preordered_books):
            print('\nCurrent preorders (Release Date / Title):')
        for book_id in self.preordered_books:
            print('%s  %s' % (self.preordered_books[book_id]['time'], self.preordered_books[book_id]['title']))

    def __ensure_files_exist(self):
        if not os.path.isfile(self.owned_series_file):
            open(self.owned_series_file, 'a').close()
        if not os.path.isfile(self.downloaded_books_list_file):
            open(self.downloaded_books_list_file, 'a').close()

    @staticmethod
    def user_confirm(message):
        answer = input(message + ' (y/n)')
        return True if answer == 'y' else False


class JNCBook:
    pass


class JNCApiError(Exception):
    """Exception for JNC API errors"""
    pass


class NoCreditsError(Exception):
    pass


class ArgumentError(Exception):
    pass
