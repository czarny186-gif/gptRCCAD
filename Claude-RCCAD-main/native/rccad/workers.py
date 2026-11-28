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
from collections import deque
import os
import threading

MIN_PARALLEL = 2         # mniej kształtów nie opłaca się wysyłać do procesów (przesyłanie trwa dłużej niż zysk)
TIMEOUT = 240            # s - proces, który tak długo nie odpowiada, uznaje się za zawieszony: liczy okno, procesy są wyłączane

_pools = []          # wykonawcy z jednym procesem każdy (stałe przypisanie zadań do procesu)
_mesh_pool = None    # osobny proces na dokładne siatki w tle - nie blokuje kolejek operacji
_turn = 0
_ready = False
_starting = False
_lock = threading.Lock()


def count():
    """Liczba procesów: RCCAD_WORKERS (0 = wyłączone), domyślnie połowa rdzeni (od 2 do 6). Na komputerze z jednym rdzeniem procesy nie mają sensu."""
    value = os.environ.get('RCCAD_WORKERS')
    if value is not None:
        try:
            return max(0, min(int(value), 32))
        except ValueError:
            return 0
    cores = os.cpu_count() or 1
    return 0 if cores < 2 else max(2, min(cores // 2, 6))      # połowa rdzeni: reszta zostaje dla okna i systemu (mniej ciepła)


IN_WORKER = False          # True w procesie liczącym


def _init():
    """Start procesu liczącego: wczytuje bibliotekę geometrii. Wątki OpenCascade zostają (pojedyncza operacja na blasze
    w procesie liczy tak samo szybko jak w oknie)."""
    global IN_WORKER
    IN_WORKER = True
    from . import kernel  # noqa: F401


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
        mesh_pool = ProcessPoolExecutor(max_workers=1, mp_context=context, initializer=_init)
        pids = {f.result(timeout=180) for f in [p.submit(_ping) for p in (*pools, mesh_pool)]}     # każdy proces wczytał bibliotekę
        with _lock:
            global _mesh_pool
            _pools, _mesh_pool, _ready = pools, mesh_pool, len(pids) == len(pools) + 1 > 1
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
    global _mesh_pool
    with _lock:
        pools, _pools, _ready = [*_pools, *([_mesh_pool] if _mesh_pool is not None else [])], [], False
        _mesh_pool = None
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
    """Stały proces dla klucza. Rozwinięcia blachy (('layout', id)) idą do procesu obok procesu jej budowy (('sheet', id)),
    żeby przygotowywanie rozwinięcia w tle nie opóźniało dodawania kolejnych kołnierzy."""
    import zlib
    pools = _pools
    if not pools:
        return None
    if isinstance(key, tuple) and key and key[0] == 'layout':
        return pools[(zlib.crc32(repr(('sheet', *key[1:])).encode()) + 1) % len(pools)]
    return pools[zlib.crc32(repr(key).encode()) % len(pools)]


class Unavailable(Exception):
    """Procesy niegotowe albo zadanie nie dało się wykonać w procesie - policz w bieżącym procesie."""


class Aborted(Exception):
    """Liczenie przerwane przyciskiem „Anuluj liczenie” - wyniku nie ma i nie liczy się go od nowa w oknie."""


_abort_gen = 0           # rośnie przy każdym przerwaniu: zadania wysłane wcześniej kończą się wyjątkiem Aborted


def abort():
    """Przerwanie wszystkiego, co liczy się w procesach: procesy są zamykane siłą (także zawieszone na jednej operacji),
    oczekujące zadania kończą się wyjątkiem Aborted, a nowe procesy startują w tle."""
    global _pools, _ready, _mesh_pool, _abort_gen
    with _lock:
        _abort_gen += 1
        pools = [*_pools, *([_mesh_pool] if _mesh_pool is not None else [])]
        _pools, _ready, _mesh_pool = [], False, None
    for pool in pools:
        for proc in list((getattr(pool, '_processes', None) or {}).values()):
            try:
                proc.kill()
            except Exception:
                pass
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
    _prepared.clear()
    if count() > 0:
        start()
    return bool(pools)


def _failed(exc, gen):
    """Wyjątek z procesu: przerwane przyciskiem -> Aborted; zawieszony / zamknięty proces -> wyłączenie procesów; zawsze
    bez wyniku z procesu."""
    from concurrent.futures import TimeoutError as Timeout
    from concurrent.futures.process import BrokenProcessPool
    from concurrent.futures import CancelledError
    if gen != _abort_gen:
        return Aborted()
    if isinstance(exc, (BrokenProcessPool, Timeout)):
        _broken()              # zawieszony albo zamknięty proces: dalej liczy okno (nic nie czeka bez końca)
    if isinstance(exc, CancelledError) and gen != _abort_gen:
        return Aborted()
    return Unavailable()


class Hung(Exception):
    """Zadanie przekroczyło swój limit czasu (np. OpenCascade zapętlił się w algorytmie zaokrąglenia): procesy zostały
    zamknięte i startują od nowa - tego zadania NIE liczy się ponownie w oknie (zawiesiłoby wątek bez końca)."""


class Crashed(Hung):
    """Proces liczący zakończył się awarią na tym zadaniu - liczenie go w oknie mogłoby zamknąć cały program."""


def call_guarded(key, function, *args, timeout=60.0):
    """Jak call_affine (key=None - dowolny proces), z własnym limitem czasu. Po przekroczeniu - zamknięcie procesów
    (także zawieszonego) i wyjątek Hung."""
    if not ready():
        raise Unavailable()
    from . import kernel
    from concurrent.futures import TimeoutError as Timeout
    gen = _abort_gen
    pool = _pool_for(key) if key is not None else _next_pool()
    try:
        return pool.submit(function, *args).result(timeout=float(timeout))
    except kernel.CadError:
        raise
    except Timeout as exc:
        if gen != _abort_gen:
            raise Aborted() from exc
        abort()                                    # zabija zawieszony proces (i pozostałe), nowe startują w tle
        raise Hung() from exc
    except Exception as exc:
        from concurrent.futures.process import BrokenProcessPool
        if isinstance(exc, BrokenProcessPool) and gen == _abort_gen:
            abort()                                # proces padł na tym zadaniu (błąd OpenCascade) - nie liczyć go w oknie
            raise Crashed() from exc
        raise _failed(exc, gen) from exc


def call_affine(key, function, *args):
    """Jedno zadanie w procesie przypisanym do klucza (np. ta sama blacha zawsze w tym samym procesie, który pamięta
    jej wcześniejsze wyniki). Wątek okna czeka bez blokady Pythona, więc okno się nie zacina.
    Błąd geometrii (CadError) idzie dalej; inny kłopot -> Unavailable (licz tutaj)."""
    if not ready():
        raise Unavailable()
    from . import kernel
    gen = _abort_gen
    try:
        future = _pool_for(key).submit(function, *args)
        return future.result(timeout=TIMEOUT)
    except kernel.CadError:
        raise
    except Exception as exc:
        raise _failed(exc, gen) from exc


_prepared = {}          # znacznik -> Future przygotowania w tle (np. rozwinięcie blachy w procesie rozwinięć)


def prepare(tag, key, function, *args):
    """Przygotowanie w tle w procesie klucza, zapamiętane pod znacznikiem (prepared(tag) mówi, czy już gotowe)."""
    future = submit_affine(key, function, *args)
    if future is not None:
        if len(_prepared) > 200:
            _prepared.clear()
        _prepared[tag] = future
    return future is not None


def prepared(tag):
    future = _prepared.get(tag)
    return future is not None and future.done() and not future.cancelled() and future.exception() is None


def pending():
    """Czy któreś przygotowanie w tle jeszcze trwa."""
    try:
        return any(not f.done() for f in list(_prepared.values()))
    except Exception:
        return False


def call_any(function, *args):
    """Jedno zadanie w dowolnym procesie (po kolei rozdzielane). Okno czeka bez blokady Pythona. Jak call_affine."""
    if not ready():
        raise Unavailable()
    from . import kernel
    gen = _abort_gen
    try:
        return _next_pool().submit(function, *args).result(timeout=TIMEOUT)
    except kernel.CadError:
        raise
    except Exception as exc:
        raise _failed(exc, gen) from exc


def submit_affine(key, function, *args):
    """Zadanie w tle w procesie przypisanym do klucza, bez czekania na wynik (np. przygotowanie rozwinięcia). Future albo None."""
    if not ready():
        return None
    try:
        return _pool_for(key).submit(function, *args)
    except Exception:
        return None


def run_affine(jobs):
    """jobs: [(klucz, funkcja, argumenty)] -> lista wyników albo None (procesy niegotowe / awaria: licz w bieżącym procesie).
    Zadanie o danym kluczu trafia zawsze do tego samego procesu. Błąd geometrii (CadError) z procesu jest zgłaszany dalej."""
    if not ready():
        return None
    from . import kernel
    gen = _abort_gen
    try:
        futures = [_pool_for(key).submit(function, *args) for key, function, args in jobs]
    except Exception:
        _broken()
        return None
    results = []
    for future in futures:
        try:
            results.append(future.result(timeout=TIMEOUT))
        except kernel.CadError:
            raise
        except Exception as exc:
            error = _failed(exc, gen)
            if isinstance(error, Aborted):
                raise error from exc       # przerwane przyciskiem: bez liczenia od nowa w oknie
            return None             # nieoczekiwany kłopot w procesie: ta sama praca liczy się jeszcze raz tutaj
    return results


def fine_meshes(shapes):
    """Dokładne siatki dla kształtów, które mają zgrubne: w procesach (osobne kopie, więc wspólny kształt w oknie się nie
    zmienia), a bez procesów - na kopii kształtu w bieżącym wątku."""
    shapes = list(shapes)
    if shapes and ready() and _mesh_pool is not None:
        out = []
        for shape in shapes:
            try:
                out.append(_mesh_pool.submit(_mesh_job, shape, .12, False, False).result(timeout=TIMEOUT)[0])
            except Exception:
                out.append(None)
        return out
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
    slots = size()
    if len(items) < MIN_PARALLEL or not slots:
        return [_mesh_local(shape, solid, tolerance, False) for shape, solid in items]

    generation = _abort_gen
    queued = deque()
    pending = iter(items)

    def submit(item):
        if generation != _abort_gen:
            raise Aborted()
        shape, solid = item
        pool = _next_pool()
        try:
            future = pool.submit(_mesh_job, shape, tolerance, solid, coarse) if pool else None
        except Exception:
            future = None
        queued.append((item, future))

    results = []
    try:
        for _ in range(min(len(items), 2 * slots)):
            submit(next(pending))
        while queued:
            if generation != _abort_gen:
                raise Aborted()
            (shape, solid), future = queued.popleft()
            result = None
            if future is not None:
                try:
                    result = future.result(timeout=TIMEOUT)
                except Exception:
                    if generation != _abort_gen:
                        raise Aborted()
            if generation != _abort_gen:
                raise Aborted()
            following = next(pending, None)
            if following is not None:
                submit(following)
            if result is None:
                result = _mesh_local(shape, solid, tolerance, False)
            results.append(result)
        if generation != _abort_gen:
            raise Aborted()
        return results
    finally:
        for _, future in queued:
            if future is not None:
                future.cancel()


def _mesh_local(shape, solid, tolerance, coarse):
    from . import kernel
    try:
        kernel.valid(shape, solid)
        return kernel.display_mesh(shape, tolerance, coarse=coarse and kernel.heavy(shape)), None
    except kernel.CadError as exc:
        return None, str(exc)
