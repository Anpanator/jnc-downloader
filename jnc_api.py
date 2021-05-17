import csv
import os
from datetime import datetime, timezone
from typing import Dict, List, Set

import requests


class JNCUserData:
    user_id: str
    user_name: str
    auth_token: str
    premium_credits: int
    account_type: str
    credit_price: int = None

    ACCOUNT_TYPE_PREMIUM = 'PremiumMembership'

    def __init__(self, user_id: str, user_name: str, auth_token: str, premium_credits: int, account_type: str):
        self.user_id = user_id
        self.user_name = user_name
        self.auth_token = auth_token
        self.premium_credits = premium_credits
        self.account_type = account_type
        if self.ACCOUNT_TYPE_PREMIUM in account_type:
            self.credit_price = 6
        else:
            self.credit_price = 7


class JNCBook:
    book_id: str
    title: str
    title_slug: str
    volume_num: int
    publish_date: datetime
    series_id: str
    series_slug: str
    is_owned: bool = None
    is_preorder: bool = None
    updated_date: datetime = None
    purchase_date: datetime = None
    download_link: str = None

    def __init__(self, book_id: str, title: str, title_slug: str, volume_num: int, publish_date: str, series_id: str,
                 series_slug: str, is_preorder: bool = None, is_owned: bool = None, updated_date: str = None,
                 purchase_date: str = None, download_link: str = None):
        publish_date = publish_date.rstrip('Z').split('.')[0]
        self.publish_date = datetime.fromisoformat(publish_date).replace(tzinfo=timezone.utc)
        self.series_id = series_id
        self.volume_num = volume_num
        self.title_slug = title_slug
        self.title = title
        self.book_id = book_id
        self.is_preorder = is_preorder
        self.series_slug = series_slug
        self.is_owned = is_owned
        self.download_link = download_link
        if updated_date is not None:
            updated_date = updated_date.rstrip('Z').split('.')[0]
            self.updated_date = datetime.fromisoformat(updated_date).replace(tzinfo=timezone.utc)
        if purchase_date is not None:
            purchase_date = purchase_date.rstrip('Z').split('.')[0]
            self.purchase_date = datetime.fromisoformat(purchase_date).replace(tzinfo=timezone.utc)


class JNCSeries:
    id: str
    slug: str
    tags: str
    volumes: Dict[str, JNCBook]

    def __init__(self, series_id: str, slug: str, tags: str, volumes: Dict[str, JNCBook]):
        self.id = series_id
        self.slug = slug
        self.tags = tags
        self.volumes = volumes


