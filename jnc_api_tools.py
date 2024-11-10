import csv
import os
from datetime import datetime, timezone
from typing import Dict, List, Set

import requests


class JNCUserData:
    user_id: str
    user_name: str
    auth_token: str
    coins: int
    account_type: str
    coin_discount: int = 0

    ACCOUNT_TYPE_PREMIUM = 'PREMIUM'
    ACCOUNT_TYPE_REGULAR = 'REGULAR'

    def __init__(self, user_id: str, user_name: str, auth_token: str, coins: int, account_type: str):
        self.user_id = user_id
        self.user_name = user_name
        self.auth_token = auth_token
        self.coins = coins
        self.account_type = account_type
        if self.ACCOUNT_TYPE_PREMIUM in account_type.upper():
            self.coin_discount = 15
        elif self.ACCOUNT_TYPE_REGULAR in account_type.upper():
            self.coin_discount = 5


class JNCBook:
    book_id: str
    title: str
    title_slug: str
    volume_id: str
    volume_num: int
    publish_date: datetime
    series_id: str
    series_slug: str
    is_owned: bool = None
    is_preorder: bool = None
    updated_date: datetime = None
    purchase_date: datetime = None
    download_link: str = None
    price: int

    def __init__(self, book_id: str, title: str, title_slug: str, volume_id: str, volume_num: int, publish_date: str, series_id: str,
                 series_slug: str, is_preorder: bool = None, is_owned: bool = None, updated_date: str = None,
                 purchase_date: str = None, download_link: str = None, price: int = 0):
        publish_date = publish_date.rstrip('Z').split('.')[0]
        self.publish_date = datetime.fromisoformat(publish_date).replace(tzinfo=timezone.utc)
        self.series_id = series_id
        self.volume_id = volume_id
        self.volume_num = volume_num
        self.title_slug = title_slug
        self.title = title
        self.book_id = book_id
        self.is_preorder = is_preorder
        self.series_slug = series_slug
        self.is_owned = is_owned
        self.download_link = download_link
        self._price = price
        if updated_date is not None:
            updated_date = updated_date.rstrip('Z').split('.')[0]
            self.updated_date = datetime.fromisoformat(updated_date).replace(tzinfo=timezone.utc)
        if purchase_date is not None:
            purchase_date = purchase_date.rstrip('Z').split('.')[0]
            self.purchase_date = datetime.fromisoformat(purchase_date).replace(tzinfo=timezone.utc)

    @property
    def price(self):
        if self._price > 0:
            return self._price
        price_response = requests.get(
            JNClient.FETCH_BOOK_PRICE_URL % self.title_slug,
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            }
        )
        if price_response.status_code != 200:
            raise JNCApiError(str(price_response.status_code) + ': Book price not available.')
        self._price = price_response.json()['coins']
        return self._price


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


