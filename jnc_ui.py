"""
Console user interface of the jnc-downloader.

This is the only module that writes to stdout or reads from stdin.
The API layer (jnc_api_tools) returns data and messages; JNCConsoleUI turns
them into output and prompts, and jnc.py drives the interaction.
"""
from datetime import datetime, timezone
from getpass import getpass
from typing import Dict, List, Optional, Tuple

from jnc_api_tools import JNCBook, JNCUserData


class JNCConsoleUI:
    """All user-facing output and prompts of the downloader."""

    def info(self, message: str) -> None:
        """Print a status message to stdout."""
        print(message)

    def error(self, message: str) -> None:
        """Print an error message. Stays on stdout to preserve the original output behavior."""
        print(message)

    def confirm(self, message: str) -> bool:
        """Ask a yes/no question; only a literal 'y' counts as yes."""
        answer = input(message + ' (y/n)')
        return True if answer == 'y' else False

    def prompt_login(self) -> Tuple[str, str]:
        """Prompt for email and password; the password is not echoed."""
        login = input('Enter login email: ')
        password = getpass()
        return login, password

    def prompt_choice(self, message: str, options: List[str]) -> Optional[str]:
        """
        Print the options with their numbers and let the user pick one by number.

        Returns the chosen option, or None when the user cancels with 0.
        Answers that are no valid option number are asked again.
        """
        for option_index, option in enumerate(options, start=1):
            print(f'({option_index}) {option}')
        while True:
            answer = input(f'{message} (1-{len(options)}, 0 to cancel)')
            if answer == '0':
                return None
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return options[int(answer) - 1]
            self.error(f'Please enter a number between 1 and {len(options)}, or 0 to cancel.')

    def show_coin_balance(self, user_data: JNCUserData) -> None:
        """Print the current coin balance, plus the coin discount when there is one."""
        print(f'You have {user_data.coins} coins.')
        if user_data.coin_discount:
            print(f'You can buy coins at a {user_data.coin_discount}% discount.')

    def show_new_books(self, books: List[JNCBook]) -> None:
        """Print coin price and availability of the given books."""
        now = datetime.now(tz=timezone.utc)
        for book in books:
            availability = 'Preorder:' if now < book.publish_date else 'Available:'
            print(f'({book.price} coins) {availability}\t{book.title}')

    def show_preorders(self, library: Dict[str, JNCBook]) -> None:
        """Print all preorder books in the library with their release dates."""
        preorders = []
        for book in library.values():
            if book.is_preorder:
                preorders.append(book)
        if len(preorders):
            print('\nCurrent preorders (Release Date / Title):')
        for book in preorders:
            print(f'{book.publish_date} {book.title}')