class JNCUtils:
    @staticmethod
    def print_preorders(library: Dict[str, JNCBook]) -> None:
        preorders = []
        for book in library.values():
            if book.is_preorder:
                preorders.append(book)
        if len(preorders):
            print('\nCurrent preorders (Release Date / Title):')
        for book in preorders:
            print(f'{book.publish_date} {book.title}')

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
    def read_downloaded_books_file(csv_path: str) -> set:
        """First column of the csv is expected to be the book id"""
        with open(csv_path, mode='r', newline='') as f:
            book_ids = set([row[0] for row in csv.reader(f, delimiter='\t')])
        return book_ids

    @staticmethod
    def download_book(target_dir: str, book: JNCBook) -> None:
        if book.download_link is None:
            raise RuntimeError('Book does not have a download link.')

        download_response = requests.get(book.download_link)

        if download_response.status_code != 200:
            raise JNCApiError(str(download_response.status_code) + ': Book not available.')

        book_file_name = book.title_slug + '.epub'
        book_file_path = os.path.join(target_dir, book_file_name)

        with open(book_file_path, mode='wb') as f:
            f.write(download_response.content)

    @staticmethod
    def get_new_series(library: Dict[str, JNCBook], known_series: List[str]) -> List[str]:
        """
        :param library:
        :param known_series: List of series title slugs that are already known
        :return: List of series title slugs that are new
        """
        result = []
        for book in library.values():
            if book.series_slug != '' \
                    and book.series_slug not in known_series \
                    and book.series_slug not in result:
                result.append(book.series_slug)
        return result

    @staticmethod
    def get_unowned_books(library: Dict[str, JNCBook], series_info: Dict[str, JNCSeries]) -> List[JNCBook]:
        """
        Returns a list of book ids that are not yet owned, but available
        """
        result = []
        for series in series_info.values():
            for volume in series.volumes.values():
                if volume.book_id not in library:
                    result.append(volume)
        return result

    @staticmethod
    def unfollow_completed_series(library: Dict[str, JNCBook], series: Dict[str, JNCSeries],
                                  series_follow_states: Dict[str, bool]) -> None:
        # TODO
        pass

    @staticmethod
    def process_library(library: Dict[str, JNCBook], downloaded_book_dates: Dict[str, datetime], target_dir: str,
                        include_updated: bool = False) -> None:
        now = datetime.now(tz=timezone.utc).replace(microsecond=0)
        for book_id, book in library.items():
            if book.is_preorder is True \
                    or book.publish_date > now \
                    or book.download_link is None \
                    or book_id in downloaded_book_dates and not include_updated:
                continue

            if book_id not in downloaded_book_dates \
                    or (include_updated
                        and book.updated_date is not None
                        and downloaded_book_dates[book_id] < book.updated_date):
                try:
                    print(f'Downloading: {book.title}')
                    JNCUtils.download_book(target_dir=target_dir, book=book)
                    downloaded_book_dates[book_id] = now
                except JNCApiError as err:
                    print(err)

    @staticmethod
    def handle_new_books(new_books: List[JNCBook], user_data: JNCUserData,
                         buy_credits: bool = False) -> Dict[str, JNCBook]:
        """
        :param buy_credits:
        :param user_data:
        :param new_books: Limited information JNCBooks from series info
        :return: dictionary {book_id: JNCBook} of ordered books
        """
        ordered_books = {}
        for book in new_books:
            print(f'You have {user_data.premium_credits} credits')
            if not JNCUtils.user_confirm(f'Do you want to order {book.title}?'):
                continue
            if user_data.premium_credits == 0 and buy_credits \
                    and JNCUtils.user_confirm(f'Do you want to buy 1 credit?'):
                print('Buying 1 credit')
                user_data.premium_credits += 1
                JNClient.buy_credits(user_data=user_data, amount=1)
            if user_data.premium_credits == 0:
                print('Out of credits, stopping order process!')
                break
            JNClient.order_book(book=book, user_data=user_data)
            ordered_books[book.book_id] = JNClient.fetch_owned_book_info(auth_token=user_data.auth_token,
                                                                         volume_id=book.book_id)
            print(f'Ordered: {book.title}\n')
        return ordered_books


