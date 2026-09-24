"""
Shared helpers for the jnc-downloader unittest suite.

The tests never talk to the real JNC API: every HTTP call goes through a fake
requests implementation. They also never import jnc — importing it executes
the whole download flow (API calls, login prompt, downloads, state writes) —
so the workflow functions are pulled out of jnc.py's source via ast instead
(see load_workflow_functions).
"""
import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from jnc_api_tools import JNCBook, JNCApiError, JNClient, JNCUserData, JNCUtils
from jnc_ui import JNCConsoleUI

REPO_ROOT = Path(__file__).resolve().parent
JNC_SOURCE = (REPO_ROOT / 'jnc.py').read_text(encoding='utf-8')

PAST_PUBLISH = '2020-01-01T00:00:00.000000Z'
FUTURE_PUBLISH = '2030-01-01T00:00:00.000000Z'


class FakeResponse:
    """Stand-in for requests.Response with just the surface the code uses."""

    def __init__(self, status_code: int, json_data: Optional[dict] = None, content: bytes = b'') -> None:
        self.status_code = status_code
        self.content = content
        self.text = content.decode('utf-8', errors='replace')
        self._json_data = json_data

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> dict:
        if self._json_data is None:
            raise AssertionError('fake response has no JSON body')
        return self._json_data


class FakeConsoleUI(JNCConsoleUI):
    """JNCConsoleUI stand-in that records output instead of printing it."""

    def __init__(self, confirm_answers: Optional[List[bool]] = None,
                 choice_answers: Optional[List[Optional[str]]] = None) -> None:
        super().__init__()
        self.infos: List[str] = []
        self.errors: List[str] = []
        self.confirms: List[str] = []
        self.choice_prompts: List[Tuple[str, List[str]]] = []
        self._confirm_answers = iter(confirm_answers or [])
        self._choice_answers = iter(choice_answers or [])

    def info(self, message: str) -> None:
        self.infos.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def confirm(self, message: str) -> bool:
        self.confirms.append(message)
        return next(self._confirm_answers, False)

    def prompt_choice(self, message: str, options: List[str]) -> Optional[str]:
        self.choice_prompts.append((message, options))
        return next(self._choice_answers, None)


def api_volume(book_id: str, title: str, title_slug: str, volume_id: str, number: int, publishing: str) -> dict:
    """A 'volume' sub-dict as found in JNC API responses."""
    return {
        'legacyId': book_id,
        'title': title,
        'slug': title_slug,
        'id': volume_id,
        'number': number,
        'publishing': publishing,
        'owned': True,
    }


def api_library_item(volume: dict, *, status: str = 'OWNED', downloads: Optional[List[dict]] = None,
                     last_updated: Optional[str] = None, purchased: Optional[str] = None,
                     serie: Optional[dict] = None) -> dict:
    """A library entry as returned by the library and single-volume endpoints."""
    item = {'downloads': downloads or [], 'volume': volume, 'status': status}
    if last_updated is not None:
        item['lastUpdated'] = last_updated
    if purchased is not None:
        item['purchased'] = purchased
    if serie is not None:
        item['serie'] = serie
    return item


def api_user_json(*, coins: int = 42, level: str = 'PREMIUM') -> dict:
    """A 'me' response as returned by the user endpoint."""
    return {'id': 'user-1', 'username': 'tester', 'coins': coins, 'level': level}


def api_series_aggregate(slug: str, volumes: List[dict], *, tags: Optional[List[str]] = None) -> dict:
    """A series aggregate as returned by the series endpoint."""
    return {
        'series': {'legacyId': 'S1', 'slug': slug, 'tags': list(tags or [])},
        'volumes': [{'volume': volume} for volume in volumes],
    }


def epub_download(link: str) -> dict:
    return {'type': 'EPUB', 'link': link}


def make_book(book_id: str, title: str, *, volume_id: Optional[str] = None,
              title_slug: Optional[str] = None, volume_num: int = 1,
              series_slug: str = 'my-series', price: int = 0,
              publish_date: str = PAST_PUBLISH, download_link: Optional[str] = None,
              is_preorder: bool = False, updated_date: Optional[str] = None) -> JNCBook:
    """JNCBook factory for tests that need pre-parsed books."""
    return JNCBook(
        book_id=book_id,
        title=title,
        title_slug=title_slug or book_id,
        volume_id=volume_id or f'v-{book_id}',
        volume_num=volume_num,
        publish_date=publish_date,
        series_id='S1',
        series_slug=series_slug,
        is_preorder=is_preorder,
        updated_date=updated_date,
        download_link=download_link,
        price=price,
    )


def load_workflow_functions() -> Dict[str, Callable]:
    """
    Returns jnc.py's workflow functions without executing the script.

    jnc.py runs its whole flow at module top level, so it must never be
    imported by tests. Instead its source is parsed and only the
    handle_new_books/process_library/handle_unfollow definitions are compiled
    and executed in a controlled namespace.
    """
    tree = ast.parse(JNC_SOURCE, filename='jnc.py')
    wanted = [node for node in tree.body
              if isinstance(node, ast.FunctionDef)
              and node.name in ('handle_new_books', 'process_library', 'handle_unfollow')]
    if {node.name for node in wanted} != {'handle_new_books', 'process_library', 'handle_unfollow'}:
        raise AssertionError('jnc.py no longer defines handle_new_books, process_library, '
                             'and handle_unfollow at top level')
    namespace: Dict[str, Any] = {
        'JNCBook': JNCBook,
        'JNCUserData': JNCUserData,
        'JNCApiError': JNCApiError,
        'JNClient': JNClient,
        'JNCUtils': JNCUtils,
        'JNCConsoleUI': JNCConsoleUI,
        'Dict': Dict,
        'List': List,
        'Optional': Optional,
        'datetime': datetime,
        'timezone': timezone,
    }
    exec(compile(ast.Module(body=wanted, type_ignores=[]), 'jnc.py', 'exec'), namespace)
    return namespace
