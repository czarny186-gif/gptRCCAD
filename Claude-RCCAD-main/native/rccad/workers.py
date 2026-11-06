"""Procesy liczące: kilka osobnych procesów Pythona (mniej więcej jeden na rdzeń), które liczą naprawdę równolegle.

Wątki w tle utrzymują płynność okna, ale Python wykonuje w danej chwili kod tylko jednego wątku, więc ciężkie liczenie
z kilku wątków i tak idzie po kolei. Procesy omijają to ograniczenie: każdy ma własnego Pythona i własne OpenCascade.

Pula startuje w tle po otwarciu okna (start()), a każdy proces raz wczytuje bibliotekę geometrii. Dopóki pula nie jest
gotowa - albo gdy jej zabraknie (błąd, wyłączona zmienną RCCAD_WORKERS=0) - wszystko liczy się jak dotąd, w bieżącym
procesie. Kształty przechodzą między procesami jako binarny zapis OpenCascade (pickle z cadquery), wyniki jako tablice numpy.

W procesach liczą się:
- siatki do wyświetlania razem ze sprawdzeniem poprawności brył (mesh_many): otwieranie projektu, cofanie / ponawianie,
  przeskoki w historii i stan wynikowy po przeliczeniu historii,
- przycinanie kołnierzy blachy w narożnikach (run_affine): kołnierze jednego poziomu równolegle.

Każdy proces ma własną kolejkę (osobny wykonawca z jednym procesem). Zadanie z kluczem trafia zawsze do tego samego procesu,
więc proces pamięta swoje wcześniejsze wyniki (np. cięcia narożników danego kołnierza) - dodanie kolejnego kołnierza
nie liczy wszystkiego od nowa.
"""
from __future__ import annotations

import atexit
import os
import threading

MIN_PARALLEL = 2         # mniej kształtów nie opłaca się wysyłać do procesów (przesyłanie trwa dłużej niż zysk)

_pools = []          # wykonawcy z jednym procesem każdy (stałe przypisanie zadań do procesu)
_turn = 0
_ready = False
_starting = False
_lock = threading.Lock()


def count():
    """Liczba procesów: RCCAD_WORKERS (0 = wyłączone), domyślnie tyle, ile rdzeni (najwyżej 8; okno czeka na wynik, więc
    nie zabiera im rdzenia). Na komputerze z jednym rdzeniem procesy nie mają sensu."""
    value = os.environ.get('RCCAD_WORKERS')
    if value is not None:
        try:
            return max(0, min(int(value), 32))
        except ValueError:
            return 0
    cores = os.cpu_count() or 1
    return 0 if cores < 2 else min(cores, 8)


def _init():
    """Start procesu liczącego: wczytuje bibliotekę geometrii i liczy siatki na jednym rdzeniu (równoległość daje sama pula)."""
    from . import kernel
    kernel.PARALLEL_MESH = False


def _ping():
    return os.getpid()


def _mesh_job(shape, tolerance, solid, coarse=False):
    """W procesie liczącym: sprawdzenie bryły i siatka do wyświetlania. Zwraca (siatka, None) albo (None, komunikat błędu)."""
    import cadquery as cq
    from . import kernel
    try:
        shape = cq.Shape.cast(shape.wrapped)
        if not coarse:
            # kształt przyszedł z siatką z okna (np. zgrubną), a po przesłaniu nie wiadomo, jak była dokładna - to kopia tylko
            # tego procesu, więc siatkę można bezpiecznie usunąć i policzyć dokładną od nowa
            from OCP.BRepTools import BRepTools
            BRepTools.Clean_s(shape.wrapped)
        kernel.valid(shape, solid)
        return kernel.display_mesh(shape, tolerance, coarse=coarse and kernel.heavy(shape)), None
    except kernel.CadError as exc:
        return None, str(exc)


def start(wait=False):
    """Uruchamia procesy w tle (raz na cały program). wait=True czeka, aż będą gotowe (testy, autotest)."""
    global _starting
    with _lock:
        if _pools or _starting or count() == 0:
            begin = None
        else:
            _starting = True
            begin = threading.Thread(target=_create, name='rccad-workers', daemon=True)
    if begin is not None:
        begin.start()
        if wait:
            begin.join()
    elif wait:
        while _starting:
            threading.Event().wait(.05)
    return ready()


