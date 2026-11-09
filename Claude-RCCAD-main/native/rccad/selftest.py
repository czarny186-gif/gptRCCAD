"""Executed by the packaged EXE as well as Python: validates shipped DLLs and I/O."""
from __future__ import annotations
import json
import math
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
    from . import workers
    if workers.count():          # procesy liczące działają także w spakowanym programie (freeze_support)
        assert workers.start(wait=True), 'worker processes did not start'
        meshed = workers.mesh_many([(shape, True), (rounded, True), (drilled, True)])
        assert all(m is not None and len(m.triangles) for m, _ in meshed)
        checks.append(f'worker processes: {workers.size()} parallel meshing processes')
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
    parallel_recipe = dict(base=sheet['base'],t=2,flanges=walls,rules=dict(gap=.2,joint='parallel'))
    parallel_frames,parallel_corners = shm._effective(walls,2,True)
    parallel_parts = shm._corner_parts(parallel_recipe,parallel_frames,parallel_corners)
    assert not any(abs(face.normalAt().x)>1e-5 and abs(face.normalAt().y)>1e-5
                   for pieces in parallel_parts.values() for piece in pieces for face in piece.Faces()
                   if face.geomType()=='PLANE')
    checks.append('parallel corners: square butt seams at every panel and bend level')
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
    inclined = [dict(spec, angle=135) for spec in walls[:4]]
    inclined_shape = shm.build_sheet(dict(base=sheet['base'],t=2,flanges=inclined,
                                          rules=dict(gap=.2,joint='sheet')))
    assert inclined_shape.isValid() and len(inclined_shape.Solids())==1
    assert sum(f.geomType()=='CYLINDER' for f in inclined_shape.Faces())==8
    checks.append('inclined sheet box: four 135 degree bends with shared corner clearance')
    from . import sheetedit as she
    import cadquery as cq
    edit_recipe=dict(base=sheet['base'],t=2,flanges=[dict(walls[0],length=20)],rules=dict(joint='sheet',gap=.2,kfactor=.44))
    edit_model=she.layout(edit_recipe)
    edited=edit_model.flat.cut(cq.Solid.makeCylinder(1,6,cq.Vector(20,20,-2)))
    refolded,edit_state=she.switch(edited,she.state(edit_recipe,True),False)
    unfolded,_=she.switch(refolded,edit_state,True)
    assert unfolded.isValid() and abs(unfolded.cut(edited).Volume())+abs(edited.cut(unfolded).Volume())<2e-5
    checks.append('editable sheet: unfold, cut hole, refold and restore edited blank')
    bend=edit_model.bends[0];allowance=math.radians(90)*2.88
    span=math.dist(bend.frame['p1'],bend.frame['p0'])
    slot=cq.Solid.makeBox(allowance+2,3,4,cq.Vector(-1,span/2-1.5,-1)).transformShape(bend.flat_frame)
    cut_blank=edit_model.flat.cut(slot)
    bent_slot,slot_state=she.switch(cut_blank,she.state(edit_recipe,True),False)
    restored_slot,_=she.switch(bent_slot,slot_state,True)
    assert bent_slot.isValid() and abs(cut_blank.cut(restored_slot).Volume())+abs(restored_slot.cut(cut_blank).Volume())<1e-4
    checks.append('editable sheet: through slot crosses base, circular bend and flange')
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'edited-sheet.dxf'
        she.export_dxf(edited,she.state(edit_recipe,True),path)
        dxf=ezdxf.readfile(path)
        assert dxf.units==4 and len(dxf.modelspace().query('CIRCLE[layer=="CUT"]'))==1 and not dxf.audit().has_errors
        corner_recipe=dict(base=sheet['base'],t=2,flanges=walls,rules=dict(gap=.2,joint='sheet'))
        corner_blank=she.layout(corner_recipe).flat
        she.export_dxf(corner_blank,she.state(corner_recipe,True),path)
        corner_dxf=ezdxf.readfile(path)
        assert len(corner_dxf.modelspace().query('SPLINE[layer=="CUT"]'))>0 and not corner_dxf.audit().has_errors
    checks.append('edited sheet DXF: analytic circle, complex spline corners, millimetres and bend layers')
    parallel_blank=she.layout(parallel_recipe).flat
    assert parallel_blank.isValid() and len(parallel_blank.Solids())==1
    assert not any(face.innerWires() for face in parallel_blank.Faces() if face.normalAt().z>.99)
    checks.append('parallel sheet: three bend levels unfold without detached strips or hidden holes')
    legacy_parallel=shm.build_sheet(parallel_recipe,parallel_version=1)
    old_source=she.state(parallel_recipe);old_source.pop('bend_engine');old_source['dirty']=True
    old_hole=cq.Solid.makeCylinder(1,5,cq.Vector(20,20,-1))
    migrated,migrated_state=she.rebuild(legacy_parallel.cut(old_hole),old_source,parallel_recipe)
    assert migrated_state['bend_engine']==shm.ENGINE and k.point_state(migrated,(20,20,1))=='out'
    checks.append('legacy parallel sheet migration preserves edited holes')
    slim_base=dict(o=[0,0,0],x=[1,0,0],y=[0,1,0],z=[0,0,1],lx=100,ly=50,lz=1)
    for slim_angle in (45,135):
        slim_specs=[dict(kind='base',p0=[a[0],a[1],1],p1=[b[0],b[1],1],n=[0,0,1],m=m,r=.5,angle=slim_angle,length=5) for a,b,m in edges]
        slim_recipe=dict(base=slim_base,t=1,flanges=slim_specs,rules=dict(joint='parallel',gap=.2))
        slim_result=shm.build_sheet(slim_recipe)
        expected_reach=1.5 if slim_angle==135 else 6.5/math.sqrt(2)
        assert slim_result.isValid() and len(slim_result.Solids())==1
        assert abs(slim_result.BoundingBox().xmax-100-expected_reach)<2e-5
    checks.append('parallel inclined walls: 45 and 135 degree bends keep nominal extents')
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    relieved_specs=[dict(spec,r=.5) for spec in walls]
    relieved_specs += [dict(kind='tip',parent=i+8,side='out',r=.5,angle=45,length=5) for i in range(4)]
    relieved_recipe=dict(base=sheet['base'],t=2,flanges=relieved_specs,rules=dict(joint='parallel',gap=.3))
    relieved=shm.build_sheet(relieved_recipe)
    assert relieved.isValid() and len(relieved.Solids())==1
    assert {round(BRepAdaptor_Surface(face.wrapped).Cylinder().Radius(),6) for face in relieved.Faces() if face.geomType()=='CYLINDER'}=={.5,2.5}
    checks.append('parallel four-level seams: simple reliefs without additional rollover cylinders')
    for hem_joint in ('parallel','sheet'):
        hem_specs=[dict(kind='base',p0=[a[0],a[1],0],p1=[b[0],b[1],0],n=[0,0,-1],m=m,r=1,angle=90,length=3,hem=dict(gap=.2,ret=3)) for a,b,m in edges]
        hem_recipe=dict(base=sheet['base'],t=2,flanges=hem_specs,rules=dict(joint=hem_joint,gap=0))
        hem_body=shm.build_sheet(hem_recipe)
        hem_flat,hem_state=she.switch(hem_body,she.state(hem_recipe),True)
        assert hem_flat.isValid() and len(hem_flat.Solids())==1
        hem_folded,_=she.switch(hem_flat,hem_state,False)
        assert hem_folded.isValid() and len(hem_folded.Solids())==1
        assert abs(hem_folded.Volume(1e-9)-hem_body.Volume(1e-9))<1e-4
    checks.append('four underside hems: parallel and sheet joints unfold and refold with zero corner gap')
    reference_specs=[dict(kind='base',p0=[a[0],a[1],1],p1=[b[0],b[1],1],n=[0,0,1],m=m,r=.5,angle=90,length=20) for a,b,m in edges]
    reference_specs += [dict(kind='tip',parent=i,side='in',r=.5,angle=90,length=5) for i in range(4)]
    reference_specs += [dict(kind='tip',parent=i+4,side='in',r=.5,angle=90,length=5) for i in range(4)]
    reference_recipe=dict(base=slim_base,t=1,flanges=reference_specs,rules=dict(joint='parallel',gap=.2))
    reference_frames,reference_corners=shm._effective(reference_specs,1,True)
    old_parts=shm._corner_parts(reference_recipe,reference_frames,reference_corners,parallel_version=5)
    assert abs(k.bounds(old_parts[0][1]).ymax-50.3)<1e-6           # wersja 5 (starsze projekty): szczelina przed sąsiadem
    reference_parts=shm._corner_parts(reference_recipe,reference_frames,reference_corners)
    assert abs(k.bounds(reference_parts[0][1]).ymax-51.5)<1e-6     # zamknięty narożnik: styk z zewnętrzną powierzchnią sąsiada
    assert abs(k.bounds(reference_parts[1][1]).xmax-100.3)<1e-6
    reference_layout=she.layout(reference_recipe)
    assert reference_layout.flat.isValid() and len(reference_layout.flat.Solids())==1
    for i,left in enumerate(reference_layout.flat_bends[:4]):
        assert all(abs(left.intersect(right).Volume(1e-9))<1e-7 for right in reference_layout.flat_bends[:i])
    checks.append('reference parallel corners: square roots, constant return ends and non-overlapping developed root patches')
    auto_specs=[dict(kind='base',p0=[a[0],a[1],1],p1=[b[0],b[1],1],n=[0,0,1],m=m,r=1,angle=90,length=5) for a,b,m in edges]
    auto_specs.append(dict(kind='tip',parent=0,side='out',r=1,angle=90,length=10,hem=dict(gap=.2,ret=10)))
    auto_recipe=dict(base=slim_base,t=1,flanges=auto_specs,rules=dict(joint='parallel',gap=.2,miter=False,auto_corners=True))
    auto_normalized=shm.normalize(auto_recipe)
    assert auto_normalized['rules']['miter'] and auto_normalized['flanges'][-1]['hem']['ret']==5
    auto_body=shm.build_sheet(auto_recipe);auto_flat,auto_state=she.switch(auto_body,she.state(auto_recipe),True)
    assert auto_flat.isValid() and len(auto_flat.Solids())==1
    auto_folded,_=she.switch(auto_flat,auto_state,False)
    assert auto_folded.isValid() and abs(auto_folded.Volume(1e-9)-auto_body.Volume(1e-9))<1e-4
    checks.append('automatic corners: forced neighbour fitting and hem maximum limited by its supporting flange')

    # Exercise the packaged assembly/joint-baseline modules, not just bare sheets.
    from . import history as history
    with k.deferred_mesh():
        seed=Body('Joint regression',k.box(40,30,1))
        face=max(seed.shape.Faces(),key=lambda f:f.Center().z)
        bodies=history.run_sheet([seed],dict(id=seed.id,face=history.face_ref(face,(0,0,1),face.Center().toTuple(),seed.shape)))
        plate=bodies[0];base=plate.meta['sheet']['recipe']['base']
        import numpy as np
        O=np.array(base['o'])+np.array(base['z']);X=np.array(base['x'])*base['lx'];Y=np.array(base['y'])*base['ly']
        idx=history._edge_on_segment(plate.shape,O,O+X)
        bodies=history.run_sheet_tabwall(bodies,dict(id=plate.id,edges=history.edge_refs(plate.shape,[idx]),t=1,length=12,width=4,fit=.1,corner='parallel'))
        wall=bodies[-1];wb=wall.meta['sheet']['recipe']['base'];Z=np.array(wb['z'])
        C=np.array(wb['o'])+wb['lx']/2*np.array(wb['x'])+wb['ly']/2*np.array(wb['y'])-Z
        drill=cq.Solid.makeCylinder(.8,3,cq.Vector(*C),cq.Vector(*Z))
        bodies=[b.changed(b.shape.cut(drill)) if b.id==wall.id else b for b in bodies]
        W=np.array(wb['o'])+Z;A=np.array(wb['x'])*wb['lx'];B=np.array(wb['y'])*wb['ly']
        for bid,mid,L in ((wall.id,W+B+A/2,4),(plate.id,O+X+Y/2,12)):
            body=next(b for b in bodies if b.id==bid);r=body.meta['sheet']['recipe']
            spec=shm.spec_for_edge(r['base'],1,r['flanges'],r.get('rules'),mid,.1)
            spec.update(r=.5,angle=90,length=L,measure='outer')
            bodies=history.run_sheetbuild(bodies,dict(id=bid,base=r['base'],t=1,flanges=[*r['flanges'],spec],rules=dict(auto_corners=True,miter=True,joint='parallel',gap=.1)))
        if workers.ready():
            r=next(b for b in bodies if b.id==plate.id).meta['sheet']['recipe']
            bodies=history.offloaded(history.run_sheetbuild,bodies,dict(r,id=plate.id))
        assert next(b for b in bodies if b.id==wall.id).shape.intersect(drill).Volume()<1e-6
        for flat in (True,False):
            bodies=history.run_sheetmode(bodies,dict(id=plate.id,flat=flat))
            assert all(b.shape.isValid() and len(b.shape.Solids())==1 for b in bodies)
    checks.append('tab-wall assembly: user hole retained after wall/base bending, unfold and refold')
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
    assert studio.fl_joint.findData('diagonal') == -1
    assert not hasattr(studio,'fl_miter') and studio._flange_rules()['auto_corners']
    test_body=Body('Sheet selection',edit_model.folded,meta={'sheet':she.state(edit_recipe)}).prepared()
    studio.document.commit([test_body]);studio.selected=[test_body.id]
    studio.set_mode('flange')
    assert test_body.id not in studio.view.selected_bodies and test_body.id in studio.selected
    studio.set_mode(None)
    assert test_body.id in studio.view.selected_bodies
    checks.append('sheet tools: two corner choices and edge-only highlighting during bends')
    for command,flat in [('unfold_sheet',True),('fold_sheet',False)]:
        studio.tools[command].click();end=time.monotonic()+20
        while studio.busy and time.monotonic()<end:app.processEvents();time.sleep(.005)
        app.processEvents()
        assert not studio.busy and studio.document.get(test_body.id).meta['sheet']['flat']==flat
    checks.append('Qt editable sheet: unfold and refold buttons with persistent sheet identity')

    from PySide6.QtGui import QVector3D
    from . import measurement
    import cadquery as cq
    probe_shape=k.boolean('subtract',k.box(20,20,20),[k.box(10,10,10).translate(cq.Vector(5,5,5))])
    probe=Body('Section chamber',probe_shape).prepared()
    studio.document.commit([probe]);studio.selected=[];studio.refresh()
    studio.view.opts['center']=QVector3D(10,10,10)
    studio.view.setCameraPosition(distance=90,elevation=0,azimuth=-90)
    xy=studio.view.project_one((10,15,10))
    studio.toggle_section(True);studio.section_pick(*xy);studio.section_offset.setValue(10)
    assert abs(studio.view.pick_face(*xy)[2][1]-15)<1e-4
    wall_xy=studio.view.project_one((2,10,10))
    assert studio.view.pick_body(*wall_xy)==probe.id
    assert studio.view.pick_face(*wall_xy) is None
    if studio.view.isValid():
        assert not studio.view.grabFramebuffer().isNull()
        assert studio.view.section_caps.available is True
    checks.append('Section material: opaque hatched wall blocks hidden faces and preserves open chamber')
    from .sectionmesh import cap_mesh
    import numpy as np
    material=cap_mesh(probe.mesh,[0,1,0,-10])
    triangles=material.vertices[material.triangles]
    area=np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),axis=1).sum()/2
    assert abs(float(area)-300)<1e-3
    checks.append('Portable section material: bundled contour triangulator preserves chamber independently of stencil')
    studio.section_work_button.click()
    assert studio.section_working and not studio.view.section_handles and studio.section_work_button.text()=='PRZERWIJ'
    studio.set_mode('mod')
    assert not studio.view.section_handles
    assert studio.view.section_plane is not None and studio.document.get(probe.id).shape is probe_shape
    studio.section_work_button.click()
    assert not studio.section_working and studio.view.section_handles
    studio.toggle_section(False)
    assert studio.section_origin is None and studio.section_offset.value()==0 and studio.mode is None
    studio.toggle_section(True)
    assert studio.section_picking and studio.view.section_plane is None
    studio.toggle_section(False)
    assert studio.view.section_plane is None and abs(studio.view.pick_face(*xy)[2][1])<1e-4
    checks.append('Section view: closed chamber revealed, original interior face picked, persistent across tools, non-destructive disable')
    projection=studio.view._edge_projection(probe)
    assert projection is studio.view._edge_projection(probe)
    camera=studio.view._camera_data();studio.view.project_one((2,0,10))
    assert camera is studio.view._camera_data()
    assert len(probe.mesh.face_ids)==len(probe.mesh.triangles)
    checks.append('Accelerated picking: cached projection, stable camera and triangle-to-CAD face mapping')
    studio.set_mode('mangle')
    assert [studio.ms_angle_kind.itemData(i) for i in range(studio.ms_angle_kind.count())]==['points','edges','faces']
    assert abs(measurement.angle_between([1,0,0],[-1,1,0],True)-45)<1e-8
    assert abs(float(sum(measurement.on_edge(cq.Edge.makeCircle(10),[7,7,0])**2))-100)<1e-6
    studio.set_mode('mdist')
    import numpy as np
    studio.ms_points=[np.array([0.,0.,0.]),np.array([10.,0.,0.])]
    studio.ms_refs=[dict(point=q,label='Vertex') for q in studio.ms_points]
    studio._measure_points_update();studio.context_menu(5,5)
    assert len(studio.ms_points)==1 and len(studio.view.measure_labels)==1
    assert all(p.scroll is not None for p in studio.ms_panels.values())
    studio.set_mode(None)
    checks.append('Measurements: point/edge/face angle modes, exact CAD snapping, right-click undo and scrollable result panels')

    studio.document._saved_revision=studio.document._revision
    studio.close();app.processEvents()
    checks.append('Studio window (HTML layout), icons and click-click sketch')
    result=dict(app='RCCAD Desktop',version=__version__,platform=platform.platform(),passed=True,checks=checks)
    if report_path:
        Path(report_path).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
