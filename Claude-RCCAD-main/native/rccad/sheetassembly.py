"""Rebuild folded tab-wall assemblies from clean sheets before cutting joints.

Contacts are found on individual straight panels, never on a bounding slab of a
bent part. Joint cuts therefore stop at tangent lines and cannot enter a bend.
"""
from dataclasses import replace
import numpy as np
from . import kernel as k,sheetmetal as s,sheetedit as e,sheetjoints as j,plywood as p


def _clear_bend_ends(shape,model,other,clearance,other_model):
    """A neighbouring sheet may shorten a bend axially, never shave its arc."""
    reach=2+sum(abs(c) for v in shape.Vertices() for c in v.toTuple())
    for bend in model.bends:
        if not p._boxes_near(bend.folded,other):continue
        common=bend.folded.intersect(other)
        if e._volume(common)<1e-7:continue
        axis=s._unit(np.asarray(bend.frame['p1'])-np.asarray(bend.frame['p0']))
        lo,hi=p.extent(bend.folded,axis);left,right=lo,hi
        support=[p.extent(panel.folded,axis) for panel in other_model.panels if abs(float(np.asarray([panel.folded_frame[row,2] for row in range(3)])@axis))>1-1e-6]
        near_left=any(a-1e-5<=lo<=b+1e-5 for a,b in support)
        near_right=any(a-1e-5<=hi<=b+1e-5 for a,b in support)
        for region in common.Solids():
            a,b=p.extent(region,axis)
            if a<=lo+1e-5 or (near_left and (a+b)/2<(lo+hi)/2):left=max(left,b+clearance/2)
            elif b>=hi-1e-5 or (near_right and (a+b)/2>(lo+hi)/2):right=min(right,a-clearance/2)
            else:raise k.CadError('Ścianka przecina środek gięcia. Zmień jej położenie lub kierunek.')
        if right-left<1e-5:raise k.CadError('Sąsiednia ścianka zabiera całą długość gięcia.')
        trimmed=bend.folded
        if left>lo+1e-5:trimmed=s._endcut(trimmed,left*axis,-axis,reach)
        if right<hi-1e-5:trimmed=s._endcut(trimmed,right*axis,axis,reach)
        cut=bend.folded.cut(trimmed)
        if e._volume(cut)>1e-7:shape=k.boolean('subtract',shape,[cut])
    return shape


