#!/usr/bin/env python3
from __future__ import print_function

import csv
import os
import sys
from argparse import ArgumentParser
from datetime import datetime
from getpass import getpass

from jnc_api_tools import JNCUnauthorizedError, JNClient, JNCApiError, JNCUtils

MIN_PYTHON = (3, 7)
assert sys.version_info >= MIN_PYTHON, f'requires Python {".".join([str(n) for n in MIN_PYTHON])} or newer'

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
        print(e)

while user_data is None:
    try:
        login = input('Enter login email: ')
        password = getpass()
        user_data = JNClient.login(login, password)
    except JNCApiError as e:
        print(e)

print(f'You have {user_data.coins} coins.')
if user_data.coin_discount:
    print(f'You can buy coins at a {user_data.coin_discount}% discount.')
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
    follow_new = no_confirm_series or JNCUtils.user_confirm(f'{series_slug} is a new series. Do you want to follow it?')
    series_follow_states[series_slug] = follow_new
    if follow_new:
        followed_series.append(series_slug)


series_info = JNClient.fetch_series(followed_series)
new_books = JNCUtils.get_unowned_books(library=library, series_info=series_info)
new_book_cnt = len(new_books)
print(f'There are {new_book_cnt} new volumes available:')
total_price = 0
for book in new_books:
    total_price += book.price
JNCUtils.print_books(new_books)
missing_coins = total_price - user_data.coins
if enable_order_books:
    coin_opts = JNClient.fetch_coin_options(user_data.auth_token)
    purchase_coins = max(missing_coins, coin_opts.purchaseMinimumCoins)
    cost = purchase_coins * (100 - coin_opts.coinDiscount) * coin_opts.coinPriceInCents / 10000
    if (missing_coins > 0) \
            and enable_buy_coins \
            and (no_confirm_coins
                 or JNCUtils.user_confirm(
                    f'{new_book_cnt} new books available. It will cost '
                    f'{total_price} coins to purchase them all. You have '
                    f'{user_data.coins} coins available. Purchase '
                    f'{purchase_coins} coins for ${cost:,.2f}?'
            )):
        while purchase_coins > 0:
            buy_amount = min(coin_opts.purchaseMaximumCoins, purchase_coins)
            print(f'Buying {buy_amount} coins')
            JNClient.buy_coins(user_data=user_data, amount=buy_amount)
            purchase_coins -= buy_amount


    ordered_books = JNCUtils.handle_new_books(
        new_books=new_books,
        user_data=user_data,
        buy_coins=enable_buy_coins,
        no_confirm_coins=no_confirm_coins,
        no_confirm_order=no_confirm_order)
    library |= ordered_books

library = JNCUtils.sort_books(library)

JNCUtils.print_preorders(library)

JNCUtils.process_library(
    library=library,
    downloaded_book_dates=downloaded_books_dates,
    target_dir=download_target_dir,
    include_updated=update_books
)

JNCUtils.unfollow_completed_series(
    downloaded_book_ids=[*downloaded_books_dates],
    series=series_info,
    series_follow_states=series_follow_states
)

with open(token_file, mode='w', newline='') as f:
    f.write(user_data.auth_token)

with open(downloaded_books_file, mode='w', newline='') as f:
    csv_writer = csv.writer(f, delimiter='\t')
    for book_id in downloaded_books_dates:
        csv_writer.writerow([book_id, library[book_id].title, downloaded_books_dates[book_id].isoformat()])

with open(owned_series_file, mode='w', newline='') as f:
    series_csv_writer = csv.writer(f, delimiter='\t')
    series_csv_writer.writerows(series_follow_states.items())
