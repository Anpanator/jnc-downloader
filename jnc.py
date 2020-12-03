#!/usr/bin/env python3
from __future__ import print_function

import sys
from argparse import ArgumentParser

from jnc_api_tools import JNClient, JNCApiError, JNCDataHandler

MIN_PYTHON = (3, 7)
assert sys.version_info >= MIN_PYTHON, f'requires Python {".".join([str(n) for n in MIN_PYTHON])} or newer'

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

print(f'Available premium credits: {jnclient.available_credits}')
handler.handle_new_series()
handler.print_new_volumes()
unowned_books_amount = len(handler.get_orderable_books())
if unowned_books_amount > 0:
    print(
        f'\nTo buy all books, you will need {unowned_books_amount} premium credits, '
        f'you have {jnclient.available_credits}'
    )

if enable_order_books and unowned_books_amount > 0:
    if (jnclient.available_credits < unowned_books_amount) and enable_buy_credits:
        print(
            'If you do not buy all credits at once, you will be asked to buy credits for each volume once you run out'
        )
        handler.buy_credits(unowned_books_amount - jnclient.available_credits)

    handler.order_unowned_books(enable_buy_credits)

handler.print_preorders()
handler.download_new_books()
handler.write_downloaded_books_file()
handler.unfollow_complete_series()
handler.write_owned_series_file()

del jnclient
del handler