class JNCCoinOptions:
    coinPriceInCents: int
    purchaseMinimumCoins: int
    purchaseMaximumCoins: int
    coinDiscount: int
    packs: [Dict[str, int]]

    def __init__(self, coinPriceInCents: int, purchaseMinimumCoins: int, purchaseMaximumCoins: int, packs: List[Dict[str, int]]):
        self.coinPriceInCents = coinPriceInCents
        self.purchaseMinimumCoins = purchaseMinimumCoins
        self.purchaseMaximumCoins = purchaseMaximumCoins
        self.packs = packs
        current, original = packs[0]['currentCentsCost'], packs[0]['originalCentsCost']
        self.coinDiscount = int((1-current/original)*100)

    def nearest_pack(self, amount) -> tuple[int, int]:
        for pack in self.packs:
            if pack['coins'] > amount:
                return pack['coins'], pack['currentCentsCost']
        return self.packs[-1]['coins'], self.packs[-1]['currentCentsCost']


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
    def print_books(books: List[JNCBook]):
        now = datetime.now(tz=timezone.utc)
        for book in books:
            availability = 'Preorder:' if now < book.publish_date else 'Available:'
            print(f'({book.price} coins) {availability}\t{book.title}')

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
    def unfollow_completed_series(downloaded_book_ids: List[str], series: Dict[str, JNCSeries],
                                  series_follow_states: Dict[str, bool]) -> None:
        for serie in series.values():
            is_completed = True
            if 'fully translated' not in serie.tags:
                continue
            for book_id in serie.volumes:
                if book_id not in downloaded_book_ids:
                    is_completed = False
                    break
            if is_completed:
                print(f'{serie.slug} is fully owned and translated. Series will be unfollowed.')
                series_follow_states[serie.slug] = False

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
                         buy_coins: bool = False, no_confirm_order: bool = False,
                         no_confirm_coins: bool = False) -> Dict[str, JNCBook]:
        """
        :param no_confirm_coins:
        :param no_confirm_order:
        :param buy_coins:
        :param user_data:
        :param new_books: Limited information JNCBooks from series info
        :return: dictionary {book_id: JNCBook} of ordered books
        """
        ordered_books = {}
        for book in new_books:
            print(f'You have {user_data.coins} coins')
            if not no_confirm_order and not JNCUtils.user_confirm(f'Do you want to order {book.title}?'):
                continue
            if user_data.coins == 0 and buy_coins \
                    and (no_confirm_coins or JNCUtils.user_confirm(f'Do you want to buy {book.price} coins?')):
                print(f'Buying {book.price} coins')
                JNClient.buy_coins(user_data=user_data, amount=book.price)
            if user_data.coins < book.price:
                print('Not enough coins, stopping order process!')
                break
            JNClient.order_book(book=book, user_data=user_data)
            ordered_books[book.book_id] = JNClient.fetch_owned_book_info(auth_token=user_data.auth_token,
                                                                         volume_id=book.volume_id)
            print(f'Ordered: {book.title}\n')
        return ordered_books


