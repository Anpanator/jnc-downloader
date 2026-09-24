#!/usr/bin/env python3
import sys

# The version check must run before the other imports: jnc_api_tools uses
# builtin-generic annotations and fails to import on Python < 3.9.
MIN_PYTHON = (3, 9)
assert sys.version_info >= MIN_PYTHON, f'requires Python {".".join([str(n) for n in MIN_PYTHON])} or newer'

import csv
import os
from argparse import ArgumentParser
from datetime import datetime, timezone
from typing import Dict, List

from jnc_api_tools import JNCBook, JNCUserData, JNCApiError, JNClient, JNCUnauthorizedError, JNCUtils
from jnc_ui import JNCConsoleUI

# Config: START
# override with ENV vars, e.g. JNC_DOWNLOAD_TARGET_DIR="~/Documents/" ./jnc.py --order
download_target_dir = os.environ.get('JNC_DOWNLOAD_TARGET_DIR', '~/Downloads/')
downloaded_books_file = os.environ.get('JNC_DOWNLOADED_BOOKS_FILE', '~/.downloadedJncBooks.csv')  # Format book_id + \t + title_slug + \t + download date
owned_series_file = os.environ.get('JNC_OWNED_SERIES_FILE', '~/.jncOwnedSeries.csv')  # Format series_title_slug + \t + followed (boolean)
token_file = os.environ.get('JNC_TOKEN_FILE', '~/.jncToken')
login_email = os.environ.get('JNC_LOGIN_EMAIL', None) # Will prompt.
login_pw = os.environ.get('JNC_LOGIN_PW', None)
# -- or just redefine these variables between here and Config: END.

# Config: END

parser = ArgumentParser()
parser.add_argument("--order",
                    dest="order",
                    action='store_const',
                    const=True,
                    default=False,
                    help="Enables ordering books. Each order requires confirmation by default."
                    )
parser.add_argument("--update-books",
                    dest="update_books",
                    action='store_const',
                    const=True,
                    default=False,
                    help="Checks if books have been updated by JNC and downloads them again if that is the case."
                    )
parser.add_argument("--coins", "--credits",
                    dest="coins",
                    action='store_const',
                    const=True,
                    default=False,
                    help="Enables buying J-Novel coins. Each purchase requires confirmation by default."
                    )
parser.add_argument("--no-confirm-all",
                    dest="no_confirm_all",
                    action='store_const',
                    const=True,
                    default=False,
                    help="Disable all user confirmations and assume 'yes'. USE WITH CAUTION!!! This can spend money!"
                    )
parser.add_argument("--no-confirm-order",
                    dest="no_confirm_order",
                    action='store_const',
                    const=True,
                    default=False,
                    help="Disable user confirmations for ordering books and assume 'yes'. USE WITH CAUTION!!! This can spend money!"
                    )
parser.add_argument("--no-confirm-coins", "--no-confirm-credits",
                    dest="no_confirm_coins",
                    action='store_const',
                    const=True,
                    default=False,
                    help="Disable user confirmations for buying J-Novel coins and assume 'yes'. USE WITH CAUTION!!! This can spend money!"
                    )
parser.add_argument("--no-confirm-series-follow",
                    dest="no_confirm_series",
                    action='store_const',
                    const=True,
                    default=False,
                    help="Disable user confirmation for following new series."
                    )
args = parser.parse_args()
enable_order_books = args.order
enable_buy_coins = args.coins
update_books = args.update_books
no_confirm_order = args.no_confirm_all or args.no_confirm_order
no_confirm_series = args.no_confirm_all or args.no_confirm_series
no_confirm_coins = args.no_confirm_all or args.no_confirm_coins

download_target_dir = os.path.expanduser(download_target_dir)
downloaded_books_file = os.path.expanduser(downloaded_books_file)
owned_series_file = os.path.expanduser(owned_series_file)
token_file = os.path.expanduser(token_file)

# make sure files exist
open(downloaded_books_file, 'a').close()
open(owned_series_file, 'a').close()

