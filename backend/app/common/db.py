from collections.abc import Iterator

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

_pool: ConnectionPool | None = None


def open_pool() -> None:
    global _pool
    _pool = ConnectionPool(settings.database_url, min_size=1, max_size=10,
                           kwargs={"row_factory": dict_row}, open=True)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def connection():
    """요청 밖(스케줄러 등)에서 연결을 빌릴 때 쓴다. 정상 종료면 커밋, 예외면 롤백."""
    assert _pool is not None, "DB 풀이 열려 있지 않습니다"
    return _pool.connection()


def get_db() -> Iterator[Connection]:
    """요청마다 연결 하나를 빌려준다. 정상 종료면 커밋, 예외면 롤백한다.

    실패 기록처럼 예외를 던지기 전에 남겨야 하는 변경은 서비스에서 먼저 conn.commit()을 호출한다.
    """
    assert _pool is not None, "DB 풀이 열려 있지 않습니다"
    with _pool.connection() as conn:
        yield conn
