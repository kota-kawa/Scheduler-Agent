import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


try:
    import sqlmodel  # noqa: F401
except ModuleNotFoundError:
    stub = types.ModuleType("sqlmodel")
    stub.__stub__ = True

    class _Meta:
        def create_all(self, bind=None):
            return None

    class SQLModel:
        metadata = _Meta()

        def __init_subclass__(cls, **kwargs):
            return None

    class Session:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self, *args, **kwargs):
            return _ExecResult([])

        def add(self, *args, **kwargs):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

        def flush(self):
            return None

    class _Select:
        def where(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

    class _ExecResult:
        def __init__(self, items):
            self._items = items

        def all(self):
            return list(self._items)

        def first(self):
            return self._items[0] if self._items else None

    def Field(*args, **kwargs):
        return None

    def Relationship(*args, **kwargs):
        return None

    def create_engine(*args, **kwargs):
        return object()

    def select(*args, **kwargs):
        return _Select()

    stub.SQLModel = SQLModel
    stub.Session = Session
    stub.Field = Field
    stub.Relationship = Relationship
    stub.create_engine = create_engine
    stub.select = select

    pool_stub = types.ModuleType("sqlmodel.pool")
    pool_stub.StaticPool = object
    sys.modules["sqlmodel.pool"] = pool_stub

    sys.modules["sqlmodel"] = stub