# parse downloaded books file
downloaded_books_dates = {}
csv_is_legacy_format = False
with open(downloaded_books_file, mode='r', newline='') as f:
    for row in csv.reader(f, delimiter='\t'):
        if len(row) >= 3:
            downloaded_books_dates[row[0]] = datetime.fromisoformat(row[2])
        else:
            csv_is_legacy_format = True
            downloaded_books_dates[row[0]] = None

# parse owned series file
series_follow_states = {}
followed_series = []
with open(owned_series_file, mode='r', newline='') as f:
    csv_reader = csv.reader(f, delimiter='\t')
    for series_row in csv_reader:
        followed = True if series_row[1] == 'True' else False
        if followed:
            followed_series.append(series_row[0])
        series_follow_states[series_row[0]] = followed

try:
    with open(token_file, "r") as f:
        jnc_token = f.read()
except FileNotFoundError:
    jnc_token = None

ui = JNCConsoleUI()


def handle_new_books(ui: JNCConsoleUI, new_books: List[JNCBook],
                     user_data: JNCUserData, buy_coins: bool = False,
                     no_confirm_order: bool = False,
                     no_confirm_coins: bool = False) -> Dict[str, JNCBook]:
    """
    Interactively order the given new books, buying coins first when enabled and confirmed.

    :param ui: console UI for all prompts and status output
    :param new_books: books from series info that are not owned yet
    :param user_data: current user; the coin balance is updated in place
    :param buy_coins: allow a coin purchase when the balance is too low
    :param no_confirm_order: order each book without asking
    :param no_confirm_coins: buy coins without asking
    :return: dictionary {book_id: JNCBook} of ordered books
    """
    ordered_books = {}
    for book in new_books:
        ui.info(f'You have {user_data.coins} coins')
        if not no_confirm_order and not ui.confirm(f'Do you want to order {book.title}?'):
            continue
        if user_data.coins == 0 and buy_coins \
                and (no_confirm_coins or ui.confirm(f'Do you want to buy {book.price} coins?')):
            ui.info(f'Buying {book.price} coins')
            buy_message = JNClient.buy_coins(user_data=user_data, amount=book.price)
            ui.info(buy_message)
        if user_data.coins < book.price:
            ui.error('Not enough coins, stopping order process!')
            break
        JNClient.order_book(book=book, user_data=user_data)
        ordered_books[book.book_id] = JNClient.fetch_owned_book_info(
            auth_token=user_data.auth_token,
            volume_id=book.volume_id)
        ui.info(f'Ordered: {book.title}\n')
    return ordered_books


def process_library(ui: JNCConsoleUI, library: Dict[str, JNCBook],
                    downloaded_book_dates: Dict[str, datetime],
                    target_dir: str, include_updated: bool = False) -> None:
    """
    Download every library book that is due for download.

    Skips preorders, books that are not published yet, books without a download
    link, and already downloaded books. With include_updated, books whose
    updated_date is newer than the recorded download date are downloaded again.
    Prints per-book progress and a final summary so long download runs can be
    tracked.
    """
    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    due_books = []
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
            due_books.append((book_id, book))

    due_count = len(due_books)
    downloaded_count = 0
    for download_index, (book_id, book) in enumerate(due_books, start=1):
        try:
            ui.info(f'Downloading ({download_index}/{due_count}): {book.title}')
            JNCUtils.download_book(target_dir=target_dir, book=book)
            downloaded_book_dates[book_id] = now
            downloaded_count += 1
        except JNCApiError as err:
            ui.error(str(err))

    if due_count:
        ui.info(f'Downloaded {downloaded_count} of {due_count} books.')


user_data = None
try:
    if jnc_token is not None:
        user_data = JNClient.fetch_user_data(jnc_token)
except JNCUnauthorizedError:
    pass

if user_data is None and login_email and login_pw:
    try:
        user_data = JNClient.login(login_email, login_pw)
    except JNCApiError as e:
        ui.error(str(e))

while user_data is None:
    try:
        login, password = ui.prompt_login()
        user_data = JNClient.login(login, password)
    except JNCApiError as e:
        ui.error(str(e))

