"""Hand-labelled review cases.

Each case is a before/after pair for one file. The diff is generated from them, so
line numbers never need to be typed by hand. "expect" lists the problems a
reviewer should report. Each entry names a substring of the AFTER file; the
scorer turns it into a line number and requires that line to be inside the diff.

"buggy" cases contain at least one real problem. "clean" cases contain none, so
every comment on them is a false positive. Several clean cases are safe versions
of buggy ones, to test whether the reviewer over-reports.
"""

CASES = [
    # ---- buggy -----------------------------------------------------------
    {
        "id": "bug-off-by-one",
        "kind": "buggy",
        "path": "app/pricing.py",
        "before": """
            def total_price(items):
                total = 0
                for i in range(len(items)):
                    total += items[i].price
                return total
        """,
        "after": """
            def total_price(items):
                total = 0
                for i in range(len(items) + 1):
                    total += items[i].price
                return total
        """,
        "expect": [{"contains": "range(len(items) + 1)", "category": "bug"}],
    },
    {
        "id": "sec-sql-injection",
        "kind": "buggy",
        "path": "app/users.py",
        "before": """
            def find_user(conn, name):
                cur = conn.cursor()
                return cur.execute("SELECT id, email FROM users WHERE name = %s", (name,)).fetchone()
        """,
        "after": """
            def find_user(conn, name):
                cur = conn.cursor()
                query = f"SELECT id, email FROM users WHERE name = '{name}'"
                return cur.execute(query).fetchone()
        """,
        "expect": [{"contains": "WHERE name = '{name}'", "category": "security"}],
    },
    {
        "id": "sec-path-traversal",
        "kind": "buggy",
        "path": "app/uploads.py",
        "before": """
            import os

            UPLOAD_DIR = '/srv/uploads'


            def read_upload(filename):
                return None
        """,
        "after": """
            import os

            UPLOAD_DIR = '/srv/uploads'


            def read_upload(filename):
                path = os.path.join(UPLOAD_DIR, filename)
                with open(path, 'rb') as fh:
                    return fh.read()
        """,
        "expect": [{"contains": "path = os.path.join(UPLOAD_DIR, filename)", "category": "security"}],
    },
    {
        "id": "bug-missing-await",
        "kind": "buggy",
        "path": "app/greet.py",
        "before": """
            async def get_user(uid):
                return await db.fetch_one(uid)


            async def greeting(uid):
                return 'hi'
        """,
        "after": """
            async def get_user(uid):
                return await db.fetch_one(uid)


            async def greeting(uid):
                user = get_user(uid)
                return f'hi {user.name}'
        """,
        "expect": [{"contains": "user = get_user(uid)", "category": "bug"}],
    },
    {
        "id": "err-swallowed-exception",
        "kind": "buggy",
        "path": "app/billing.py",
        "before": """
            def charge(gateway, order):
                gateway.charge(order.total, order.card)
                order.status = 'paid'
        """,
        "after": """
            def charge(gateway, order):
                try:
                    gateway.charge(order.total, order.card)
                except Exception:
                    pass
                order.status = 'paid'
        """,
        "expect": [{"contains": "except Exception:", "category": "error-handling"}],
    },
    {
        "id": "bug-mutable-default",
        "kind": "buggy",
        "path": "app/tags.py",
        "before": """
            def add_tag(tags, tag):
                tags.append(tag)
                return tags
        """,
        "after": """
            def add_tag(tag, tags=[]):
                tags.append(tag)
                return tags
        """,
        "expect": [{"contains": "def add_tag(tag, tags=[]):", "category": "bug"}],
    },
    {
        "id": "sec-timing-compare",
        "kind": "buggy",
        "path": "app/auth.py",
        "before": """
            def verify_token(token, expected):
                return False
        """,
        "after": """
            def verify_token(token, expected):
                return token == expected
        """,
        "expect": [{"contains": "return token == expected", "category": "security"}],
    },
    {
        "id": "sec-secret-logged",
        "kind": "buggy",
        "path": "app/client.py",
        "before": """
            import logging

            log = logging.getLogger(__name__)


            def connect(api_key):
                return Client(api_key)
        """,
        "after": """
            import logging

            log = logging.getLogger(__name__)


            def connect(api_key):
                log.info('connecting with key %s', api_key)
                return Client(api_key)
        """,
        "expect": [{"contains": "log.info('connecting with key %s', api_key)", "category": "security"}],
    },
    {
        "id": "bug-none-deref",
        "kind": "buggy",
        "path": "app/cache.py",
        "before": """
            def display_name(cache, key):
                return cache.get(key)
        """,
        "after": """
            def display_name(cache, key):
                value = cache.get(key)
                return value.upper()
        """,
        "expect": [{"contains": "return value.upper()", "category": "bug"}],
    },
    {
        "id": "bug-divide-by-zero",
        "kind": "buggy",
        "path": "app/stats.py",
        "before": """
            def average(total, count):
                return total
        """,
        "after": """
            def average(total, count):
                return total / count
        """,
        "expect": [{"contains": "return total / count", "category": "bug"}],
    },
    {
        "id": "sec-missing-authz",
        "kind": "buggy",
        "path": "app/projects.py",
        "before": """
            def delete_project(user, project):
                if project.owner_id != user.id:
                    abort(403)
                db.delete(project)
        """,
        "after": """
            def delete_project(user, project):
                db.delete(project)
        """,
        "expect": [{"contains": "db.delete(project)", "category": "security"}],
    },
    {
        "id": "sec-ssrf",
        "kind": "buggy",
        "path": "app/preview.py",
        "before": """
            import requests


            def preview(request):
                return None
        """,
        "after": """
            import requests


            def preview(request):
                resp = requests.get(request.args['url'], timeout=5)
                return resp.text
        """,
        "expect": [{"contains": "requests.get(request.args['url']", "category": "security"}],
    },
    {
        "id": "sec-pickle-untrusted",
        "kind": "buggy",
        "path": "app/jobs.py",
        "before": """
            import json


            def load_job(body):
                return json.loads(body)
        """,
        "after": """
            import pickle


            def load_job(body):
                return pickle.loads(body)
        """,
        "expect": [{"contains": "pickle.loads(body)", "category": "security"}],
    },
    {
        "id": "bug-infinite-retry",
        "kind": "buggy",
        "path": "app/retry.py",
        "before": """
            def fetch_with_retry(call):
                return call()
        """,
        "after": """
            def fetch_with_retry(call):
                while True:
                    try:
                        return call()
                    except Exception:
                        continue
        """,
        "expect": [{"contains": "continue", "category": "bug"}],
    },
    {
        "id": "sec-hardcoded-password",
        "kind": "buggy",
        "path": "app/config.py",
        "before": """
            import os


            def db_url():
                return os.environ['DATABASE_URL']
        """,
        "after": """
            import os


            DB_PASSWORD = 'hunter2-prod'


            def db_url():
                return f'postgresql://app:{DB_PASSWORD}@db/app'
        """,
        "expect": [{"contains": "DB_PASSWORD = 'hunter2-prod'", "category": "security"}],
    },
    {
        "id": "bug-always-true-condition",
        "kind": "buggy",
        "path": "app/orders.py",
        "before": """
            def is_paid(order):
                return order.status == 'paid'
        """,
        "after": """
            def is_paid(order):
                return order.status == 'paid' or 'refunded'
        """,
        "expect": [{"contains": "or 'refunded'", "category": "bug"}],
    },

    # ---- clean (any comment is a false positive) -------------------------
    {
        "id": "clean-rename-variable",
        "kind": "clean",
        "path": "app/geometry.py",
        "before": """
            def area(r):
                x = 3.14159 * r * r
                return x
        """,
        "after": """
            def area(radius):
                circle_area = 3.14159 * radius * radius
                return circle_area
        """,
        "expect": [],
    },
    {
        "id": "clean-add-docstring",
        "kind": "clean",
        "path": "app/text.py",
        "before": """
            def slugify(text):
                return text.lower().replace(' ', '-')
        """,
        "after": """
            def slugify(text):
                \"\"\"Lowercase text and join words with hyphens.\"\"\"
                return text.lower().replace(' ', '-')
        """,
        "expect": [],
    },
    {
        "id": "clean-comprehension-to-loop",
        "kind": "clean",
        "path": "app/math_utils.py",
        "before": """
            def squares(xs):
                return [x * x for x in xs]
        """,
        "after": """
            def squares(xs):
                out = []
                for x in xs:
                    out.append(x * x)
                return out
        """,
        "expect": [],
    },
    {
        "id": "clean-new-unit-test",
        "kind": "clean",
        "path": "tests/test_money.py",
        "before": "",
        "after": """
            import unittest

            from money import add


            class AddTest(unittest.TestCase):
                def test_adds_cents(self):
                    self.assertEqual(add(1, 2), 3)
        """,
        "expect": [],
    },
    {
        "id": "clean-dependency-bump",
        "kind": "clean",
        "path": "requirements.txt",
        "before": """
            requests==2.31.0
        """,
        "after": """
            requests==2.32.3
        """,
        "expect": [],
    },
    {
        "id": "clean-parameterized-query",
        "kind": "clean",
        "path": "app/users.py",
        "before": """
            def find_user(conn, name):
                cur = conn.cursor()
                return cur.execute('SELECT 1', ()).fetchone()
        """,
        "after": """
            def find_user(conn, name):
                cur = conn.cursor()
                return cur.execute('SELECT id, email FROM users WHERE name = %s', (name,)).fetchone()
        """,
        "expect": [],
    },
    {
        "id": "clean-realpath-check",
        "kind": "clean",
        "path": "app/uploads.py",
        "before": """
            import os

            UPLOAD_DIR = '/srv/uploads'


            def read_upload(filename):
                return None
        """,
        "after": """
            import os

            UPLOAD_DIR = os.path.realpath('/srv/uploads')


            def read_upload(filename):
                path = os.path.realpath(os.path.join(UPLOAD_DIR, filename))
                if not path.startswith(UPLOAD_DIR + os.sep):
                    raise ValueError('bad filename')
                with open(path, 'rb') as fh:
                    return fh.read()
        """,
        "expect": [],
    },
    {
        "id": "clean-log-length-not-secret",
        "kind": "clean",
        "path": "app/client.py",
        "before": """
            import logging

            log = logging.getLogger(__name__)


            def connect(api_key):
                return Client(api_key)
        """,
        "after": """
            import logging

            log = logging.getLogger(__name__)


            def connect(api_key):
                log.info('connecting client, key length %d', len(api_key))
                return Client(api_key)
        """,
        "expect": [],
    },
    {
        "id": "clean-extract-constant",
        "kind": "clean",
        "path": "app/net.py",
        "before": """
            def fetch(call):
                for _ in range(3):
                    try:
                        return call()
                    except OSError:
                        pass
                raise RuntimeError('gave up')
        """,
        "after": """
            MAX_RETRIES = 3


            def fetch(call):
                for _ in range(MAX_RETRIES):
                    try:
                        return call()
                    except OSError:
                        pass
                raise RuntimeError('gave up')
        """,
        "expect": [],
    },
    {
        "id": "clean-constant-time-compare",
        "kind": "clean",
        "path": "app/auth.py",
        "before": """
            def verify_token(token, expected):
                return False
        """,
        "after": """
            import hmac


            def verify_token(token, expected):
                return hmac.compare_digest(token, expected)
        """,
        "expect": [],
    },
    {
        "id": "clean-readme-config-section",
        "kind": "clean",
        "path": "README.md",
        "before": """
            # Service

            Run it with make run.
        """,
        "after": """
            # Service

            Run it with `make run`.

            ## Config

            Set `PORT` to change the listen port (default 8080).
        """,
        "expect": [],
    },
    {
        "id": "clean-add-type-hints",
        "kind": "clean",
        "path": "app/scale.py",
        "before": """
            def scale(values, factor):
                return [v * factor for v in values]
        """,
        "after": """
            from typing import Iterable


            def scale(values: Iterable[float], factor: float) -> list[float]:
                return [v * factor for v in values]
        """,
        "expect": [],
    },
]
