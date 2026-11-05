"""Square parallel corner ends, reconstructed from the supplied CAD reference.

Congruent orthogonal chains returning into the base keep one through end;
its neighbour receives a constant plane clearing the bend and following turn.
Shared material at the root turns belongs to one bend only. Other corner
families continue to use the previous construction and its edit baselines.
"""
import math
import numpy as np
import cadquery as cq
from . import kernel as k


def _families(specs):
    owners=[];depths=[];families={}
    for i,f in enumerate(specs):
        owner=i if f['kind']=='base' else owners[f['parent']]
        depth=0 if f['kind']=='base' else depths[f['parent']]+1
        owners.append(owner);depths.append(depth);families.setdefault(owner,[]).append(i)
    return owners,depths,families


def eligible(recipe,eff,corners):
    rules=recipe.get('rules') or {}
    if not corners or rules.get('joint','parallel')!='parallel':return False
    if any(f.get('hem') or abs(float(f['angle'])-90)>1e-6 for f in eff):return False
    owners,depths,families=_families(recipe['flanges']);normal=np.asarray(recipe['base']['z'],float)
    signatures={}
    for owner,indices in families.items():
        root=eff[owner];signature=[]
        for i in indices:
            f=eff[i];direction=math.cos(math.radians(f['angle']))*f['m']+math.sin(math.radians(f['angle']))*f['n']
            if i!=owner and float(direction@root['m'])>1e-6:return False
            signature.append(tuple(round(float(v),8) for v in
                (f['r'],f['angle'],f['length'],(f['p0']-root['p0'])@root['m'],(f['p0']-root['p0'])@normal,
                 f['n']@root['m'],f['n']@normal,f['m']@root['m'],f['m']@normal)))
        signatures[owner]=signature
    return all(all(x==y for x,y in zip(signatures[a],signatures[b])) for _,a,b,_ in corners)


def parts(recipe,eff,corners):
    from . import sheetmetal as s
    specs,t=recipe['flanges'],float(recipe['t']);gap=float((recipe.get('rules') or {}).get('gap',0))
    frames,owners,depths,extension=s._corner_layout(specs,eff,corners,t)
    raw={i:s._flange_parts(f,t) for i,f in enumerate(frames)};result={i:list(v) for i,v in raw.items()}
    lookup={(owner,depth):i for i,(owner,depth) in enumerate(zip(owners,depths))}
    reach=sum(float(recipe['base'][key]) for key in ('lx','ly','lz'))+4*extension+gap+1
    normal=s._unit(recipe['base']['z']);caps={};bounds={}
    for i in sorted(result,key=lambda j:depths[j]):
        for c,(point,a,b,_) in enumerate(corners):
            owner=owners[i]
            if owner not in (a,b):continue
            other=b if owner==a else a;direction=eff[other]['m'];peer=lookup.get((other,depths[i]))
            if depths[i]==0:
                profile=s._leg_profile(eff[other],eff[other],point,normal,t)
                stop=float(profile[:,0].min())-gap
            elif owner==a or peer is None:
                stop=caps[specs[i]['parent'],c]
            else:
                key=(peer,c)
                if key not in bounds:
                    pieces=list(raw[peer])+[raw[j][0] for j in raw if specs[j].get('parent')==peer]
                    plane=cq.Plane(origin=tuple(point),xDir=tuple(direction),normal=tuple(np.cross(direction,normal)))
                    bounds[key]=min(k.bounds(piece.transformShape(plane.fG)).xmin for piece in pieces)
                stop=bounds[key]-gap
            caps[i,c]=stop
            result[i]=[s._endcut(piece,point+stop*direction,direction,reach) for piece in result[i]]
    # Root sectors meet in a small shared corner, as in the reference solid.
    # Partition that material rather than relaxing global collision checks.
    for _,a,b,_ in corners:
        left,right=result[a][0],result[b][0]
        key=('parallel-root-partition',s._sig(right),s._sig(left))
        if key[1] is None or key[2] is None:key=None
        result[b][0]=s._ops_memo(key,lambda right=right,left=left:k.boolean('subtract',right,[left]))
    for i,pieces in result.items():
        end,_,_,direction=s._tip_geom(eff[i],'out',t)
        vertices=[np.asarray(v.toTuple()) for v in pieces[-1].Vertices()
                  if abs(float((np.asarray(v.toTuple())-end)@direction))<s._TOL]
        axis=s._unit(eff[i]['p1']-eff[i]['p0'])
        if len(vertices)<2 or np.ptp([float(v@axis) for v in vertices])<s._TOL:
            raise k.CadError('Narożniki zabierają cały koniec kołnierza. Zmniejsz jego długość albo zmień kierunek gięcia.')
    return result


def partition_flat_roots(flat_bends,bends,corners):
    """Give each tiny developed root-corner patch one owner, including K<0.5.

    A closed root corner has common material in the formed model. Its flat
    counterpart must not contain two overlapping copies of that same patch.
    Panels, unrelated bends and genuine development collisions are untouched.
    """
    for _,a,b,_ in corners:
        flat_bends[b]=k.boolean('subtract',flat_bends[b],[flat_bends[a]])
        bends[b].flat=flat_bends[b]
