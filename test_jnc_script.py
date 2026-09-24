"""
Integration tests: jnc.py runs end to end against a fake JNC API.

jnc.py executes its whole flow on import, so the compiled source is exec'd
inside run_jnc_script with:
- requests.get/post patched to a FakeJncApi (unknown URLs fail loudly),
- all JNC_* config env vars pointing at a temp sandbox,
- stdin/getpass patched (scripted answers, or a hard error when a test does
  not expect an interactive prompt).

No test in this file (or the suite) reaches the real network.
"""
import contextlib
import csv
import io
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

from jnc_api_tools import JNClient
from jnc_test_support import (FUTURE_PUBLISH, JNC_SOURCE, REPO_ROOT, FakeResponse,
                              api_library_item, api_series_aggregate, api_user_json,
                              api_volume, epub_download)

JNC_CODE = compile(JNC_SOURCE, str(REPO_ROOT / 'jnc.py'), 'exec')

VOL_ONE = api_volume('B1', 'Book One', 'book-one', 'v1', 1, '2020-01-01T00:00:00.000000Z')
VOL_TWO = api_volume('B2', 'Book Two', 'book-two', 'v2', 2, '2020-06-01T00:00:00.000000Z')
VOL_FUTURE = api_volume('B3', 'Future Book', 'future-book', 'v3', 3, FUTURE_PUBLISH)
SERIE = {'legacyId': 'S1', 'slug': 'my-series'}
ONE_EPUB = 'https://dl.example/book-one.epub'
TWO_EPUB = 'https://dl.example/book-two.epub'


class FakeJncApi:
    """Fake requests implementation serving a canned JNC API; fails loudly on unknown URLs."""

    def __init__(self, *, user_json: Optional[dict] = None,
                 library_items: Optional[List[dict]] = None,
                 series_aggregates: Optional[Dict[str, dict]] = None,
                 prices: Optional[Dict[str, int]] = None,
                 owned_volume_items: Optional[Dict[str, dict]] = None,
                 coin_options: Optional[dict] = None,
                 downloads: Optional[Dict[str, bytes]] = None,
                 login_responses: Optional[List[dict]] = None) -> None:
        self.user_json = user_json if user_json is not None else api_user_json()
        self.library_items = library_items or []
        self.series_aggregates = series_aggregates or {}
        self.prices = prices or {}
        self.owned_volume_items = owned_volume_items or {}
        self.coin_options = coin_options
        self.downloads = downloads or {}
        self.login_responses = list(login_responses or [{'id': 'tok-1'}])
        self.calls: List[Tuple[str, str]] = []
        self.orders: List[str] = []
        self.coin_purchases: List[int] = []
        self.downloaded_urls: List[str] = []

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(('GET', url))
        if url == JNClient.FETCH_USER_URL:
            return FakeResponse(200, self.user_json)
        if url == JNClient.FETCH_LIBRARY_URL:
            return FakeResponse(200, {'books': self.library_items})
        if '/series/' in url:
            slug = url.split('/series/', 1)[1].split('/aggregate', 1)[0]
            if slug not in self.series_aggregates:
                return FakeResponse(404, {'error': f'unknown series: {slug}'})
            return FakeResponse(200, self.series_aggregates[slug])
        if '/me/library/volume/' in url:
            volume_id = url.split('/me/library/volume/', 1)[1].split('?', 1)[0]
            if volume_id not in self.owned_volume_items:
                raise AssertionError(f'no owned volume info for {volume_id}')
            return FakeResponse(200, self.owned_volume_items[volume_id])
        if '/volumes/' in url and '/price' in url:
            title_slug = url.split('/volumes/', 1)[1].split('/price', 1)[0]
            if title_slug not in self.prices:
                raise AssertionError(f'no price for {title_slug}')
            return FakeResponse(200, {'coins': self.prices[title_slug]})
        if url == JNClient.COINS_OPTIONS_URL:
            if self.coin_options is None:
                raise AssertionError('coin options requested but not configured')
            return FakeResponse(200, self.coin_options)
        if url == JNClient.PAYMENT_METHOD_URL:
            return FakeResponse(200, {'id': 4242})
        if url in self.downloads:
            self.downloaded_urls.append(url)
            return FakeResponse(200, content=self.downloads[url])
        raise AssertionError(f'unexpected GET: {url}')

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append(('POST', url))
        if url == JNClient.LOGIN_URL:
            if not self.login_responses:
                raise AssertionError('no login response left')
            return FakeResponse(200, self.login_responses.pop(0))
        if '/me/coins/redeem/' in url:
            volume_id = url.split('/me/coins/redeem/', 1)[1].split('?', 1)[0]
            self.orders.append(volume_id)
            return FakeResponse(204)
        if url == JNClient.BUY_COINS_URL:
            amount = kwargs['json']['amount']
            self.coin_purchases.append(amount)
            return FakeResponse(200, {'ok': True, 'message': f'Purchased {amount} coins'})
        raise AssertionError(f'unexpected POST: {url}')


