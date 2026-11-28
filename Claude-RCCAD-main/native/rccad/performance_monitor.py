"""Opt-in sampling for the Studio viewport and worker queue."""
from collections import deque
import ctypes
import json
import os
from pathlib import Path
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QFileDialog, QPlainTextEdit, QPushButton, QVBoxLayout

from .perfcache import array_bytes


def resident_bytes():
    if os.name == 'nt':
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    'peak_working_set', 'working_set', 'peak_paged_pool', 'paged_pool',
                    'peak_non_paged_pool', 'non_paged_pool', 'pagefile', 'peak_pagefile',
                )
            ]

        kernel = ctypes.WinDLL('kernel32')
        psapi = ctypes.WinDLL('psapi')
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        read = psapi.GetProcessMemoryInfo
        read.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        read.restype = wintypes.BOOL
        counters = Counters()
        counters.size = ctypes.sizeof(counters)
        if read(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.size):
            return counters.working_set
    elif Path('/proc/self/statm').is_file():
        return int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    return None


class FrameSamples:
    def __init__(self):
        self.frames = deque(maxlen=240)

    def record(self, start, end):
        self.frames.append((end, end - start))

    def report(self, now):
        if not self.frames:
            return {'fps_1s': 0, 'fps_mean': None, 'frame_cpu_ms': None}
        first, last = self.frames[0][0], self.frames[-1][0]
        return {
            'fps_1s': sum(0 <= now - end <= 1 for end, _ in self.frames),
            'fps_mean': round((len(self.frames) - 1) / (last - first), 1) if last > first else None,
            'frame_cpu_ms': round(self.frames[-1][1] * 1000, 2),
        }


class PerformanceMonitor(QDialog):
    def __init__(self, studio):
        super().__init__(studio)
        self.studio = studio
        self.setWindowTitle('Wydajność — RCCAD')
        self.resize(500, 425)
        layout = QVBoxLayout(self)
        layout.addLayout(studio._adaptive_detail.settings_form(self))
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        layout.addWidget(self.text)
        save = QPushButton('Zapisz raport JSON…', self)
        save.clicked.connect(self.save)
        layout.addWidget(save)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_report)
        self.samples = FrameSamples()
        self._geometry_time = None
        self._mesh_time = None

    def showEvent(self, event):
        super().showEvent(event)
        self.samples.frames.clear()
        self._cpu_sample = (time.monotonic(), time.process_time())
        self.studio.view.frame_samples = self.samples
        self.update_report()
        self.timer.start()

    def hideEvent(self, event):
        self.timer.stop()
        self.studio.view.frame_samples = None
        super().hideEvent(event)

    def report(self):
        from .viewport import _PICK

        view = self.studio.view
        bodies = [body for body in view.bodies if body.visible and body.mesh is not None]
        meshes = [body.mesh for body in bodies]
        now, cpu = time.monotonic(), time.process_time()
        last, last_cpu = self._cpu_sample
        self._cpu_sample = now, cpu
        return {
            **self.samples.report(now),
            'visible_bodies': sum(body.kind == 'solid' for body in bodies),
            'visible_triangles': sum(len(view._render_mesh(body).triangles) for body in bodies),
            'adaptive_lod_targets': self.studio._adaptive_detail.levels,
            'coarse_meshes': sum(not mesh.fine for mesh in meshes),
            'visible_mesh_bytes': array_bytes(meshes),
            'picking_cache_bytes': _PICK.bytes + view._projection_cache.bytes,
            'adaptive_lod_cache_bytes': self.studio._adaptive_detail.cache.bytes,
            'document_mesh_cache_bytes': self.studio.document._mesh_cache.bytes,
            'process_rss_bytes': resident_bytes(),
            'process_cpu_percent': round(100 * (cpu - last_cpu) / (now - last), 1) if now - last >= .1 else None,
            'jobs': self.studio.jobs.report(),
            'foreground_jobs': int(self.studio.busy),
            'preview_jobs': sum(state['running'] for state in self.studio._pv.values()),
            'refinement_jobs': int(bool(self.studio._refining)),
            'last_geometry_ms': self._geometry_time,
            'last_refinement_batch_ms': self._mesh_time,
        }

    def update_report(self):
        self.text.setPlainText(json.dumps(self.report(), indent=2, ensure_ascii=False))

    def save(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Zapisz raport wydajności', 'rccad-wydajnosc.json', 'JSON (*.json)')
        if path:
            try:
                Path(path).write_text(self.text.toPlainText() + '\n', encoding='utf-8')
            except OSError as exc:
                self.studio.toast(str(exc), 5000)
