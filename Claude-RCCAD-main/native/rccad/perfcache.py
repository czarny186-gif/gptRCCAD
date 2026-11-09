"""Size-bounded LRU caches; evict individual entries, never flush a live scene."""
from collections import OrderedDict
from threading import RLock
from functools import wraps
import numpy as np


def array_bytes(value):
    seen=set()
    def size(v):
        if id(v) in seen:return 0
        seen.add(id(v))
        if isinstance(v,np.ndarray):return v.nbytes
        if isinstance(v,(bytes,bytearray)):return len(v)
        if type(v).__name__ in ('DisplayMesh','MeshData'):return size(v.__dict__)
        if isinstance(v,dict):return sum(size(x) for x in v.values())
        if isinstance(v,(tuple,list)):return sum(size(x) for x in v)
        return 0
    return size(value)


def _locked(method):
    @wraps(method)
    def call(self,*args,**kwargs):
        with self._lock:return method(self,*args,**kwargs)
    return call


class LRU(OrderedDict):
    def __init__(self,max_bytes=256*1024*1024,max_entries=4096):
        super().__init__();self.max_bytes=max_bytes;self.max_entries=max_entries;self.bytes=0;self._sizes={};self._lock=RLock()

    @_locked
    def get(self,key,default=None):
        if key not in self:return default
        self.move_to_end(key);return self[key]

    @_locked
    def __setitem__(self,key,value):
        size=array_bytes(value)
        if size>self.max_bytes:
            self.pop(key,None);return
        if key in self:self.bytes-=self._sizes.pop(key)
        super().__setitem__(key,value);self.move_to_end(key)
        self._sizes[key]=size;self.bytes+=size
        while self and (self.bytes>self.max_bytes or len(self)>self.max_entries):
            old=next(iter(self));self.pop(old)

    @_locked
    def pop(self,key,*default):
        if key in self:self.bytes-=self._sizes.pop(key)
        return super().pop(key,*default)

    @_locked
    def clear(self):
        super().clear();self._sizes.clear();self.bytes=0
