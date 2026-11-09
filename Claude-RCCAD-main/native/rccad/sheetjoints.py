"""Persistent automatic joint baselines, separate from ordinary user edits.

BREP is compressed and stored in the sheet's local frame, in thickness units.
Rigid placement, uniform scaling, project persistence and worker transport thus
keep the baseline with the part without special world-coordinate snapshots.
"""
import base64
import zlib
from functools import lru_cache
import cadquery as cq
import numpy as np
from . import kernel as k


def _frame(state):
    from . import sheetedit as e
    b=state['recipe']['base']
    return e._matrix(np.asarray(b['o'],float),[np.asarray(b[x],float) for x in ('x','y','z')])


def remember(shape,state):
    from . import sheetedit as e
    local=shape.transformShape(e._inverse(_frame(state))).scale(1/float(state['recipe']['t']))
    data=base64.b85encode(zlib.compress(k._brep_bytes(local))).decode('ascii')
    return dict(state,joints=data)


@lru_cache(maxsize=64)
def _decode(data):
    return k._from_brep(zlib.decompress(base64.b85decode(data.encode('ascii'))))


def baseline(state):
    data=state.get('joints')
    if not data:return None
    return _decode(data).scale(float(state['recipe']['t'])).transformShape(_frame(state))


def edited_bare(actual,state,model=None):
    """Remove only automatic joints, retaining material added/cut by the user."""
    from . import sheetedit as e
    auto=baseline(state)
    if auto is None:return actual,dict(state)
    model=model or e._source_layout(state)
    shape=model.flat if state.get('flat') else model.folded
    removed,added=e._diff(auto,actual)
    if e._volume(removed)>1e-7:shape=k.boolean('subtract',shape,[removed])
    if e._volume(added)>1e-7:shape=k.boolean('union',shape,[added])
    clean={key:value for key,value in state.items() if key!='joints'}
    clean.update(dirty=e._volume(removed)+e._volume(added)>1e-7,edited=False)
    return shape,clean


def updated(before,after):
    """Record a joint operation without absorbing any existing user features."""
    from . import sheetedit as e
    state=(after.meta or {}).get('sheet')
    if not state:return after
    old=(before.meta or {}).get('sheet') if before else None
    user_removed=user_added=None
    if old:
        auto=baseline(old)
        if auto is None:
            model=e._source_layout(old);auto=model.flat if old.get('flat') else model.folded
        user_removed,user_added=e._diff(auto,before.shape)
        removed,added=e._diff(before.shape,after.shape)
        if e._volume(removed)>1e-7:auto=k.boolean('subtract',auto,[removed])
        if e._volume(added)>1e-7:auto=k.boolean('union',auto,[added])
    else:auto=after.shape
    shape=after.shape
    if user_removed is not None and e._volume(user_removed)>1e-7:shape=k.boolean('subtract',shape,[user_removed])
    if user_added is not None and e._volume(user_added)>1e-7 and e._volume(user_added.cut(shape))>1e-5:
        raise k.CadError('Nowe połączenie narusza materiał dodany przez użytkownika. Zmień położenie połączenia.')
    from dataclasses import replace
    return replace(after,shape=shape,mesh=(None if k.mesh_deferred() else k.display_mesh(shape)) if shape is not after.shape else after.mesh,meta=dict(after.meta,sheet=remember(auto,state)))
