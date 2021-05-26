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
download_target_dir = '~/Downloads/'
downloaded_books_file = '~/.downloadedJncBooks.csv'  # Format book_id + \t + title_slug + \t + download date
owned_series_file = '~/.jncOwnedSeries.csv'  # Format series_title_slug + \t + followed (boolean)
token_file = '~/.jncToken'
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
parser.add_argument("--credits",
                    dest="credits",
                    action='store_const',
                    const=True,
                    default=False,
                    help="Enables buying credits. Each purchase requires confirmation by default."
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
parser.add_argument("--no-confirm-credits",
                    dest="no_confirm_credits",
                    action='store_const',
                    const=True,
                    default=False,
                    help="Disable user confirmations for buying premium credits and assume 'yes'. USE WITH CAUTION!!! This can spend money!"
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
enable_buy_credits = args.credits
update_books = args.update_books
no_confirm_order = args.no_confirm_all or args.no_confirm_order
no_confirm_series = args.no_confirm_all or args.no_confirm_series
no_confirm_credits = args.no_confirm_all or args.no_confirm_credits

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

while user_data is None:
    try:
        login = input('Enter login email: ')
        password = getpass()
        user_data = JNClient.login(login, password)
    except JNCApiError as e:
        print(e)

print(f'You have {user_data.premium_credits} credits')
if user_data.credit_price is not None:
    print(f'Each premium credit you buy costs ${user_data.credit_price}')
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
JNCUtils.print_books(new_books)
if enable_order_books:
    missing_credits = new_book_cnt - user_data.premium_credits
    if (missing_credits > 0) \
            and enable_buy_credits \
            and (no_confirm_credits
                 or JNCUtils.user_confirm(
                    f'{new_book_cnt} new books available. You have {user_data.premium_credits} '
                    f'credits available. Do you want to buy {missing_credits} credits '
                    f'for ${user_data.credit_price * missing_credits}?'
            )):
        while missing_credits > 0:
            buy_amount = min(10, missing_credits)
            print(f'Buying {buy_amount} credits')
            JNClient.buy_credits(user_data=user_data, amount=buy_amount)
            missing_credits -= buy_amount

    ordered_books = JNCUtils.handle_new_books(
        new_books=new_books,
        user_data=user_data,
        buy_credits=enable_buy_credits,
        no_confirm_credits=no_confirm_credits,
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