ui.show_coin_balance(user_data)

ui.info('Fetching your library...')
library = JNClient.fetch_library(user_data.auth_token)

"""
For compatibility with old csv formats, assume download date to be publish date or purchase date, whichever is greater,
and update the data to write back to the csv
"""
if csv_is_legacy_format:
    for book_id in downloaded_books_dates:
        if library[book_id].publish_date > library[book_id].purchase_date:
            assumed_update_date = library[book_id].publish_date
        else:
            assumed_update_date = library[book_id].purchase_date
        downloaded_books_dates[book_id] = assumed_update_date

new_series = JNCUtils.get_new_series(library=library, known_series=[*series_follow_states])
for series_slug in new_series:
    follow_new = no_confirm_series or ui.confirm(f'{series_slug} is a new series. Do you want to follow it?')
    series_follow_states[series_slug] = follow_new
    if follow_new:
        followed_series.append(series_slug)

series_info = {}
series_total = len(followed_series)
for series_index, series_slug in enumerate(followed_series, start=1):
    ui.info(f'Fetching series info ({series_index}/{series_total}): {series_slug}')
    series_info |= JNClient.fetch_series([series_slug])

new_books = JNCUtils.get_unowned_books(library=library, series_info=series_info)
new_book_cnt = len(new_books)
for price_index, book in enumerate(new_books, start=1):
    ui.info(f'Fetching book price ({price_index}/{new_book_cnt}): {book.title}')
    JNCUtils.fetch_book_prices([book])
ui.info(f'There are {new_book_cnt} new volumes available:')
total_price = 0
for book in new_books:
    total_price += book.price
ui.show_new_books(new_books)
missing_coins = total_price - user_data.coins
if enable_order_books:
    coin_opts = JNClient.fetch_coin_options(user_data.auth_token)
    purchase_coins = max(missing_coins, coin_opts.purchaseMinimumCoins)
    cost = purchase_coins * (100 - coin_opts.coinDiscount) * coin_opts.coinPriceInCents / 10000
    if (missing_coins > 0) \
            and enable_buy_coins \
            and (no_confirm_coins
                 or ui.confirm(
                    f'{new_book_cnt} new books available. It will cost '
                    f'{total_price} coins to purchase them all. You have '
                    f'{user_data.coins} coins available. Purchase '
                    f'{purchase_coins} coins for ${cost:,.2f}?'
            )):
        while purchase_coins > 0:
            buy_amount = min(coin_opts.purchaseMaximumCoins, purchase_coins)
            ui.info(f'Buying {buy_amount} coins')
            buy_message = JNClient.buy_coins(user_data=user_data, amount=buy_amount)
            ui.info(buy_message)
            purchase_coins -= buy_amount

    ordered_books = handle_new_books(
        ui=ui,
        new_books=new_books,
        user_data=user_data,
        buy_coins=enable_buy_coins,
        no_confirm_coins=no_confirm_coins,
        no_confirm_order=no_confirm_order)
    library |= ordered_books

library = JNCUtils.sort_books(library)

ui.show_preorders(library)

process_library(
    ui=ui,
    library=library,
    downloaded_book_dates=downloaded_books_dates,
    target_dir=download_target_dir,
    include_updated=update_books
)

unfollowed_series = JNCUtils.unfollow_completed_series(
    downloaded_book_ids=[*downloaded_books_dates],
    series=series_info,
    series_follow_states=series_follow_states
)
for series_slug in unfollowed_series:
    ui.info(f'{series_slug} is fully owned and translated. Series will be unfollowed.')

with open(token_file, mode='w', newline='') as f:
    f.write(user_data.auth_token)

with open(downloaded_books_file, mode='w', newline='') as f:
    csv_writer = csv.writer(f, delimiter='\t')
    for book_id in downloaded_books_dates:
        csv_writer.writerow([book_id, library[book_id].title, downloaded_books_dates[book_id].isoformat()])

with open(owned_series_file, mode='w', newline='') as f:
    series_csv_writer = csv.writer(f, delimiter='\t')
    series_csv_writer.writerows(series_follow_states.items())
