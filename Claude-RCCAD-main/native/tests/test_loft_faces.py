"""Bryły z wyciągnięcia złożonego (duży i mały prostokąt w różnych wysokościach): pochylone ściany muszą działać w szkicu, wycinaniu i Boolean."""
import unittest
import numpy as np
import cadquery as cq
from rccad import kernel as k
from rccad import history as hist
from rccad.document import Body


def rect(w, h, z, cx=0.0, cy=0.0):
    return cq.Wire.makePolygon([cq.Vector(cx - w / 2, cy - h / 2, z), cq.Vector(cx + w / 2, cy - h / 2, z),
                                cq.Vector(cx + w / 2, cy + h / 2, z), cq.Vector(cx - w / 2, cy + h / 2, z)], close=True)


CASES = {
    'środkowy': ([rect(40, 30, 0), rect(20, 10, 30)], False),
    'przesunięty': ([rect(40, 30, 0), rect(18, 8, 25, 6, -4)], False),
    'ruled': ([rect(40, 30, 0), rect(20, 10, 30)], True),
    'daleko': ([rect(60, 40, 0), rect(10, 6, 80)], False),
}


def clicks(solid, face, count=6):
    """Punkty i normalne, jakie dałoby kliknięcie w siatkę ściany (środki trójkątów rozłożone po całej ścianie)."""
    mesh = k.display_mesh(face)
    tri = np.asarray(mesh.vertices, float)[np.asarray(mesh.triangles)]
    centers = tri.mean(axis=1)
    idx = np.linspace(0, len(tri) - 1, min(count, len(tri))).astype(int)
    out = []
    for i in idx:
        n = np.cross(tri[i][1] - tri[i][0], tri[i][2] - tri[i][0])
        out.append((tuple(n / np.linalg.norm(n)), tuple(centers[i])))
    return out


class LoftFaceTests(unittest.TestCase):
    def test_every_side_face_can_be_picked_sketched_cut_and_combined(self):
        problems = []
        for name, (wires, ruled) in CASES.items():
            solid = k.loft_wires(wires, None, ruled)
            vol0 = float(solid.Volume())
            for fi, face in enumerate(solid.Faces()):
                tag = f'{name}/ściana{fi}({face.geomType()})'
                if not k.is_planar_face(face):
                    problems.append(tag + ': nie uznana za płaską')
                    continue
                # 1. wskazanie ściany w wielu miejscach
                for normal, point in clicks(solid, face):
                    try:
                        got, n = k.face_at(solid, normal, point, curved=True)
                        if not got.isSame(face):
                            problems.append(tag + ': wskazana inna ściana')
                            break
                    except k.CadError as exc:
                        problems.append(tag + f': face_at {exc}')
                        break
                # 2. szkic na ścianie i wycięcie w głąb
                try:
                    got, n = k.face_at(solid, *clicks(solid, face, 1)[0], curved=True)
                    n = np.asarray(n, float)
                    center = np.array(face.Center().toTuple())
                    frame = k.face_frame(tuple(center), n)
                    wire = k.sketch('rectangle', frame, 4, 4, 0, 0)
                    cut_face = hist.profile_face(wire)
                    tool = k.extrude_face(cut_face, -n, 2.0)
                    body = Body('b', solid, 'solid').prepared()
                    out = hist.combine([body], [tool], 'cut', set(), [], 'Wytnij')
                    vol = float(out[0].shape.Volume()) if out and out[0].kind == 'solid' else -1
                    if abs((vol0 - vol) - 32.0) > 0.5:
                        problems.append(tag + f': wycięcie usunęło {vol0 - vol:.2f} zamiast 32')
                    # 3. kolejny szkic na ścianie bryły po wycięciu
                    again = out[0].shape
                    faces = [f for f in again.Faces() if k.is_planar_face(f) and abs(float(np.dot(f.normalAt().toTuple(), n))) > .999 and f.Area() > 20]
                    if not faces:
                        problems.append(tag + ': po wycięciu nie widać ściany')
                except Exception as exc:
                    problems.append(tag + f': szkic/wycięcie {type(exc).__name__} {exc}')
                # 4. wyciągnięcie samej ściany (dodanie materiału)
                try:
                    added = k.extrude_face(face, np.asarray(k.face_at(solid, *clicks(solid, face, 1)[0], curved=True)[1], float), 3.0)
                    joined = k.boolean('union', solid, [added])
                    if float(joined.Volume()) <= vol0 + 1.0:
                        problems.append(tag + ': wyciągnięcie ściany nie dodało objętości')
                except Exception as exc:
                    problems.append(tag + f': wyciągnięcie ściany {type(exc).__name__} {exc}')
            # 5. Boolean z bryłami przecinającymi pochylone ściany
            bb = k.bounds(solid)
            for label, tool_shape in (('pudło', cq.Solid.makeBox(25, 25, 25, cq.Vector(bb.xmax - 10, bb.ymin + 2, bb.zmin + 4))),
                                      ('walec', cq.Solid.makeCylinder(6, 40, cq.Vector((bb.xmin + bb.xmax) / 2 + 8, (bb.ymin + bb.ymax) / 2, bb.zmin - 5)))):
                try:
                    cut = k.boolean('subtract', solid, [tool_shape])
                    common = k.boolean('intersect', solid, [tool_shape])
                    union = k.boolean('union', solid, [tool_shape])
                    if abs(float(cut.Volume()) + float(common.Volume()) - vol0) > 0.01 * vol0:
                        problems.append(f'{name}/{label}: objętości boolean nie sumują się')
                    if float(union.Volume()) < vol0 - 0.5:
                        problems.append(f'{name}/{label}: suma mniejsza od bryły')
                except k.CadError as exc:
                    problems.append(f'{name}/{label}: boolean {exc}')
        self.assertFalse(problems, '\n'.join(problems))


def variant(w, h, z, start=0, reverse=False, cx=0.0, cy=0.0):
    pts = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
    pts = pts[start:] + pts[:start]
    if reverse:
        pts = pts[::-1]
    return cq.Wire.makePolygon([cq.Vector(x, y, z) for x, y in pts], close=True)


class LoftAlignTests(unittest.TestCase):
    def test_profiles_drawn_from_other_corner_or_direction_give_planar_sides(self):
        problems = []
        base = rect(40, 30, 0)
        for start in range(4):
            for reverse in (False, True):
                for ruled in (False, True):
                    top = variant(20, 10, 30, start, reverse, 3, -2)
                    solid = k.loft_wires([base, top], None, ruled)
                    bad = [f for f in solid.Faces() if not k.is_planar_face(f)]
                    expected = (40 * 30 + 20 * 10 + 0) * 0  # tylko sprawdzenie ścian
                    if bad or len(solid.Faces()) != 6 or float(solid.Volume()) < 0.3 * 30 * 20 * 10 * 4:
                        problems.append(f'start={start} reverse={reverse} ruled={ruled}: nieplaskich={len(bad)} scian={len(solid.Faces())} V={solid.Volume():.0f}')
        self.assertFalse(problems, '\n'.join(problems))


if __name__ == '__main__':
    unittest.main()
