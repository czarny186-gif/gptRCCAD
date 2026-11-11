"""Kontrola historii na całym zestawie testów: każdy zapisany krok z przepisem (każda funkcja programu, która trafia do
historii) jest od razu wykonywany ponownie z przepisu na stanie sprzed kroku i porównywany z tym, co program zapisał.
Uruchomienie: python tests/history_audit.py  (wynik: history_audit.log, kod 1 przy rozbieżnościach)."""
import json
import os
import sys
import time
import traceback
import unittest
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('RCCAD_WORKERS', '0')

from rccad import history as hist          # noqa: E402
from rccad import kernel                   # noqa: E402
from rccad.document import Body, Document  # noqa: E402

LOG = Path(os.environ.get('RCCAD_AUDIT_LOG', 'history_audit.log'))
seen, timing = Counter(), defaultdict(float)


class _Problems(defaultdict):
    def note(self, kind, item):
        self[kind].append(item)
        print(f'AUDIT [{kind}] {item[0]}: {item[1]}', file=sys.__stderr__, flush=True)


problems = _Problems(list)
_commit = Document.commit
_current = {'test': ''}


def _signature(body):
    shape = body.shape
    try:
        box = kernel.bounds(shape)
        bb = (box.xmin, box.ymin, box.zmin, box.xmax, box.ymax, box.zmax)
    except Exception:
        bb = None
    try:
        volume = shape.Volume() if body.kind == 'solid' else None
    except Exception:
        volume = None
    return body.kind, bool(body.visible), bb, volume


def _close(a, b, tol):
    if a is None or b is None:
        return a is b
    return all(abs(x - y) <= tol * max(1.0, abs(x), abs(y)) for x, y in zip(a, b))


def _compare(expected, got):
    """Różnice między stanem zapisanym przez program a odtworzonym z przepisu (lista opisów)."""
    out = []
    em, gm = {b.id: b for b in expected}, {b.id: b for b in got}
    if set(em) != set(gm):
        out.append(f'inne obiekty: brakuje {sorted(set(em) - set(gm))[:3]}, nadmiarowe {sorted(set(gm) - set(em))[:3]}')
        return out
    for i, e in em.items():
        g = gm[i]
        if e.shape is g.shape:
            continue
        ek, ev, ebb, evol = _signature(e)
        gk, gv, gbb, gvol = _signature(g)
        if ek != gk or ev != gv:
            out.append(f'{e.name}: rodzaj / widoczność {ek},{ev} != {gk},{gv}')
        elif not _close(ebb, gbb, 2e-3):
            out.append(f'{e.name}: wymiary {ebb} != {gbb}')
        elif evol is not None and gvol is not None and abs(evol - gvol) > 2e-3 * max(1.0, abs(evol)):
            out.append(f'{e.name}: objętość {evol:.3f} != {gvol:.3f}')
        if e.folder != g.folder or e.group != g.group or e.color != g.color or e.name != g.name:
            out.append(f'{e.name}: nazwa / grupa / kolor inne ({e.name},{e.folder},{e.group},{e.color} != {g.name},{g.folder},{g.group},{g.color})')
    return out


def audited_commit(self, bodies, label=None, icon=None, op=None):
    recipe = op or self.pending_op
    before = self.bodies
    result = _commit(self, bodies, label, icon, op)
    if not recipe or self.merging and recipe.get('type') != 'sketchmeta':
        return result
    kind = recipe.get('type')
    seen[kind] += 1
    start = time.perf_counter()
    try:
        hist.reads(recipe, before)
    except Exception as exc:
        problems.note(kind, (_current['test'], f'reads() błąd: {exc!r}'))
    try:
        with kernel.deferred_mesh():
            again = hist.run_recipe(before, recipe)
        diff = _compare(self.bodies, again)
        if diff:
            problems.note(kind, (_current['test'], '; '.join(diff[:3])))
    except Exception as exc:
        problems.note(kind, (_current['test'], f'nie da się odtworzyć: {exc!r}'[:400]))
    try:      # przeliczenie historii po zmianie czegoś niezwiązanego wcześniej: krok ma dać ten sam wynik (bez błędu)
        with kernel.deferred_mesh():
            far = Body('Kontrola', kernel.box(1, 1, 1).translate((5e4, 5e4, 5e4)))
            out, failed = hist.rebuild((*before, far), [(before, self.bodies, dict(self.info))])
        if failed:
            problems.note(kind, (_current['test'], 'po niezwiązanej zmianie wcześniej: ' + out[-1][1].get('why', '?')[:300]))
        else:
            diff = _compare((*self.bodies, far), out[-1][0])
            if diff:
                problems.note(kind, (_current['test'], 'po niezwiązanej zmianie wcześniej: ' + '; '.join(diff[:3])))
    except Exception as exc:
        problems.note(kind, (_current['test'], f'przeliczenie historii: {exc!r}'[:400]))
    timing[kind] += time.perf_counter() - start
    return result


class _Result(unittest.TextTestResult):
    def startTest(self, test):
        _current['test'] = test.id()
        super().startTest(test)


def main():
    Document.commit = audited_commit
    suite = unittest.defaultTestLoader.discover(sys.argv[1] if len(sys.argv) > 1 else 'tests')
    result = unittest.TextTestRunner(verbosity=1, resultclass=_Result).run(suite)
    lines = ['Kontrola historii - kroki z przepisem sprawdzone ponownym wykonaniem', '']
    for kind in sorted(set(seen) | set(hist.RUNNERS)):
        bad = problems.get(kind, [])
        lines.append(f'{kind:14s} sprawdzono {seen.get(kind, 0):5d}  rozbieżności {len(bad):4d}  czas {timing.get(kind, 0):7.1f} s')
    lines.append('')
    for kind, items in sorted(problems.items()):
        for test, text in items[:12]:
            lines.append(f'[{kind}] {test}: {text}')
    lines.append('')
    lines.append(f'testy: {result.testsRun}, błędy: {len(result.errors)}, niepowodzenia: {len(result.failures)}')
    LOG.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))
    return 0 if result.wasSuccessful() and not problems else 1


if __name__ == '__main__':
    sys.exit(main())