def rebuild(bodies,recipe):
    from . import history as h
    target=h._body(bodies,recipe['id']);root=h.sheet_root(bodies,target.id)
    walls=h.sheet_tab_walls(bodies,root.id);members=[root,*walls]
    made={};models={};features={}
    for old in members:
        state=old.meta['sheet'];auto=j.baseline(state)
        if auto is not None:features[old.id]=e._diff(auto,old.shape)
        else:features[old.id]=(None,None)
        nominal=recipe if old.id==target.id else state['recipe']
        if old is not root:
            tab=old.meta['ply']['tab'];parent=made[tab['sheet']];frame=h._sheet_frame(parent)
            ends=[(frame@np.append(q,1.))[:3] for q in tab['seg']]
            idx=h._edge_on_segment(parent.shape,*ends)
            if idx is None:raise k.CadError(f'{old.name}: po gięciu nie znaleziono krawędzi pod ścianką.')
            edge,plate=h._nominal_edge(parent,parent.shape.Edges()[idx])
            r=tab['recipe'];wall,_,up=p.tab_wall(parent.shape,edge,r['t'],r['length'],r.get('measure','outer'),bool(r.get('flip')),plate)
            nominal=h._wall_bend_recipe(nominal,h._wall_base(wall,r['t'],up))
        model=e.layout(nominal);shape=model.folded
        removed,added=features[old.id]
        if removed is not None and e._volume(removed)>1e-7:shape=k.boolean('subtract',shape,[removed])
        if added is not None and e._volume(added)>1e-7:shape=k.boolean('union',shape,[added])
        models[old.id]=model
        made[old.id]=replace(old,shape=shape,mesh=None,meta=dict(old.meta,sheet=e.state(nominal)))
    # Earlier sheets take precedence at physical intersections. Coplanar panels
    # use the selected seam rule, including planar finger joints.
    raw={bid:replace(b,meta=dict(b.meta,sheet=j.remember(models[bid].folded,b.meta['sheet']))) for bid,b in made.items()}
    ids=list(made);joined={bid:set() for bid in ids}
    for pos,bid in enumerate(ids[1:],1):
        body=made[bid];r=body.meta['ply']['tab']['recipe'];shape=body.shape
        for aid in ids[:pos]:
            other=made[aid]
            for wp in models[bid].panels:
                for ap in models[aid].panels:
                    if not p._boxes_near(wp.folded,ap.folded):continue
                    A=shape.intersect(wp.folded);B=other.shape.intersect(ap.folded)
                    if e._volume(A)<1e-7 or e._volume(B)<1e-7 or e._volume(A.intersect(B))<1e-7:continue
                    na=p.panel_info(wp.folded)['n'];nb=p.panel_info(ap.folded)['n']
                    if abs(float(na@nb))<1-1e-6:continue
                    A2,changes,partners=p.resolve_overlaps(A,float(body.meta['sheet']['recipe']['t']),[(aid,B,float(other.meta['sheet']['recipe']['t']))],r.get('corner','parallel'),float(r.get('width') or 0),float(r.get('fit',0)))
                    if aid in changes:
                        shape=k.boolean('union',k.boolean('subtract',shape,[A]),[A2])
                        other=replace(other,shape=k.boolean('union',k.boolean('subtract',other.shape,[B]),[changes[aid]]),mesh=None)
                        joined[bid].add(aid);joined[aid].add(bid)
            shape=_clear_bend_ends(shape,models[bid],other.shape,float(r.get('fit',0)),models[aid])
            shape=h._ply_trim(shape,[other.shape]);made[aid]=other
        made[bid]=replace(body,shape=shape,mesh=None)
    # Detect contacts on the actual, trimmed flat material, then apply each
    # contact to its complete owning solid. Curved regions are never cut.
    for pos,bid in enumerate(ids[1:],1):
        r=made[bid].meta['ply']['tab']['recipe'];t=float(made[bid].meta['sheet']['recipe']['t'])
        for aid in ids[:pos]:
            for wi,wp in enumerate(models[bid].panels):
                for ai,ap in enumerate(models[aid].panels):
                    if not p._boxes_near(wp.folded,ap.folded):continue
                    A=made[bid].shape.intersect(wp.folded);B=made[aid].shape.intersect(ap.folded)
                    if e._volume(A)<1e-7 or e._volume(B)<1e-7 or not p._boxes_near(A,B):continue
                    contacts,_=p.find_contacts([dict(id=bid,shape=A,**p.panel_info(wp.folded,t)),dict(id=aid,shape=B,**p.panel_info(ap.folded,float(made[aid].meta['sheet']['recipe']['t'])))])
                    for c in contacts:
                        c['joint']=p.joint_for('laser',c['kind']);c['key']=f'{bid}:{wi}:{aid}:{ai}'
                        params=dict(method='laser',width=float(r.get('width') or 0),fit=float(r.get('fit',0)))
                        before={x:made[x].shape for x in (bid,aid)}
                        normals={bid:p.panel_info(wp.folded,t)['n'],aid:p.panel_info(ap.folded)['n']}
                        failures=[]
                        result=p.apply_joints({x:(before[x],normals[x]) for x in before},[c],params,failures=failures)
                        if failures:continue
                        for key,after in result.items():
                            removed,added=e._diff(before[key],after);shape=before[key]
                            regions=[q.folded for q in models[key].panels]
                            cuts=[]
                            if e._volume(removed)>1e-7:
                                cuts=[part for q in regions if e._volume(part:=removed.intersect(q))>1e-7]
                            if cuts:shape=k.boolean('subtract',shape,cuts)
                            keep=[so for so in added.Solids() if all(e._volume(so.intersect(b))<1e-7 for b in models[key].folded_bends)]
                            if keep:shape=k.boolean('union',shape,keep)
                            made[key]=replace(made[key],shape=shape,mesh=None)
                        joined[bid].add(aid);joined[aid].add(bid)
    for bid,body in list(made.items()):
        if len(body.shape.Solids())!=1:raise k.CadError(f'{body.name}: połączenia rozdzieliły blachę.')
        k.valid(body.shape)
        body=j.updated(raw[bid],body)
        meta=dict(body.meta,sheet=dict(body.meta['sheet'],dirty=True,assembly=1))
        if meta.get('ply'):meta['ply']=dict(meta['ply'],joined=sorted(joined[bid]))
        made[bid]=replace(body,meta=meta,mesh=None if k.mesh_deferred() else k.display_mesh(body.shape))
    for i,bid in enumerate(ids):
        for aid in ids[i+1:]:
            if e._volume(made[bid].shape.intersect(made[aid].shape))>1e-5:
                raise k.CadError('Połączenia ścianek nachodzą na siebie. Zmień długość lub kierunek kołnierzy.')
    return [made.get(b.id,b) for b in bodies]
