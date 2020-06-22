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
        :param book_title_slug the full title slug of the book, e.g. an-archdemon-s-dilemma-how-to-love-your-elf-bride-volume-9
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


class JNCApiError(Exception):
    """Exception for JNC API errors"""
    pass


class NoCreditsError(Exception):
    pass


class ArgumentError(Exception):
    pass
