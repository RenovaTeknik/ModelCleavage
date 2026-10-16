"""Exact reusable point-to-triangle distance queries with bounded batches."""
import numpy as np
from scipy.spatial import cKDTree
import trimesh


class SurfaceDistance:
    """Exact batched AABB hierarchy; avoids candidate arrays for whole surfaces."""
    def __init__(self,triangles):
        self.triangles=np.asarray(triangles,dtype=np.float64)
        self.vertices=cKDTree(self.triangles.reshape(-1,3))
        low=self.triangles.min(1);high=self.triangles.max(1)
        centres=(low+high)/2
        def build(ids):
            bounds=(low[ids].min(0),high[ids].max(0))
            if len(ids)<=24:return (*bounds,None,None,ids)
            axis=int(np.ptp(centres[ids],axis=0).argmax())
            mid=len(ids)//2;order=ids[np.argpartition(centres[ids,axis],mid)]
            return (*bounds,build(order[:mid]),build(order[mid:]),None)
        self.root=build(np.arange(len(triangles)))

    def __call__(self,points):
        points=np.asarray(points,dtype=np.float64)
        answer=np.empty(len(points))
        def box_distance(node,p):
            delta=np.maximum(np.maximum(node[0]-p,p-node[1]),0)
            return np.square(delta).sum(axis=-1)
        for start in range(0,len(points),512):
            batch=points[start:start+512]
            best=np.square(self.vertices.query(batch)[0])+1e-12
            def visit(node,ids):
                if not len(ids):return
                ids=ids[box_distance(node,batch[ids])<=best[ids]+1e-12]
                if not len(ids):return
                if node[4] is not None:
                    triangles=self.triangles[node[4]];width=len(triangles)
                    q=np.repeat(batch[ids],width,axis=0)
                    close=trimesh.triangles.closest_point(np.tile(triangles,(len(ids),1,1)),q)
                    distances=np.square(close-q).sum(1).reshape(-1,width).min(1)
                    best[ids]=np.minimum(best[ids],distances)
                else:
                    left,right=node[2:4];centre=batch[ids].mean(0)
                    if box_distance(right,centre)<box_distance(left,centre):left,right=right,left
                    visit(left,ids);visit(right,ids)
            visit(self.root,np.arange(len(batch)))
            answer[start:start+len(batch)]=np.sqrt(best)
        return answer


def raster_roof(triangles, low, shape, step, progress=None):
    roof = np.full(int(np.prod(shape)), -np.inf)
    visited = 0
    for number, triangle in enumerate(triangles):
        if progress is not None and number % 256 == 0:
            progress('Projecting painted surface',number,len(triangles))
        a,b,c = triangle
        determinant=(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        if determinant < 1e-10:
            continue
        lo=np.maximum(0,np.ceil((triangle[:,:2].min(axis=0)-1e-7-low)/step).astype(int))
        hi=np.minimum(np.asarray(shape)-1,np.floor((triangle[:,:2].max(axis=0)+1e-7-low)/step).astype(int))
        if np.any(hi<lo):
            continue
        ii,jj=np.meshgrid(np.arange(lo[0],hi[0]+1),np.arange(lo[1],hi[1]+1),indexing='ij')
        ids=(ii.ravel()*shape[1]+jj.ravel())
        x=low[0]+ii.ravel()*step;y=low[1]+jj.ravel()*step
        dx=x-a[0];dy=y-a[1]
        q=(dx*(c[1]-a[1])-dy*(c[0]-a[0]))/determinant
        r=((b[0]-a[0])*dy-(b[1]-a[1])*dx)/determinant
        inside=(q>=-1e-7)&(r>=-1e-7)&(q+r<=1+1e-7)
        roof[ids[inside]]=np.maximum(roof[ids[inside]],a[2]+q[inside]*(b[2]-a[2])+r[inside]*(c[2]-a[2]))
        visited += len(ids)
    return roof,visited
