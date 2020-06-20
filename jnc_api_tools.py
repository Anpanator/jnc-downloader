import requests


class JNClient:
    """Everything you need to talk to the JNC API"""

    BASE_URL = 'https://api.j-novel.club/api'
    LOGIN_URL = BASE_URL + '/users/login?include=user'
    API_USER_URL_PATTERN = BASE_URL + '/users/%s/'  # %s is the user id
    DOWNLOAD_BOOK_URL_PATTERN = BASE_URL + '/volumes/%s/getpremiumebook'  # %s is the book id
    LOGOUT_URL = BASE_URL + '/users/logout'

    def __init__(self, login_email, login_password):
        login_response = self.__login(login_email, login_password)

        if 'error' in login_response:
            raise RuntimeError('Login failed!')

        self.auth_token = login_response['id']
        self.user_id = login_response['user']['id']
        self.user_name = login_response['user']['username']

    def request_owned_books(self):
        """Requests the list of owned books from JNC.

        :return dict with information on the owned books (ids, titles, etc.)"""
        return requests.get(
            self.API_USER_URL_PATTERN % self.user_id,
            params={'filter': '{"include":[{"ownedBooks":"serie"}]}'},
            headers={'Authorization': self.auth_token}
        ).json()['ownedBooks']

    def download_book(self, book_id):
        """Will attempt to download a book from JNC
        :param book_id the id of the book.
        :return The response content
        :raise RuntimeError when the book is not available for download yet."""
        r = requests.get(
            self.DOWNLOAD_BOOK_URL_PATTERN % book_id,
            params={
                'userId': self.user_id,
                'userName': self.user_name,
                'access_token': self.auth_token
            }, allow_redirects=False
        )

        if r.status_code != 200:
            raise RuntimeError(str(r.status_code) + ': Book not available.')

        return r.content

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
