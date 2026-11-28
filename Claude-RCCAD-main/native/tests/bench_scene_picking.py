"""Measure initial scene preparation and indexed picking for rigid assemblies."""
import json
import time
import numpy as np
from PySide6.QtWidgets import QApplication
from rccad import kernel
from rccad.document import Body
from rccad.viewport import CadView

app = QApplication([])
shape = kernel.box(1, 1, 1)
mesh = kernel.display_mesh(shape)
for count in (10, 100, 1000, 10000):
    t = time.perf_counter()
    bodies = []
    for index in range(count):
        xyz = (2 * (index % 100), 2 * (index // 100), 0)
        matrix = np.eye(4)
        matrix[:3, 3] = xyz
        bodies.append(Body(str(index), shape.translate(xyz), group='batch', mesh=kernel.placed_mesh(mesh, matrix)))
    prepare = time.perf_counter() - t
    view = CadView()
    t = time.perf_counter()
    view.set_models(bodies)
    view.fit_all()
    view._scene_index()
    setup = time.perf_counter() - t
    t = time.perf_counter()
    for i in range(100):
        body = bodies[i % count]
        center = np.asarray(body.mesh.center)
        origin = center + [0, 0, 100]
        hit = view._hit(origin, np.array([0., 0., -1.]))
        assert hit is not None and hit[1] == body.id
    pick = (time.perf_counter() - t) * 10
    print(json.dumps(dict(bodies=count, positioning_ms=round(1000*prepare, 1),
                          view_and_index_ms=round(1000*setup, 1), mean_pick_ms=round(pick, 3))), flush=True)
    view.close()
    view.deleteLater()
    app.processEvents()