def owned_item(volume: dict, *, status: str = 'OWNED') -> dict:
    return api_library_item(
        volume,
        status=status,
        downloads=[epub_download(f"https://dl.example/{volume['slug']}.epub")],
        last_updated='2021-01-01T00:00:00.000000Z',
        purchased='2020-02-01T00:00:00.000000Z',
        serie=SERIE,
    )


class ScriptSandbox:
    """Temp dirs and files standing in for the user's real state files."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.target_dir = root / 'books'
        self.target_dir.mkdir()
        self.token_file = root / 'jncToken'
        self.downloaded_file = root / 'downloadedJncBooks.csv'
        self.owned_file = root / 'jncOwnedSeries.csv'

    def __enter__(self) -> 'ScriptSandbox':
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self._tmp.cleanup()

    def write_token(self, token: str) -> None:
        self.token_file.write_text(token, encoding='utf-8')

    def write_downloaded(self, content: str) -> None:
        self.downloaded_file.write_text(content, encoding='utf-8')

    def write_owned(self, content: str) -> None:
        self.owned_file.write_text(content, encoding='utf-8')

    def read_downloaded_rows(self) -> List[List[str]]:
        return _read_tsv(self.downloaded_file)

    def read_owned_rows(self) -> List[List[str]]:
        return _read_tsv(self.owned_file)

    def epub_path(self, title_slug: str) -> Path:
        return self.target_dir / f'{title_slug}.epub'


def _read_tsv(path: Path) -> List[List[str]]:
    with open(path, newline='', encoding='utf-8') as f:
        return [row for row in csv.reader(f, delimiter='\t') if row]


class ScriptRun:
    def __init__(self, stdout: str, namespace: Dict[str, Any], input_prompts: List[str],
                 exit_code: Optional[int] = None) -> None:
        self.stdout = stdout
        self.namespace = namespace
        self.input_prompts = input_prompts
        self.exit_code = exit_code


def _forbid_stdin(prompt: str = '') -> Any:
    raise AssertionError(f'unexpected interactive prompt: {prompt!r}')


def run_jnc_script(api: FakeJncApi, sandbox: ScriptSandbox, argv: List[str], *,
                   stdin_answers: Optional[List[str]] = None,
                   env_login: bool = True) -> ScriptRun:
    """Executes all of jnc.py against the fake API inside the sandbox.

    A sys.exit() from the script (the maintenance commands exit early) is
    captured and reported as ScriptRun.exit_code; it is None otherwise.
    """
    env = {
        'JNC_TOKEN_FILE': str(sandbox.token_file),
        'JNC_DOWNLOADED_BOOKS_FILE': str(sandbox.downloaded_file),
        'JNC_OWNED_SERIES_FILE': str(sandbox.owned_file),
        'JNC_DOWNLOAD_TARGET_DIR': str(sandbox.target_dir),
        'JNC_LOGIN_EMAIL': 'tester@example.com' if env_login else '',
        'JNC_LOGIN_PW': 'secret' if env_login else '',
    }
    input_prompts: List[str] = []
    if stdin_answers is None:
        input_patch = mock.patch('builtins.input', side_effect=_forbid_stdin)
        getpass_patch = mock.patch('jnc_ui.getpass', side_effect=_forbid_stdin)
    else:
        def scripted_input(prompt: str = '') -> str:
            input_prompts.append(prompt)
            return stdin_answers[len(input_prompts) - 1]

        input_patch = mock.patch('builtins.input', side_effect=scripted_input)
        getpass_patch = mock.patch('jnc_ui.getpass', return_value='secret')
    namespace: Dict[str, Any] = {'__name__': 'jnc_script_under_test'}
    out = io.StringIO()
    exit_code: Optional[int] = None
    old_argv = sys.argv
    sys.argv = ['jnc.py'] + list(argv)
    try:
        with mock.patch.dict(os.environ, env), \
                mock.patch('jnc_api_tools.requests.get', side_effect=api.get), \
                mock.patch('jnc_api_tools.requests.post', side_effect=api.post), \
                input_patch, getpass_patch, \
                contextlib.redirect_stdout(out):
            exec(JNC_CODE, namespace)
    except SystemExit as exit_request:
        exit_code = exit_request.code
    finally:
        sys.argv = old_argv
    return ScriptRun(stdout=out.getvalue(), namespace=namespace, input_prompts=input_prompts,
                     exit_code=exit_code)


def today_utc() -> str:
    return datetime.now(tz=timezone.utc).date().isoformat()


class JncScriptTests(unittest.TestCase):
    def test_downloads_new_books_and_writes_all_state_files(self) -> None:
        with ScriptSandbox() as sandbox:
            sandbox.write_token('valid-token')
            sandbox.write_owned('my-series\tTrue\n')
            api = FakeJncApi(
                library_items=[owned_item(VOL_ONE), owned_item(VOL_FUTURE, status='PREORDER')],
                series_aggregates={'my-series': api_series_aggregate('my-series', [VOL_ONE])},
                downloads={ONE_EPUB: b'one-epub'},
            )
            run = run_jnc_script(api, sandbox, argv=[], env_login=False)

            self.assertIn('You have 42 coins.', run.stdout)
            self.assertIn('You can buy coins at a 15% discount.', run.stdout)
            self.assertIn('Fetching your library...', run.stdout)
            self.assertIn('Fetching series info (1/1): my-series', run.stdout)
            self.assertIn('There are 0 new volumes available:', run.stdout)
            self.assertIn('Downloading (1/1): Book One', run.stdout)
            self.assertIn('Downloaded 1 of 1 books.', run.stdout)
            self.assertIn('Current preorders (Release Date / Title):', run.stdout)
            self.assertIn('Future Book', run.stdout)
            self.assertEqual(b'one-epub', sandbox.epub_path('book-one').read_bytes())
            rows = sandbox.read_downloaded_rows()
            self.assertEqual(1, len(rows))
            self.assertEqual(['B1', 'Book One'], rows[0][:2])
            self.assertTrue(rows[0][2].startswith(today_utc()))
            self.assertEqual([['my-series', 'True']], sandbox.read_owned_rows())
            self.assertEqual('valid-token', sandbox.token_file.read_text(encoding='utf-8'))
            self.assertEqual([], api.orders)
            self.assertEqual([], api.coin_purchases)

    def test_second_run_skips_already_downloaded_books(self) -> None:
        with ScriptSandbox() as sandbox:
            sandbox.write_token('valid-token')
            sandbox.write_owned('my-series\tTrue\n')
            api = FakeJncApi(
                library_items=[owned_item(VOL_ONE)],
                series_aggregates={'my-series': api_series_aggregate('my-series', [VOL_ONE])},
                downloads={ONE_EPUB: b'one-epub'},
            )
            run_jnc_script(api, sandbox, argv=[], env_login=False)
            api2 = FakeJncApi(
                library_items=[owned_item(VOL_ONE)],
                series_aggregates={'my-series': api_series_aggregate('my-series', [VOL_ONE])},
                downloads={ONE_EPUB: b'one-epub'},
            )
            run2 = run_jnc_script(api2, sandbox, argv=[], env_login=False)
            self.assertEqual([], api2.downloaded_urls)
            self.assertNotIn('Downloading', run2.stdout)

    def test_legacy_csv_dates_are_upgraded_to_purchase_dates(self) -> None:
        with ScriptSandbox() as sandbox:
            sandbox.write_token('valid-token')
            sandbox.write_owned('my-series\tTrue\n')
            sandbox.write_downloaded('B1\tBook One\n')
            api = FakeJncApi(
                library_items=[owned_item(VOL_ONE)],
                series_aggregates={'my-series': api_series_aggregate('my-series', [VOL_ONE])},
                downloads={ONE_EPUB: b'one-epub'},
            )
            run = run_jnc_script(api, sandbox, argv=[], env_login=False)
            rows = sandbox.read_downloaded_rows()
            self.assertEqual(['B1', 'Book One', '2020-02-01T00:00:00+00:00'], rows[0])
            self.assertEqual([], api.downloaded_urls)
            self.assertNotIn('Downloading', run.stdout)
            self.assertFalse(sandbox.epub_path('book-one').exists())

    def test_new_series_can_be_followed_and_new_volumes_are_listed(self) -> None:
        with ScriptSandbox() as sandbox:
            sandbox.write_token('valid-token')
            api = FakeJncApi(
                library_items=[owned_item(VOL_ONE)],
                series_aggregates={'my-series': api_series_aggregate('my-series', [VOL_ONE, VOL_TWO])},
                prices={'book-two': 800},
                downloads={ONE_EPUB: b'one-epub'},
            )
            run = run_jnc_script(api, sandbox, argv=[], stdin_answers=['y'], env_login=False)

            self.assertEqual(['my-series is a new series. Do you want to follow it? (y/n)'],
                             run.input_prompts)
            self.assertIn('Fetching series info (1/1): my-series', run.stdout)
            self.assertIn('Fetching book price (1/1): Book Two', run.stdout)
            self.assertIn('There are 1 new volumes available:', run.stdout)
            self.assertIn('(800 coins) Available:\tBook Two', run.stdout)
            self.assertEqual([['my-series', 'True']], sandbox.read_owned_rows())
            self.assertEqual([], api.orders)
            self.assertEqual([], api.coin_purchases)
            self.assertEqual([ONE_EPUB], api.downloaded_urls)

    def test_declined_new_series_is_recorded_as_not_followed(self) -> None:
        with ScriptSandbox() as sandbox:
            sandbox.write_token('valid-token')
            api = FakeJncApi(
                library_items=[owned_item(VOL_ONE)],
                series_aggregates={'my-series': api_series_aggregate('my-series', [VOL_ONE, VOL_TWO])},
                prices={'book-two': 800},
                downloads={ONE_EPUB: b'one-epub'},
            )
            run = run_jnc_script(api, sandbox, argv=[], stdin_answers=['n'], env_login=False)

            self.assertEqual([['my-series', 'False']], sandbox.read_owned_rows())
            self.assertIn('There are 0 new volumes available:', run.stdout)
            self.assertFalse(any('/series/' in url for _, url in api.calls))
            self.assertEqual([ONE_EPUB], api.downloaded_urls)

    def test_env_credentials_log_in_without_a_prompt(self) -> None:
        with ScriptSandbox() as sandbox:
            api = FakeJncApi(library_items=[])
            run = run_jnc_script(api, sandbox, argv=[], env_login=True)
            self.assertEqual([], run.input_prompts)
            self.assertIn('You have 42 coins.', run.stdout)
            self.assertEqual('tok-1', sandbox.token_file.read_text(encoding='utf-8'))

    def test_interactive_login_retries_after_a_failed_attempt(self) -> None:
        with ScriptSandbox() as sandbox:
            api = FakeJncApi(
                user_json=api_user_json(coins=42),
                library_items=[],
                login_responses=[{'error': 'bad credentials'}, {'id': 'tok-2'}],
            )
            run = run_jnc_script(api, sandbox, argv=[],
                                 stdin_answers=['tester@example.com', 'tester@example.com'],
                                 env_login=False)
            self.assertEqual(['Enter login email: ', 'Enter login email: '], run.input_prompts)
            self.assertIn('Login failed!', run.stdout)
            self.assertIn('You have 42 coins.', run.stdout)
            self.assertIn('There are 0 new volumes available:', run.stdout)
            self.assertEqual('tok-2', sandbox.token_file.read_text(encoding='utf-8'))

    def test_order_flow_buys_coins_orders_and_downloads(self) -> None:
        with ScriptSandbox() as sandbox:
            sandbox.write_token('valid-token')
            sandbox.write_owned('my-series\tTrue\n')
            sandbox.write_downloaded('B1\tBook One\t2020-01-01T00:00:00+00:00\n')
            api = FakeJncApi(
                user_json=api_user_json(coins=100),
                library_items=[owned_item(VOL_ONE)],
                series_aggregates={'my-series': api_series_aggregate('my-series', [VOL_ONE, VOL_TWO])},
                prices={'book-two': 800},
                owned_volume_items={'v2': owned_item(VOL_TWO)},
                coin_options={
                    'coinPriceInCents': 100,
                    'purchaseMinimumCoins': 500,
                    'purchaseMaximumCoins': 1000,
                    'packs': [{'coins': 500, 'currentCentsCost': 250, 'originalCentsCost': 500}],
                },
                downloads={ONE_EPUB: b'one-epub', TWO_EPUB: b'two-epub'},
            )
            run = run_jnc_script(api, sandbox, argv=['--order', '--coins', '--no-confirm-all'],
                                 env_login=False)

            self.assertEqual([700], api.coin_purchases)
            self.assertEqual(['v2'], api.orders)
            self.assertEqual(0, run.namespace['user_data'].coins)
            self.assertIn('There are 1 new volumes available:', run.stdout)
            self.assertIn('Buying 700 coins', run.stdout)
            self.assertIn('Purchased 700 coins', run.stdout)
            self.assertIn('You have 800 coins', run.stdout)
            self.assertIn('Ordered: Book Two', run.stdout)
            self.assertIn('Downloading (1/1): Book Two', run.stdout)
            self.assertNotIn('Downloading (1/1): Book One', run.stdout)
            self.assertEqual([TWO_EPUB], api.downloaded_urls)
            self.assertEqual(b'two-epub', sandbox.epub_path('book-two').read_bytes())
            rows = sandbox.read_downloaded_rows()
            self.assertEqual(2, len(rows))
            self.assertEqual(['B1', 'Book One', '2020-01-01T00:00:00+00:00'], rows[0])
            self.assertEqual(['B2', 'Book Two'], rows[1][:2])
            self.assertTrue(rows[1][2].startswith(today_utc()))

    def test_completed_series_is_unfollowed(self) -> None:
        with ScriptSandbox() as sandbox:
            sandbox.write_token('valid-token')
            sandbox.write_owned('my-series\tTrue\n')
            sandbox.write_downloaded('B1\tBook One\t2020-01-01T00:00:00+00:00\n')
            api = FakeJncApi(
                library_items=[owned_item(VOL_ONE)],
                series_aggregates={'my-series': api_series_aggregate(
                    'my-series', [VOL_ONE], tags=['fully translated', 'comedy'])},
            )
            run = run_jnc_script(api, sandbox, argv=[], env_login=False)

            self.assertIn('my-series is fully owned and translated. Series will be unfollowed.', run.stdout)
            self.assertEqual([['my-series', 'False']], sandbox.read_owned_rows())
            self.assertEqual([], api.downloaded_urls)

    def test_update_books_redownloads_books_jNC_updated(self) -> None:
        with ScriptSandbox() as sandbox:
            sandbox.write_token('valid-token')
            sandbox.write_owned('my-series\tTrue\n')
            sandbox.write_downloaded('B1\tBook One\t2020-01-01T00:00:00+00:00\n')
            api = FakeJncApi(
                library_items=[owned_item(VOL_ONE)],
                series_aggregates={'my-series': api_series_aggregate('my-series', [VOL_ONE])},
                downloads={ONE_EPUB: b'one-epub-v2'},
            )
            run_default = run_jnc_script(api, sandbox, argv=[], env_login=False)
            self.assertEqual([], api.downloaded_urls)
            self.assertNotIn('Downloading', run_default.stdout)

            api_update = FakeJncApi(
                library_items=[owned_item(VOL_ONE)],
                series_aggregates={'my-series': api_series_aggregate('my-series', [VOL_ONE])},
                downloads={ONE_EPUB: b'one-epub-v2'},
            )
            run_update = run_jnc_script(api_update, sandbox, argv=['--update-books'], env_login=False)
            self.assertEqual([ONE_EPUB], api_update.downloaded_urls)
            self.assertIn('Downloading (1/1): Book One', run_update.stdout)
            self.assertIn('Downloaded 1 of 1 books.', run_update.stdout)
            self.assertEqual(b'one-epub-v2', sandbox.epub_path('book-one').read_bytes())
            rows = sandbox.read_downloaded_rows()
            self.assertTrue(rows[0][2].startswith(today_utc()))

    def test_unfollow_series_updates_state_and_exits_without_touching_the_api(self) -> None:
        with ScriptSandbox() as sandbox:
            sandbox.write_token('valid-token')
            sandbox.write_owned('my-series\tTrue\nother-series\tTrue\n')
            api = FakeJncApi()
            run = run_jnc_script(api, sandbox, argv=['--unfollow', 'my-series'], env_login=False)

            self.assertEqual(0, run.exit_code)
            self.assertIn('Unfollowed my-series. It will no longer be checked for new volumes.',
                          run.stdout)
            self.assertEqual([['my-series', 'False'], ['other-series', 'True']],
                             sandbox.read_owned_rows())
            self.assertEqual('valid-token', sandbox.token_file.read_text(encoding='utf-8'))
            self.assertEqual([], api.calls)
            self.assertFalse(sandbox.epub_path('book-one').exists())

    def test_unfollow_series_without_a_match_leaves_the_state_unchanged(self) -> None:
        with ScriptSandbox() as sandbox:
            sandbox.write_token('valid-token')
            sandbox.write_owned('my-series\tTrue\n')
            api = FakeJncApi()
            run = run_jnc_script(api, sandbox, argv=['--unfollow', 'unknown-series'], env_login=False)

            self.assertEqual(0, run.exit_code)
            self.assertIn('No series matching "unknown-series" found.', run.stdout)
            self.assertEqual([['my-series', 'True']], sandbox.read_owned_rows())
            self.assertEqual([], api.calls)

    def test_unfollow_series_with_several_matches_asks_for_a_choice(self) -> None:
        with ScriptSandbox() as sandbox:
            sandbox.write_token('valid-token')
            sandbox.write_owned('magic-1\tTrue\nmagic-2\tTrue\nother-series\tTrue\n')
            api = FakeJncApi()
            run = run_jnc_script(api, sandbox, argv=['--unfollow', 'MAGIC'],
                                 stdin_answers=['2'], env_login=False)

            self.assertEqual(0, run.exit_code)
            self.assertIn('2 series match "MAGIC":', run.stdout)
            self.assertIn('(1) magic-1', run.stdout)
            self.assertIn('(2) magic-2', run.stdout)
            self.assertEqual(['Which series do you want to unfollow? (1-2, 0 to cancel)'],
                             run.input_prompts)
            self.assertIn('Unfollowed magic-2. It will no longer be checked for new volumes.',
                          run.stdout)
            self.assertEqual([['magic-1', 'True'], ['magic-2', 'False'],
                              ['other-series', 'True']], sandbox.read_owned_rows())
            self.assertEqual([], api.calls)

    def test_unfollow_series_choice_can_be_cancelled(self) -> None:
        with ScriptSandbox() as sandbox:
            sandbox.write_token('valid-token')
            sandbox.write_owned('magic-1\tTrue\nmagic-2\tTrue\n')
            api = FakeJncApi()
            run = run_jnc_script(api, sandbox, argv=['--unfollow', 'magic'],
                                 stdin_answers=['0'], env_login=False)

            self.assertEqual(0, run.exit_code)
            self.assertIn('Unfollow cancelled.', run.stdout)
            self.assertEqual([['magic-1', 'True'], ['magic-2', 'True']],
                             sandbox.read_owned_rows())
            self.assertEqual([], api.calls)

    def test_unfollow_series_choice_asks_again_on_an_invalid_number(self) -> None:
        with ScriptSandbox() as sandbox:
            sandbox.write_token('valid-token')
            sandbox.write_owned('magic-1\tTrue\nmagic-2\tTrue\n')
            api = FakeJncApi()
            run = run_jnc_script(api, sandbox, argv=['--unfollow', 'magic'],
                                 stdin_answers=['9', '1'], env_login=False)

            self.assertEqual(0, run.exit_code)
            self.assertIn('Please enter a number between 1 and 2, or 0 to cancel.', run.stdout)
            self.assertIn('Unfollowed magic-1. It will no longer be checked for new volumes.',
                          run.stdout)
            self.assertEqual([['magic-1', 'False'], ['magic-2', 'True']],
                             sandbox.read_owned_rows())
            self.assertEqual([], api.calls)

    def test_delete_token_removes_the_token_file_and_exits_without_logging_in(self) -> None:
        with ScriptSandbox() as sandbox:
            sandbox.write_token('valid-token')
            sandbox.write_owned('my-series\tTrue\n')
            api = FakeJncApi()
            run = run_jnc_script(api, sandbox, argv=['--delete-token'], env_login=False)

            self.assertEqual(0, run.exit_code)
            self.assertIn('Deleted the stored API token:', run.stdout)
            self.assertFalse(sandbox.token_file.exists())
            self.assertEqual([['my-series', 'True']], sandbox.read_owned_rows())
            self.assertEqual([], api.calls)

    def test_delete_token_without_a_stored_token_reports_and_exits_cleanly(self) -> None:
        with ScriptSandbox() as sandbox:
            api = FakeJncApi()
            run = run_jnc_script(api, sandbox, argv=['--delete-token'], env_login=False)

            self.assertEqual(0, run.exit_code)
            self.assertIn('No stored API token found at', run.stdout)
            self.assertFalse(sandbox.token_file.exists())
            self.assertEqual([], api.calls)

    def test_unfollow_and_delete_token_can_be_combined(self) -> None:
        with ScriptSandbox() as sandbox:
            sandbox.write_token('valid-token')
            sandbox.write_owned('my-series\tTrue\n')
            api = FakeJncApi()
            run = run_jnc_script(api, sandbox, argv=['--unfollow', 'my-series', '--delete-token'],
                                 env_login=False)

            self.assertEqual(0, run.exit_code)
            self.assertEqual([['my-series', 'False']], sandbox.read_owned_rows())
            self.assertFalse(sandbox.token_file.exists())
            self.assertEqual([], api.calls)


if __name__ == '__main__':
    unittest.main()
