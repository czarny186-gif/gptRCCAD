"""Exact CAD references for measurement; no free screen-space guesses."""
import numpy as np
import cadquery as cq
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from . import kernel


def on_shape(edge,point):
    query=BRepExtrema_DistShapeShape(cq.Vertex.makeVertex(*map(float,point)).wrapped,edge.wrapped)
    if not query.IsDone() or query.NbSolution()<1:raise kernel.CadError('Nie udało się wskazać punktu na krawędzi.')
    p=query.PointOnShape2(1)
    return np.array([p.X(),p.Y(),p.Z()])


def angle_between(a,b,unoriented=False):
    a,b=np.asarray(a,float),np.asarray(b,float)
    lengths=np.linalg.norm(a)*np.linalg.norm(b)
    if lengths<1e-12:raise kernel.CadError('Wybierz dwa różne punkty dla każdego ramienia kąta.')
    dot=float(a@b)/lengths
    if unoriented:dot=abs(dot)
    return float(np.degrees(np.arccos(np.clip(dot,-1,1))))


on_edge=on_shape


def angle_arc(origin,a,b,radius):
    o=np.asarray(origin,float);a=np.asarray(a,float);b=np.asarray(b,float)
    if min(np.linalg.norm(a),np.linalg.norm(b))<1e-9:return None
    a=a/np.linalg.norm(a);b=b/np.linalg.norm(b)
    theta=np.arccos(np.clip(a@b,-1,1));v=b-a*(a@b)
    if np.linalg.norm(v)<1e-8:return None
    v/=np.linalg.norm(v);t=np.linspace(0,theta,33)
    return o+radius*(np.cos(t)[:,None]*a+np.sin(t)[:,None]*v)