def _create():
    global _pools, _ready, _starting
    try:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        context = multiprocessing.get_context('spawn')
        pools = [ProcessPoolExecutor(max_workers=1, mp_context=context, initializer=_init) for _ in range(count())]
        pids = {f.result(timeout=180) for f in [p.submit(_ping) for p in pools]}       # każdy proces wczytał bibliotekę
        with _lock:
            _pools, _ready = pools, len(pids) == len(pools) > 0
    except Exception:
        with _lock:
            _pools, _ready = [], False
    finally:
        _starting = False


def ready():
    return _ready and bool(_pools)


def size():
    return len(_pools) if ready() else 0


def shutdown():
    global _pools, _ready
    with _lock:
        pools, _pools, _ready = _pools, [], False
    for pool in pools:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


atexit.register(shutdown)


def _broken():
    """Procesy przestały działać (np. zamknięte przez system): dalej liczy bieżący proces."""
    shutdown()


def _next_pool():
    global _turn
    with _lock:
        pools = _pools
        _turn += 1
        return pools[_turn % len(pools)] if pools else None


def _pool_for(key):
    import zlib
    pools = _pools
    return pools[zlib.crc32(repr(key).encode()) % len(pools)] if pools else None


def run_affine(jobs):
    """jobs: [(klucz, funkcja, argumenty)] -> lista wyników albo None (procesy niegotowe / awaria: licz w bieżącym procesie).
    Zadanie o danym kluczu trafia zawsze do tego samego procesu. Błąd geometrii (CadError) z procesu jest zgłaszany dalej."""
    if not ready():
        return None
    from . import kernel
    try:
        futures = [_pool_for(key).submit(function, *args) for key, function, args in jobs]
    except Exception:
        _broken()
        return None
    results = []
    for future in futures:
        try:
            results.append(future.result())
        except kernel.CadError:
            raise
        except Exception:
            from concurrent.futures.process import BrokenProcessPool
            if isinstance(future.exception(), BrokenProcessPool):
                _broken()
            return None             # nieoczekiwany kłopot w procesie: ta sama praca liczy się jeszcze raz tutaj
    return results


def fine_meshes(shapes):
    """Dokładne siatki dla kształtów, które mają zgrubne: w procesach (osobne kopie, więc wspólny kształt w oknie się nie
    zmienia), a bez procesów - na kopii kształtu w bieżącym wątku."""
    shapes = list(shapes)
    if shapes and ready():
        try:
            futures = [_next_pool().submit(_mesh_job, shape, .12, False, False) for shape in shapes]
            return [f.result()[0] for f in futures]
        except Exception:
            _broken()
    import cadquery as cq
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
    from . import kernel
    out = []
    for shape in shapes:
        try:
            out.append(kernel.display_mesh(cq.Shape.cast(BRepBuilderAPI_Copy(shape.wrapped, True, False).Shape())))
        except Exception:
            out.append(None)
    return out


def mesh_many(items, tolerance=.12, coarse=False):
    """items: [(kształt, czy_bryła)] -> [(siatka, None) | (None, komunikat)] w tej samej kolejności.
    Przy co najmniej MIN_PARALLEL kształtach i gotowych procesach liczą procesy (po kolei rozdzielane), inaczej - bieżący proces.
    coarse=True: duże bryły dostają zgrubną siatkę (dokładną dolicza potem okno w tle)."""
    items = list(items)
    if len(items) >= MIN_PARALLEL and ready():
        try:
            futures = [_next_pool().submit(_mesh_job, shape, tolerance, solid, coarse) for shape, solid in items]
            return [f.result() for f in futures]
        except Exception:
            _broken()
    from . import kernel
    out = []
    for shape, solid in items:
        try:
            kernel.valid(shape, solid)
            out.append((kernel.display_mesh(shape, tolerance, coarse=coarse and kernel.heavy(shape)), None))
        except kernel.CadError as exc:
            out.append((None, str(exc)))
    return out
