from contextlib import contextmanager, closing
import os
from uuid import uuid4
import psycopg2
from psycopg2.extras import Json


@contextmanager
def cursor():
    with (
        closing(psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=5)) as db,
        db,
        db.cursor() as cur,
    ):
        yield cur


def init():
    with cursor() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS checks(id uuid PRIMARY KEY, submission jsonb NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now());
                    CREATE TABLE IF NOT EXISTS revisions(check_id uuid REFERENCES checks(id), version integer NOT NULL,
                    saved_at timestamptz NOT NULL DEFAULT now(), attached jsonb NOT NULL, result jsonb NOT NULL,
                    PRIMARY KEY(check_id,version))""")


def create(submission, result):
    key = str(uuid4())
    with cursor() as c:
        c.execute(
            "INSERT INTO checks(id,submission) VALUES(%s,%s)", (key, Json(submission))
        )
        c.execute(
            "INSERT INTO revisions(check_id,version,attached,result) VALUES(%s,1,%s,%s)",
            (key, Json([]), Json(result)),
        )
    return key


def get(key):
    with cursor() as c:
        c.execute(
            "SELECT submission,version,saved_at,attached,result FROM checks JOIN revisions ON id=check_id WHERE id=%s ORDER BY version",
            (str(key),),
        )
        rows = c.fetchall()
    if not rows:
        raise KeyError(key)
    return dict(
        id=str(key),
        submission=rows[0][0],
        versions=[
            dict(version=v, saved_at=t.isoformat(), attached=a, result=r)
            for _, v, t, a, r in rows
        ],
    )


def recent():
    with cursor() as c:
        c.execute(
            "SELECT id::text,submission->>'brand',created_at FROM checks ORDER BY created_at DESC,id LIMIT 50"
        )
        return [
            dict(id=i, brand=b, created_at=t.isoformat()) for i, b, t in c.fetchall()
        ]


def append(key, expected, attached, result):
    with cursor() as c:
        c.execute("SELECT id FROM checks WHERE id=%s FOR UPDATE", (str(key),))
        if not c.fetchone():
            raise KeyError(key)
        c.execute("SELECT max(version) FROM revisions WHERE check_id=%s", (str(key),))
        version = c.fetchone()[0]
        if version != expected:
            raise ValueError("另一个窗口已生成新版本，请刷新后重试。")
        c.execute(
            "INSERT INTO revisions(check_id,version,attached,result) VALUES(%s,%s,%s,%s)",
            (str(key), version + 1, Json(attached), Json(result)),
        )