class JNClient:
    """
    Colletion of methods to talk to the JNC API

    Partial reference:
    https://forums.j-novel.club/topic/4370/developer-psa-current-epub-download-links-will-be-replaced-soon
    """

    LOGIN_URL = 'https://api.j-novel.club/api/users/login?include=user'
    FETCH_USER_URL = 'https://api.j-novel.club/api/users/me'  # ?filter={"include":[]}
    FETCH_LIBRARY_URL = 'https://labs.j-novel.club/app/v1/me/library?include=serie&format=json'
    BUY_CREDITS_URL = 'https://api.j-novel.club/api/users/me/purchasecredit'
    FETCH_SERIES_URL = 'https://api.j-novel.club/api/series/findOne'
    FETCH_SINGLE_BOOK = 'https://labs.j-novel.club/app/v1/me/library/volume/%s?include=serie&format=json'  # %s = volume id
    ORDER_URL_PATTERN = 'https://labs.j-novel.club/app/v1/me/redeem/%s'  # %s volume id

    @staticmethod
    def login(user: str, password: str) -> JNCUserData:
        """
        :raise JNCApiError when the login failed
        """
        login_response = requests.post(
            JNClient.LOGIN_URL,
            headers={'Accept': 'application/json', 'content-type': 'application/json'},
            json={'email': user, 'password': password}
        ).json()

        if 'error' in login_response:
            raise JNCApiError('Login failed!')

        return JNClient.create_jnc_user_data(login_response['id'], login_response['user'])

    @staticmethod
    def order_book(book: JNCBook, user_data: JNCUserData) -> None:
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
        if user_data.premium_credits <= 0:
            raise NoCreditsError('No credits available to order book!')

        response = requests.post(
            JNClient.ORDER_URL_PATTERN % book.book_id,
            headers={'Authorization': f'Bearer {user_data.auth_token}'}
        )

        if response.status_code == 409:
            raise JNCApiError('Book already ordered')

        if not response.ok:
            raise JNCApiError(f'Error when ordering book. Response was: {response.status_code}')

        user_data.premium_credits -= 1

    @staticmethod
    def fetch_series(series_slugs: List[str]) -> Dict[str, JNCSeries]:
        """Fetch information about a series from JNC, including the volumes of the series"""
        result = {}
        for series_slug in series_slugs:
            filter_string = '{"where":{"titleslug":"%s"},"include":["volumes"]}' % series_slug
            r = requests.get(
                JNClient.FETCH_SERIES_URL,
                params={'filter': filter_string}
            )
            if not r.status_code < 300:
                raise JNCApiError(f'Could not fetch series details for {series_slug}')

            content = r.json()
            volumes = {}
            for volume in content['volumes']:
                book_id = volume['id']
                volumes[book_id] = JNCBook(
                    book_id=book_id,
                    title=volume['title'],
                    title_slug=volume['titleslug'],
                    volume_num=volume['volumeNumber'],
                    publish_date=volume['publishingDate'],
                    series_id=content['id'],
                    series_slug=series_slug
                )

            result[series_slug] = JNCSeries(
                series_id=content['id'],
                slug=content['titleslug'],
                tags=content['tags'],
                volumes=volumes
            )
        return result

    @staticmethod
    def fetch_user_data(auth_token: str) -> JNCUserData:
        """
        Get user data with existing auth token.
        :raises JNCUnauthorizedError when the token is expired. Use login() instead in this case
        """
        user_response = requests.get(
            JNClient.FETCH_USER_URL,
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Authorization': auth_token
            }
        )
        if user_response.status_code == 401:
            raise JNCUnauthorizedError
        if not user_response.status_code < 300:
            raise JNCApiError('Could not fetch user data!')

        return JNClient.create_jnc_user_data(auth_token, user_response.json())

    @staticmethod
    def create_jnc_user_data(auth_token: str, user_data: dict) -> JNCUserData:
        subscription = user_data['currentSubscription']
        return JNCUserData(
            user_id=user_data['id'],
            user_name=user_data['username'],
            auth_token=auth_token,
            premium_credits=user_data['earnedCredits'] - user_data['usedCredits'],
            account_type=subscription['plan']['id'] if 'plan' in subscription else None
        )

    @staticmethod
    def fetch_library(auth_token: str) -> Dict[str, JNCBook]:
        response = requests.get(
            JNClient.FETCH_LIBRARY_URL,
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {auth_token}'
            }
        )

        if not response.status_code < 300:
            raise JNCApiError('Could not fetch library!')
        result = {}
        content = response.json()
        for item in content['books']:
            result[item['volume']['legacyId']] = JNClient.create_jnc_book_from_api_response_item(item)
        return result

    @staticmethod
    def fetch_owned_book_info(auth_token: str, volume_id: str) -> JNCBook:
        """
        Get single library book info. Book must be owned.
        """
        response = requests.get(
            JNClient.FETCH_SINGLE_BOOK % volume_id,
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {auth_token}'
            }
        )
        if not response.status_code < 300:
            raise JNCApiError(f'Could not fetch book info! Response: {response.status_code}')
        return JNClient.create_jnc_book_from_api_response_item(response.json())

    @staticmethod
    def create_jnc_book_from_api_response_item(item: dict) -> JNCBook:
        download_link = None
        for link in item['downloads']:
            download_link = link['link'] if link['type'] == 'EPUB' else None
            if download_link is not None:
                break

        volume = item['volume']
        return JNCBook(
            book_id=volume['legacyId'],
            title=volume['title'],
            title_slug=volume['slug'],
            volume_num=volume['number'],
            publish_date=volume['publishing'],
            updated_date=item.get('lastUpdated', None),
            purchase_date=item.get('purchased', None),
            is_preorder=True if item['status'] == 'PREORDER' else False,
            is_owned=volume['owned'],
            series_id=item.get('serie', {}).get('legacyId', None),
            series_slug=item.get('serie', {}).get('slug', None),
            download_link=download_link
        )

    @staticmethod
    def buy_credits(user_data: JNCUserData, amount: int) -> None:
        """
        Buy premium credits on JNC. Max. amount: 10. Price depends on membership status.

        :raises ArgumentError   when amount is out of range
        :raises JNCApiError     when the purchase request fails for any reason
        """
        if 0 >= amount > 10:
            raise ArgumentError('It is not possible to buy less than 1 or more than 10 credits.')

        response = requests.post(
            JNClient.BUY_CREDITS_URL,
            headers={
                'Accept': 'application/json',  # maybe */*?
                'Content-Type': 'application/json',
                'Authorization': user_data.auth_token
            },
            json={'number': amount},
            allow_redirects=False
        )

        if not response.status_code < 300:
            raise JNCApiError('Could not purchase credits!')

        user_data.premium_credits += amount


class JNCApiError(Exception):
    pass


class JNCUnauthorizedError(JNCApiError):
    pass


class NoCreditsError(Exception):
    pass


class ArgumentError(Exception):
    pass
