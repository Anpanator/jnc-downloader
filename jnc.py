#!/usr/bin/env python3
from __future__ import print_function
from argparse import ArgumentParser

import sys
import os
import csv
from datetime import datetime, timezone
from jnc_api_tools import JNClient, JNCApiError

# Config: START
login_email = 'user'
login_pw = 'password'

download_target_dir = '~/Downloads/'
downloaded_books_list_file = '~/.downloadedJncBooks.csv'  # Format book_id + \t + title_slug
owned_series_file = '~/.jncOwnedSeries.csv'  # Format series_title_slug + \t + followed (boolean)

# Config: END

parser = ArgumentParser()
parser.add_argument("--order",
                    dest="order",
                    action='store_const',
                    const=True,
                    default=False,
                    help="Enables ordering books. Each order requires confirmation by default."
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
no_confirm_order = args.no_confirm_all or args.no_confirm_order
no_confirm_series = args.no_confirm_all or args.no_confirm_series
no_confirm_credits = args.no_confirm_all or args.no_confirm_credits

try:
    jnclient = JNClient(login_email, login_pw)
except JNCApiError as err:
    print(err)
    sys.exit(1)

# overwrite credentials to make sure they're not used later
login_email = None
login_pw = None
print('Available premium credits: %i' % jnclient.available_credits)


def read_owned_series_file(file_path):
    """:return dictionary like {"title_slug": boolean}"""
    stored_owned_series = {}
    with open(file_path, mode='r', newline='') as file:
        csv_reader = csv.reader(file, delimiter='\t')
        for series_row in csv_reader:
            stored_owned_series[series_row[0]] = True if series_row[1] == 'True' else False

    return stored_owned_series


def store_owned_series_file(file_path, data):
    with open(file_path, mode='w', newline='') as f:
        series_csv_writer = csv.writer(f, delimiter='\t')
        series_csv_writer.writerows(data.items())


def download_book(book_id, book_title, downloaded_books):
    try:
        book_content = jnclient.download_book(book_id)

        downloaded_books[book_id] = book_title

        with open(book_file_path, mode='wb') as f:
            f.write(book_content)
    except JNCApiError as err:
        print(err)


def print_new_volumes(books_to_order):
    if len(books_to_order) > 0:
        print('\nThe following new books of series you follow can be ordered:')
    for book_id in books_to_order:
        print(books_to_order[book_id]['title'])


def buy_credits(credits_to_buy, no_confirm):
    print('Attempting to buy %i credits.' % credits_to_buy)
    unit_price = jnclient.get_premium_credit_price()
    print('Each premium credit will cost US$%i' % unit_price)
    while credits_to_buy > 0:
        purchase_batch = 10 if credits_to_buy > 10 else credits_to_buy
        price = purchase_batch * unit_price
        if no_confirm or user_confirm('Do you want to buy %i premium credits for US$%i?' % (purchase_batch, price)):
            jnclient.buy_credits(purchase_batch)
            print('Successfully bought %i premium credits. ' % purchase_batch)
            credits_to_buy -= purchase_batch
            print('%i premium credits left to buy.\n' % credits_to_buy)
        else:
            # abort when user does not confirm
            break
        print('\n')


def order_books(books_to_order, no_confirm, buy_individual_credits):
    for book_id in books_to_order:
        print('Order book %s' % books_to_order[book_id]['title'])
        if no_confirm or user_confirm('Do you want to order?'):
            if (jnclient.available_credits == 0) and buy_individual_credits:
                buy_credits(1, False)
            if jnclient.available_credits == 0:
                print('No premium credits left. Stop order process.')
                return
            jnclient.order_book(books_to_order[book_id]['titleslug'])
            print(
                'Ordered %s! Remaining credits: %i\n' % (books_to_order[book_id]['title'], jnclient.available_credits)
            )


def user_confirm(message):
    answer = input(message + ' (y/n)')
    return True if answer == 'y' else False


download_target_dir = os.path.expanduser(download_target_dir)

downloaded_books_list_file = os.path.expanduser(downloaded_books_list_file)
if not os.path.isfile(downloaded_books_list_file):
    open(downloaded_books_list_file, 'a').close()

owned_series_file = os.path.expanduser(owned_series_file)
if not os.path.isfile(owned_series_file):
    open(owned_series_file, 'a').close()

cur_time = datetime.now(timezone.utc).isoformat()[:23] + 'Z'

owned_books = jnclient.get_owned_books()
owned_series = set()
for book in owned_books:
    owned_series.add(book['serie']['titleslug'])

series_follow_states = read_owned_series_file(owned_series_file)

# Ask the user if he wants to follow a new series he owns
# New volumes from followed series will be ordered automatically
for series_title_slug in owned_series:
    if series_title_slug not in series_follow_states:
        series_follow_states[series_title_slug] = no_confirm_series or user_confirm(
            '%s is a new series. Do you want to follow it?' % series_title_slug
        )

store_owned_series_file(owned_series_file, series_follow_states)

downloaded_book_ids = set()
if os.path.exists(downloaded_books_list_file):
    with open(downloaded_books_list_file, mode='r', newline='') as f:
        downloaded_book_ids = [row[0] for row in csv.reader(f, delimiter='\t')]

books_to_order = {}
# Check for new volumes in followed series
for series_title_slug in series_follow_states:
    if series_follow_states[series_title_slug]:
        series_info = jnclient.get_series_info(series_title_slug)
        for volume in series_info['volumes']:
            # Check if the volume is not yet owned
            if not any(d['id'] == volume['id'] for d in owned_books):
                books_to_order[volume['id']] = {'titleslug': volume['titleslug'], 'title': volume['title']}

print_new_volumes(books_to_order)
books_to_order_amount = len(books_to_order)
if enable_order_books and books_to_order_amount > 0:
    print(
        '\nTo buy all books, you will need %i premium credits, you have %i' %
        (books_to_order_amount, jnclient.available_credits)
    )
    if enable_buy_credits:
        print(
            'If you do not buy all credits at once, you will be asked to buy credits for each volume once you run out\n')
        buy_credits(books_to_order_amount - jnclient.available_credits, no_confirm_credits)

if enable_order_books:
    order_books(books_to_order, no_confirm_order, enable_buy_credits)

print('\nDownloading books:')
downloaded_books = {}
preordered_books = []
if enable_order_books:
    # fetch owned books again to include the volumes that may have been ordered
    owned_books = jnclient.get_owned_books()

owned_books = sorted(
    owned_books,
    key=lambda book: (book['serie']['titleslug'], book['volumeNumber']))

for book in owned_books:
    book_id = book['id']
    book_time = book['publishingDate']
    book_title = book['title']

    if book_id in downloaded_book_ids:
        downloaded_books[book_id] = book_title
        continue

    if book_time > cur_time:
        preordered_books.append([book_title, book_id, book_time])
        continue

    print('%s \t%s \t%s' % (book_title, book_id, book_time))

    book_file_name = book['titleslug'] + '.epub'
    book_file_path = os.path.join(download_target_dir, book_file_name)

    download_book(book_id, book_title, downloaded_books)

# Save list of books that were downloaded
with open(downloaded_books_list_file, mode='w', newline='') as f:
    csv_writer = csv.writer(f, delimiter='\t')
    csv_writer.writerows(downloaded_books.items())

# Print unreleased preorders
if len(preordered_books) > 0:
    print('\nPre-ordered books that are not released yet (Release date / Title):')

    for book_title, book_id, book_time in preordered_books:
        print('%s  %s' % (book_time, book_title))

del jnclient
