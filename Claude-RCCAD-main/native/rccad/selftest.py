"""Executed by the packaged EXE as well as Python: validates shipped DLLs and I/O."""
from __future__ import annotations
import json
from pathlib import Path
import platform
import tempfile
from . import __version__, kernel as k
from .document import Body, Document


def run(report_path=None):
    checks = []
    shape = k.box(30, 30, 30)
    rounded = k.blend(shape, range(len(shape.Edges())), 3)
    assert rounded.isValid() and 0 < rounded.Volume() < shape.Volume()
    assert len(k.display_mesh(rounded).edges) == 0
    checks.append('OpenCascade: 12 edge fillets with smooth corner patches')
    drilled = k.hole(shape, 4, 15, 15)
    assert drilled.Volume() < shape.Volume() and drilled.isValid()
    checks.append('through hole')
    cut = k.boolean('subtract', shape, [k.box(10, 10, 40)])
    assert cut.isValid() and abs(cut.Volume()-24000) < 1e-5
    checks.append('Boolean subtraction')
    wire = k.sketch('rectangle','XY',20,10)
    assert abs(k.extrude(wire,'XY',10).Volume()-2000) < 1e-5
    checks.append('native sketch extrusion')
    from . import sheetmetal as shm
    slab = k.box(100, 50, 2)
    top = next(f for f in slab.Faces() if abs(f.Center().z-2) < 1e-6)
    sheet = shm.sheet_of_face(slab, top)
    flanges = [dict(kind='base', p0=[100,0,2], p1=[100,50,2], n=[0,0,1], m=[1,0,0], r=2, angle=45, length=20),
               dict(kind='tip', parent=0, side='out', r=2, angle=90, length=20),
               dict(kind='tip', parent=1, side='in', r=2, angle=60, length=20)]
    recipe = dict(base=sheet['base'], t=2, flanges=flanges, rules=dict(kfactor=.44))
    folded = shm.build_sheet(recipe)
    assert folded.isValid() and len(folded.Solids()) == 1
    checks.append('sheet metal: three bends, mixed angles and directions')
    with tempfile.TemporaryDirectory() as directory:
        import ezdxf
        path = Path(directory)/'laser.dxf'
        shm.export_flat_dxf(recipe, path, folded)
        dxf = ezdxf.readfile(path)
        cuts = list(dxf.modelspace().query('LWPOLYLINE[layer=="CUT"]'))
        assert dxf.units == 4 and len(cuts) == 1 and cuts[0].closed
        assert len(list(dxf.modelspace().query('LINE'))) == 3 and not dxf.audit().has_errors
    checks.append('sheet metal: millimetre flat DXF, closed cut contour and bend layers')
    edges = [([100,0,2],[100,50,2],[1,0,0]),([100,50,2],[0,50,2],[0,1,0]),
             ([0,50,2],[0,0,2],[-1,0,0]),([0,0,2],[100,0,2],[0,-1,0])]
    walls = [dict(kind='base',p0=a,p1=b,n=[0,0,1],m=m,r=2,angle=90,length=5) for a,b,m in edges]
    walls += [dict(kind='tip',parent=i,side='in',r=2,angle=90,length=5) for i in range(4)]
    walls += [dict(kind='tip',parent=i+4,side='out',r=2,angle=90,length=5) for i in range(4)]
    box = shm.build_sheet(dict(base=sheet['base'],t=2,flanges=walls,rules=dict(gap=.2)))
    assert box.isValid() and len(box.Solids()) == 1 and k.point_state(box,(92.7,41.3,17)) == 'in'
    checks.append('sheet metal box: four 5mm walls, inward returns and reversed third bends')
    mixed = walls[:4] + [dict(kind='tip',parent=i,side='out' if i==0 else 'in',r=2,angle=90,length=5) for i in range(4)]
    mixed_recipe = dict(base=sheet['base'],t=2,flanges=mixed,rules=dict(gap=.2,joint='diagonal'))
    mixed_shape = shm.build_sheet(mixed_recipe)
    frames,corners = shm._effective(mixed,2,True)
    parts = shm._corner_parts(mixed_recipe,frames,corners)
    axis = shm._unit(frames[1]['p1']-frames[1]['p0'])
    assert mixed_shape.isValid() and len(mixed_shape.Solids())==1
    assert any(f.geomType()=='PLANE' and abs(sum(a*b for a,b in zip(f.normalAt().toTuple(),axis)))>.99999
               and f.Area()>9.9 for f in parts[5][-1].Faces())
    checks.append('mixed sheet returns: three inward, one outward, straight non-intersecting ends')
    sheet_corner = shm.build_sheet(dict(base=sheet['base'],t=2,flanges=walls,rules=dict(gap=.2,joint='sheet')))
    assert sheet_corner.isValid() and len(sheet_corner.Solids())==1
    assert any(f.geomType()=='BSPLINE' for f in sheet_corner.Faces())
    assert any(f.geomType()=='CYLINDER' for f in sheet_corner.Faces())
    checks.append('sheet corner construction: square upright panels, circular bends and curved reliefs')
    drag = k.sketch_from_drag('rectangle','XZ',0,0,20,10)
    assert abs(k.extrude(k.sketch(**drag),'XZ',5).Volume()-1000) < 1e-5
    checks.append('mouse sketch geometry')
    plain = k.box(40,30,20)
    vertical = [i for i,e in enumerate(plain.Edges()) if abs(e.startPoint().z-e.endPoint().z) > 10]
    outline = k.blend(plain, vertical, 5)
    top = {i for i,e in enumerate(outline.Edges()) if abs(e.startPoint().z-20) < 1e-6 and abs(e.endPoint().z-20) < 1e-6}
    assert len(top) == 8 and k.edge_chain(outline, min(top)) == top
    checks.append('tangent edge chain')
    doc=Document();body=Body('Zaokrąglona kostka',rounded).prepared();doc.commit([body])
    doc.undo();assert not doc.bodies;doc.redo();assert len(doc.bodies)==1
    with tempfile.TemporaryDirectory(prefix='rccad-check-') as directory:
        root=Path(directory)
        doc.save(root/'test.rccadx')
        opened=Document.load(root/'test.rccadx')
        assert abs(opened.bodies[0].shape.Volume()-rounded.Volume()) < 1e-5
        k.export_shapes([rounded],root/'test.step')
        imported=k.import_shapes(root/'test.step')
        assert abs(imported[0][0].Volume()-rounded.Volume()) < .001
        k.export_shapes([rounded],root/'test.stl')
        assert (root/'test.stl').stat().st_size>100
    checks.append('project, undo/redo, STEP round trip and STL export')
    # Construct actual native widgets, even on CI without a graphics-capable desktop.
    from PySide6.QtWidgets import QApplication
    from .window import MainWindow
    app=QApplication.instance() or QApplication([])
    window=MainWindow();window.document=doc;window.selected=[body.id];window.refresh()
    assert window.tree.topLevelItemCount()==1 and 'Objętość' in window.properties.text()
    window.view.resize(800,600);window.view.fit_all()
    projected,_,_=window.view.project_points(body.mesh.vertices[:3])
    assert window.view._ray(float(projected[0][0]),float(projected[0][1])) is not None
    checks.append('Qt coordinate projection and picking ray')
    window.document._saved_revision=window.document._revision
    window.close();app.processEvents()
    checks.append('Qt native window, object tree and properties')
    from .studio import StudioWindow
    studio=StudioWindow();studio.resize(1400,850);studio.show();app.processEvents()
    assert all(not b.icon().isNull() for b in studio.tools.values()) and studio.shape_buttons
    studio.set_mode('plane');studio.plane_picked('XY')
    for point in ((0,0),(20,10)):studio.sketch_clicked('XY',*point)
    import time
    end=time.monotonic()+15
    while studio.busy and time.monotonic()<end:app.processEvents();time.sleep(.005)
    app.processEvents()
    assert len(studio.document.bodies)==1 and studio.document.bodies[0].kind=='sketch'
    studio.document._saved_revision=studio.document._revision
    studio.close();app.processEvents()
    checks.append('Studio window (HTML layout), icons and click-click sketch')
    result=dict(app='RCCAD Desktop',version=__version__,platform=platform.platform(),passed=True,checks=checks)
    if report_path:
        Path(report_path).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
