"""Compare GL surface-buffer allocations and framebuffer readback with OpenGL 3.3+."""
import json
import statistics
import time
from dataclasses import replace
import numpy as np
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from rccad import kernel
from rccad.document import Body
from rccad.viewport import CadView

app = QApplication([])
shape = kernel.cylinder(7, 13)
prototype = kernel.display_mesh(shape, tolerance=.001, angular=.006)
for number in (24, 100):
    bodies = []
    for i in range(number):
        xyz = (20 * (i % 10), 20 * (i // 10), 0)
        transform = np.eye(4)
        transform[:3, 3] = xyz
        bodies.append(Body(str(i), shape.translate(xyz), group='test', mesh=kernel.placed_mesh(prototype, transform)))
    view = CadView()
    view.resize(1280, 820)
    view.show()
    for phase in ('combined', 'instanced'):
        models = bodies if phase == 'instanced' else [
            replace(body, mesh=replace(body.mesh, render_prototype=None, render_transform=None)) for body in bodies
        ]
        view.set_models(models)
        view.fit_all()
        QTest.qWait(250)
        fill = view._solid_batches['test'][1]
        if phase == 'instanced':
            assert fill._instance_key and not fill._instancing_failed
        times = []
        for _ in range(7):
            start = time.perf_counter()
            frame = view.grabFramebuffer()
            assert not frame.isNull()
            times.append((time.perf_counter() - start) * 1000)
        buffers = [fill.m_vbo_position, fill.m_vbo_normal, fill.m_ibo_faces]
        if phase == 'instanced':
            buffers.append(fill._matrices)
        size = 0
        view.makeCurrent()
        for buffer in buffers:
            assert buffer.bind()
            size += buffer.size()
            buffer.release()
        print(json.dumps({'components': number, 'phase': phase,
                          'surface_buffer_bytes': size, 'frame_readback_ms': round(statistics.median(times), 2)}), flush=True)
    view.close()
