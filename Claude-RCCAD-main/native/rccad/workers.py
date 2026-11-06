"""Procesy liczące: kilka osobnych procesów Pythona (mniej więcej jeden na rdzeń), które liczą naprawdę równolegle.

Wątki w tle utrzymują płynność okna, ale Python wykonuje w danej chwili kod tylko jednego wątku, więc ciężkie liczenie
z kilku wątków i tak idzie po kolei. Procesy omijają to ograniczenie: każdy ma własnego Pythona i własne OpenCascade.

Pula startuje w tle po otwarciu okna (start()), a każdy proces raz wczytuje bibliotekę geometrii. Dopóki pula nie jest
gotowa - albo gdy jej zabraknie (błąd, wyłączona zmienną RCCAD_WORKERS=0) - wszystko liczy się jak dotąd, w bieżącym
procesie. Kształty przechodzą między procesami jako binarny zapis OpenCascade (pickle z cadquery), wyniki jako tablice numpy.

Teraz w procesach liczą się siatki do wyświetlania razem ze sprawdzeniem poprawności brył (mesh_many): otwieranie projektu,
cofanie / ponawianie, przeskoki w historii i stan wynikowy po przeliczeniu historii.
"""
from __future__ import annotations

import atexit
import os
import threading

MIN_PARALLEL = 2         # mniej kształtów nie opłaca się wysyłać do procesów (przesyłanie trwa dłużej niż zysk)

_pool = None
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


def _mesh_job(shape, tolerance, solid):
    """W procesie liczącym: sprawdzenie bryły i siatka do wyświetlania. Zwraca (siatka, None) albo (None, komunikat błędu)."""
    import cadquery as cq
    from . import kernel
    try:
        shape = cq.Shape.cast(shape.wrapped)
        kernel.valid(shape, solid)
        return kernel.display_mesh(shape, tolerance), None
    except kernel.CadError as exc:
        return None, str(exc)


def start(wait=False):
    """Uruchamia pulę w tle (raz na cały program). wait=True czeka, aż procesy będą gotowe (testy, autotest)."""
    global _starting
    with _lock:
        if _pool is not None or _starting or count() == 0:
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
    global _pool, _ready, _starting
    try:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor
        n = count()
        pool = ProcessPoolExecutor(max_workers=n, mp_context=multiprocessing.get_context('spawn'), initializer=_init)
        pids = {f.result(timeout=180) for f in [pool.submit(_ping) for _ in range(n * 2)]}     # każdy proces wczytał bibliotekę
        with _lock:
            _pool, _ready = pool, bool(pids)
    except Exception:
        with _lock:
            _pool, _ready = None, False
    finally:
        _starting = False


def ready():
    return _ready and _pool is not None


def size():
    return count() if ready() else 0


def shutdown():
    global _pool, _ready
    with _lock:
        pool, _pool, _ready = _pool, None, False
    if pool is not None:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


atexit.register(shutdown)


def _broken():
    """Pula przestała działać (np. proces zamknięty przez system): dalej liczy bieżący proces."""
    shutdown()


def mesh_many(items, tolerance=.12):
    """items: [(kształt, czy_bryła)] -> [(siatka, None) | (None, komunikat)] w tej samej kolejności.
    Przy co najmniej MIN_PARALLEL kształtach i gotowej puli liczą procesy, inaczej (albo po awarii puli) - bieżący proces."""
    items = list(items)
    if len(items) >= MIN_PARALLEL and ready():
        try:
            futures = [_pool.submit(_mesh_job, shape, tolerance, solid) for shape, solid in items]
            return [f.result() for f in futures]
        except Exception:
            _broken()
    from . import kernel
    out = []
    for shape, solid in items:
        try:
            kernel.valid(shape, solid)
            out.append((kernel.display_mesh(shape, tolerance), None))
        except kernel.CadError as exc:
            out.append((None, str(exc)))
    return out
