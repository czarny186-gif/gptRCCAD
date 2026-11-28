"""Run with an OpenGL 3.3+ display to compare instanced and compatibility frames."""
import numpy as np
from OpenGL import GL
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from rccad import kernel
from rccad.document import Body
from rccad.viewport import CadView, SharedSolidMesh

app = QApplication([])
view = CadView()
view.resize(1280, 820)
shape = kernel.cylinder(7, 13)
mesh = kernel.display_mesh(shape, tolerance=.001, angular=.006)
assert len(mesh.triangles) >= 512, len(mesh.triangles)
bodies = []
for i in range(24):
    xyz = (20 * (i % 6), 20 * (i // 6), 0)
    matrix = np.eye(4)
    matrix[:3, 3] = xyz
    bodies.append(Body(str(i), shape.translate(xyz), group='batch', mesh=kernel.placed_mesh(mesh, matrix)))
view.set_models(bodies)
fill = view._solid_batches['batch'][1]
assert isinstance(fill, SharedSolidMesh)
view.fit_all()
view.show()
QTest.qWait(500)
frame = view.grabFramebuffer()
view.makeCurrent()
print('GL', GL.glGetString(GL.GL_VERSION), GL.glGetString(GL.GL_RENDERER), 'triangles', len(mesh.triangles))
assert not frame.isNull()
assert fill._instance_key, 'Modern instancing path was not reached'
assert not fill._instancing_failed, 'Instanced draw failed'
assert fill._matrices.bind()
assert fill._matrices.size() == len(fill._instance_key) * 64
fill._matrices.release()
assert GL.glGetError() == GL.GL_NO_ERROR
print('Instanced rendering:', len(fill._instance_key), 'visible instances')
# Verify that the fallback renders the same image using the same prototype.
fill._instancing_failed = True
fallback = view.grabFramebuffer()
assert frame.size() == fallback.size()
a = np.frombuffer(frame.bits(), dtype=np.uint8).astype(int)
b = np.frombuffer(fallback.bits(), dtype=np.uint8).astype(int)
assert np.mean(np.abs(a-b)) < .1, (np.mean(np.abs(a-b)), np.max(np.abs(a-b)))
print('Fallback pixel agreement:', np.mean(np.abs(a-b)))
view.close()
