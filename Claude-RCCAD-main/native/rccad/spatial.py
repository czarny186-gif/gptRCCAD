"""Conservative AABB hierarchy shared by scene picking and face candidates."""
import numpy as np


class BoundsTree:
    def __init__(self,low,high,leaf=8):
        self.low=np.asarray(low,float).reshape(-1,3);self.high=np.asarray(high,float).reshape(-1,3);self.nodes=[]
        def build(ids):
            lo=self.low[ids].min(axis=0);hi=self.high[ids].max(axis=0);index=len(self.nodes);self.nodes.append(None)
            if len(ids)<=leaf:self.nodes[index]=(lo,hi,ids,None)
            else:
                centers=(self.low[ids]+self.high[ids])*.5;axis=np.argmax(np.ptp(centers,axis=0))
                ids=ids[np.argsort(centers[:,axis],kind='stable')];mid=len(ids)//2
                self.nodes[index]=(lo,hi,None,(build(ids[:mid]),build(ids[mid:])))
            return index
        if len(self.low):build(np.arange(len(self.low)))

    def ray(self,origin,direction):
        origin=np.asarray(origin);direction=np.asarray(direction);out=[];stack=[0] if self.nodes else []
        def crosses(lo,hi):
            parallel=np.abs(direction)<1e-15
            if np.any(parallel & ((origin<lo-1e-7)|(origin>hi+1e-7))):return False
            inv=np.divide(1.,direction,out=np.zeros(3),where=~parallel)
            a=(lo-origin)*inv;b=(hi-origin)*inv
            near=np.where(parallel,-np.inf,np.minimum(a,b)).max();far=np.where(parallel,np.inf,np.maximum(a,b)).min()
            return far>=max(near,0)-1e-7
        while stack:
            lo,hi,ids,children=self.nodes[stack.pop()]
            if not crosses(lo,hi):continue
            if ids is not None:out.extend(i for i in ids if crosses(self.low[i],self.high[i]))
            else:stack.extend(children)
        return sorted(out)

    def point(self,point,margin=0):
        out=[];stack=[0] if self.nodes else [];p=np.asarray(point)
        while stack:
            lo,hi,ids,children=self.nodes[stack.pop()]
            if np.any(p<lo-margin) or np.any(p>hi+margin):continue
            if ids is not None:
                keep=np.all((p>=self.low[ids]-margin)&(p<=self.high[ids]+margin),axis=1);out.extend(ids[keep])
            else:stack.extend(children)
        return sorted(out)

    def overlap(self,low,high,margin=0):
        out=[];stack=[0] if self.nodes else [];low=np.asarray(low)-margin;high=np.asarray(high)+margin
        while stack:
            lo,hi,ids,children=self.nodes[stack.pop()]
            if np.any(hi<low) or np.any(lo>high):continue
            if ids is not None:
                keep=np.all((self.high[ids]>=low)&(self.low[ids]<=high),axis=1);out.extend(ids[keep])
            else:stack.extend(children)
        return sorted(out)
