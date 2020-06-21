from __future__ import print_function

import json
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

try:
    jnclient = JNClient(login_email, login_pw)
except JNCApiError as err:
    print(err)
    sys.exit(1)

# overwrite credentials to make sure they're not used later
login_email = None
login_pw = None


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


download_target_dir = os.path.expanduser(download_target_dir)

downloaded_books_list_file = os.path.expanduser(downloaded_books_list_file)
if not os.path.isfile(downloaded_books_list_file):
    open(downloaded_books_list_file, 'a').close()

owned_series_file = os.path.expanduser(owned_series_file)
if not os.path.isfile(owned_series_file):
    open(owned_series_file, 'a').close()

cur_time = datetime.now(timezone.utc).isoformat()[:23] + 'Z'

owned_books = jnclient.get_owned_books()

owned_books = sorted(
    owned_books,
    key=lambda book: (book['serie']['titleslug'], book['volumeNumber']))

owned_series = set()
for book in owned_books:
    owned_series.add(book['serie']['titleslug'])

series_follow_states = read_owned_series_file(owned_series_file)

# Ask the user if he wants to follow a new series he owns
# New volumes from followed series will be ordered automatically
for series_title_slug in owned_series:
    if series_title_slug not in series_follow_states:
        should_follow = input('%s is a new series. Do you want to follow it? (y/n)' % series_title_slug)
        series_follow_states[series_title_slug] = True if should_follow == 'y' else False

store_owned_series_file(owned_series_file, series_follow_states)

downloaded_book_ids = set()
if os.path.exists(downloaded_books_list_file):
    with open(downloaded_books_list_file, mode='r', newline='') as f:
        downloaded_book_ids = [row[0] for row in csv.reader(f, delimiter='\t')]

downloaded_books = {}
preordered_books = []

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

books_to_order = {}
# Check for new volumes in followed series
for series_title_slug in series_follow_states:
    if series_follow_states[series_title_slug]:
        series_info = jnclient.get_series_info(series_title_slug)
        for volume in series_info['volumes']:
            # Check if the volume is not yet owned
            if not any(d['id'] == volume['id'] for d in owned_books):
                books_to_order[volume['id']] = {'titleslug': volume['titleslug'], 'title': volume['title']}

# Save list of books that were downloaded
with open(downloaded_books_list_file, mode='w', newline='') as f:
    csv_writer = csv.writer(f, delimiter='\t')
    csv_writer.writerows(downloaded_books.items())

# Print unreleased preorders
if len(preordered_books) > 0:
    print('\nBooks scheduled to be released after %s' % cur_time)

    for book_title, book_id, book_time in preordered_books:
        print('%s  %s' % (book_time, book_title))

print('\nThe following new books of series you follow can be ordered:')
for book_id in books_to_order:
    print(books_to_order[book_id]['title'])

del jnclient
