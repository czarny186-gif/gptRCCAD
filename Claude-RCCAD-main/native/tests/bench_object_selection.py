"""Measure Objects panel updates without a GPU or event-loop painting."""
import json
import os
from statistics import median
from time import perf_counter

from PySide6.QtWidgets import QApplication

from rccad.objects import ObjectsPanel


def main():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication([])
    for count in (10, 100, 1000, 10000):
        panel = ObjectsPanel(None)
        folded = count == 10000
        items = [
            (str(i), 'solid', i + 1, f'Bryła {i}', '', f'Folder {i // 100}' if folded else '')
            for i in range(count)
        ]
        panel.update_items(items, [], set(), set())
        samples = []
        for i in range(7):
            start = perf_counter()
            panel.update_items(items, [str(i)], set(), set())
            samples.append((perf_counter() - start) * 1000)
        print(json.dumps(dict(objects=count, folded=folded, median_ms=round(median(samples), 3))), flush=True)
        panel.deleteLater()
        app.processEvents()


if __name__ == '__main__':
    main()