class JNClient:
    """
    Colletion of methods to talk to the JNC API

    Partial reference:
    https://forums.j-novel.club/topic/4370/developer-psa-current-epub-download-links-will-be-replaced-soon
    """

    LOGIN_URL = 'https://labs.j-novel.club/app/v2/auth/login?format=json'
    FETCH_USER_URL = 'https://labs.j-novel.club/app/v2/me?format=json'
    FETCH_LIBRARY_URL = 'https://labs.j-novel.club/app/v2/me/library?include=serie&format=json'
    BUY_COINS_URL = 'https://labs.j-novel.club/app/v2/me/coins/purchase?format=json'
    COINS_OPTIONS_URL = 'https://labs.j-novel.club/app/v2/me/coins/options?format=json'
    PAYMENT_METHOD_URL ='https://labs.j-novel.club/app/v2/me/method?format=json'
    FETCH_SERIES_URL = 'https://labs.j-novel.club/app/v2/series/%s/aggregate?format=json' # %s = series id or slug
    FETCH_SINGLE_BOOK = 'https://labs.j-novel.club/app/v2/me/library/volume/%s?include=serie&format=json'  # %s = volume id
    ORDER_WITH_COINS_URL_PATTERN = 'https://labs.j-novel.club/app/v2/me/coins/redeem/%s?format=json'  # %s volume id or slug
    FETCH_BOOK_PRICE_URL = 'https://labs.j-novel.club/app/v2/volumes/%s/price?format=json' # %s volume id or slug

    @staticmethod
    def login(user: str, password: str) -> JNCUserData:
        """
        :raise JNCApiError when the login failed
        """
        login_response = requests.post(
            JNClient.LOGIN_URL,
            headers={'Accept': 'application/json', 'content-type': 'application/json'},
            json={'login': user, 'password': password}
        ).json()

        if 'error' in login_response:
            raise JNCApiError('Login failed!')

        return JNClient.fetch_user_data(login_response['id'])

    @staticmethod
    def order_book(book: JNCBook, user_data: JNCUserData) -> None:
        """Order book on JNC side, i.e. redeem premium credit

        Notable responses:
            204: Success
            401: Unauthorized
            410: Session token expired
            404: Volume not found
            501: Can't buy manga at this time
            402: Not enough coins to purchase
            409: Already own this volume
            500: Internal server error (reported to us)
            Other: Unknown server error
        """
        if user_data.coins >= book.price:
            pattern = JNClient.ORDER_WITH_COINS_URL_PATTERN
        else:
            raise NoCoinsError('Not enough coins available to order book!')
        response = requests.post(
            pattern % book.volume_id,
            headers={'Authorization': f'Bearer {user_data.auth_token}'}
        )

        if response.status_code == 409:
            raise JNCApiError('Book already ordered')

        if not response.ok:
            raise JNCApiError(f'Error when ordering book. Response was: {response.status_code}')
        
        user_data.coins -= book.price

    @staticmethod
    def fetch_series(series_slugs: List[str]) -> Dict[str, JNCSeries]:
        """Fetch information about a series from JNC, including the volumes of the series"""
        result = {}
        for series_slug in series_slugs:
            r = requests.get(
                JNClient.FETCH_SERIES_URL % series_slug,
            )
            if not r.status_code < 300:
                raise JNCApiError(f'Could not fetch series details for {series_slug}')

            content = r.json()
            volumes = {}
            for volandparts in content['volumes']:
                volume=volandparts['volume']
                book_id = volume['legacyId']
                volumes[book_id] = JNCBook(
                    book_id=book_id,
                    title=volume['title'],
                    title_slug=volume['slug'],
                    volume_id=volume['id'],
                    volume_num=volume['number'],
                    publish_date=volume['publishing'],
                    series_id=content['series']['legacyId'],
                    series_slug=content['series']['slug']
                )

            result[series_slug] = JNCSeries(
                series_id=content['series']['legacyId'],
                slug=content['series']['slug'],
                tags=','.join(content['series']['tags']),
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
                'Authorization': f'Bearer {auth_token}'
            }
        )
        if user_response.status_code == 401:
            raise JNCUnauthorizedError
        if not user_response.status_code < 300:
            raise JNCApiError('Could not fetch user data!')

        return JNClient.create_jnc_user_data(auth_token, user_response.json())

    @staticmethod
    def fetch_coin_options(auth_token: str) -> JNCCoinOptions:
        coins_options_response = requests.get(
            JNClient.COINS_OPTIONS_URL,
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {auth_token}'
            }
        )
        resp = coins_options_response.json()
        return JNCCoinOptions(resp['coinPriceInCents'], resp['purchaseMinimumCoins'], resp['purchaseMaximumCoins'], resp['packs'])

    @staticmethod
    def fetch_payment_method_id(auth_token: str) -> int:
        payment_method_response = requests.get(
            JNClient.PAYMENT_METHOD_URL,
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {auth_token}'
            }
        )
        resp = payment_method_response.json()
        return resp['id']

    @staticmethod
    def create_jnc_user_data(auth_token: str, user_data: dict) -> JNCUserData:
        return JNCUserData(
            user_id=user_data['id'],
            user_name=user_data['username'],
            auth_token=auth_token,
            coins=user_data['coins'],
            account_type=user_data['level']
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
            volume_id=volume['id'],
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
    def buy_coins(user_data: JNCUserData, amount: int) -> None:
        """
        Buy coins on JNC.

        :raises ArgumentError   when amount is out of range
        :raises JNCApiError     when the purchase request fails for any reason
        """
        if 500 > amount:
            raise ArgumentError('It is not possible to buy less than 500 coins.')

        response = requests.post(
            JNClient.BUY_COINS_URL,
            headers={
                'Authorization': f'Bearer {user_data.auth_token}',
                'Accept': 'application/json',
                'Content-Type': 'application/json',
            },
            json={
                'processor':'STRIPE',
                'amount': amount,
                'stripe_payment_intent': {
                    'payment_method': JNClient.fetch_payment_method_id(user_data.auth_token)
                }
            },
            allow_redirects=False
        )

        if not response.status_code < 300:
            raise JNCApiError('Could not purchase coins!')

        resp = response.json()
        if response.status_code == 200 and resp['ok'] == False:
            message = resp['message']
            raise JNCApiError(f'Could not purchase coins: {message}')
        print(resp['message'])
        user_data.coins += amount

class JNCApiError(Exception):
    pass


class JNCUnauthorizedError(JNCApiError):
    pass


class NoCoinsError(Exception):
    pass


class ArgumentError(Exception):
    pass
