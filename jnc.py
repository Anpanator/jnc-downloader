#!/usr/bin/env python3
from __future__ import print_function
from argparse import ArgumentParser

import sys
from jnc_api_tools import JNClient, JNCApiError, JNCDataHandler

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

handler = JNCDataHandler(jnclient, owned_series_file, downloaded_books_list_file, download_target_dir,
                         no_confirm_series, no_confirm_credits, no_confirm_order)

print('Available premium credits: %i' % jnclient.available_credits)
handler.read_owned_series_file()
handler.read_downloaded_books_file()

handler.load_owned_books()
handler.load_owned_series()
handler.load_preordered_books()
handler.load_followed_series_details()
handler.load_unowned_books()

handler.handle_new_series()

handler.print_new_volumes()

unowned_books_amount = len(handler.unowned_books)
if enable_order_books:
    buy_individual_credits = False
    print(
        '\nTo buy all books, you will need %i premium credits, you have %i' %
        (unowned_books_amount, jnclient.available_credits)
    )
    if jnclient.available_credits >= unowned_books_amount > 0:
        # No need to buy credits
        handler.order_unowned_books(False)
    elif enable_buy_credits and unowned_books_amount > 0:
        print(
            'If you do not buy all credits at once, you will be asked to buy credits for each volume once you run out'
        )
        handler.buy_credits(unowned_books_amount - jnclient.available_credits)

    buy_individual_credits = True if enable_buy_credits else False
    handler.order_unowned_books(buy_individual_credits)

handler.print_preorders()
handler.download_new_books()
handler.write_downloaded_books_file()
handler.unfollow_complete_series()
handler.write_owned_series_file()

del jnclient
del handler
