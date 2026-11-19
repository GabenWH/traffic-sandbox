"""Bulk C++ Panda3D presentation. No Python callbacks occur inside native updates.

SDK headers must match the loaded Panda runtime. Geometry is copied on upload;
traffic state is borrowed and consumed synchronously, on the simulation/UI thread.
"""
from __future__ import annotations
import ctypes as C
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import os
import re
import shlex
import subprocess
import sys
import tempfile
import numpy as np


class Visual(C.Structure):
    _fields_=[(n,C.c_int) for n in ('handle','shape','cargo','workers')]+[
        (n,C.c_float) for n in ('length','width','height','r','g','b','load')]

class Parked(C.Structure):
    _fields_=[('visual',Visual)]+[(n,C.c_double) for n in ('x','y','z','hx','hy')]

class _Pose(C.Structure):
    _fields_=[('handle',C.c_int),('kind',C.c_int)]+[(n,C.c_double) for n in ('x','y','z','hx','hy')]

class _Text(C.Structure):
    _fields_=[(n,C.c_float) for n in ('x','y','size','r','g','b','a','wrap')]+[('align',C.c_int),('text',C.c_char_p)]

class _Stats(C.Structure):
    _fields_=[(n,C.c_int) for n in ('static_geoms','static_triangles','static_lines',
        'active_vehicles','visible_vehicles','pedestrians','visible_pedestrians',
        'parked_vehicles','actor_geoms')]+[('frames',C.c_uint64)]


def _sdk_paths():
    import panda3d
    from panda3d import core
    library=Path(os.environ.get('PANDA3D_LIBRARY_DIR',Path(panda3d.__file__).parent))
    project_sdk=Path(__file__).resolve().parent/'build/panda-sdk'
    explicit_include=os.environ.get('PANDA3D_INCLUDE_DIR')
    explicit_sdk=os.environ.get('PANDA3D_SDK')
    if explicit_include:
        includes=[Path(explicit_include)]
    elif explicit_sdk:
        root=Path(explicit_sdk)
        includes=[root/'include',root/'include/panda3d',root/'usr/include/panda3d']
    else:
        includes=[project_sdk/'usr/include/panda3d',Path('/usr/include/panda3d'),
                  Path('/usr/local/include/panda3d'),Path('/Library/Developer/Panda3D/include')]
    runtime_version=core.PandaSystem.get_version_string()
    runtime_eigen=core.PandaSystem.get_global_ptr().has_system('eigen')
    mismatches=[]
    include=None
    for candidate in includes:
        if not (candidate/'nodePath.h').is_file():continue
        version_header=candidate/'pandaVersion.h'
        match=re.search(r'^\s*#\s*define\s+PANDA_VERSION_STR\s+"([^"]+)"',
                        version_header.read_text() if version_header.is_file() else '',re.MULTILINE)
        version=match.group(1) if match else 'unknown'
        config=candidate/'dtool_config.h'
        if not config.is_file():
            mismatches.append(f'{candidate} (SDK {version}, missing dtool_config.h)');continue
        sdk_eigen=bool(re.search(r'^\s*#\s*define\s+HAVE_EIGEN(?:\s|$)',
                                 config.read_text(),re.MULTILINE))
        if version==runtime_version and sdk_eigen==runtime_eigen:
            include=candidate;break
        mismatches.append(f'{candidate} (SDK {version}, Eigen {"enabled" if sdk_eigen else "disabled"})')
    if include is None:
        if mismatches:
            raise RuntimeError(f'Panda3D C++ SDK version or Eigen setting does not match the loaded Python runtime '
                               f'{runtime_version} (Eigen {"enabled" if runtime_eigen else "disabled"}): '
                               f'{", ".join(mismatches)}. '
                               'Install a matching SDK with compatible build options and set '
                               'PANDA3D_INCLUDE_DIR; see native/viewer/README.md.')
        if explicit_include or explicit_sdk:
            raise RuntimeError(f'Panda3D SDK headers not found at {explicit_include or explicit_sdk}. '
                               'Check PANDA3D_INCLUDE_DIR or PANDA3D_SDK; see native/viewer/README.md.')
        raise RuntimeError('The native viewer requires Panda3D C++ SDK headers matching the Python runtime. '
                           'Install the Panda3D SDK and set PANDA3D_INCLUDE_DIR; see native/viewer/README.md.')
    if os.environ.get('EIGEN3_INCLUDE_DIR'):
        eigen=[Path(os.environ['EIGEN3_INCLUDE_DIR'])]
    else:
        eigen=[include.parent/'eigen3',*sorted(project_sdk.glob('eigen-*')),
               Path('/usr/include/eigen3'),Path('/usr/local/include/eigen3'),Path('/opt/homebrew/include/eigen3')]
    extra=next((p for p in eigen if (p/'Eigen/Core').is_file()),None)
    if sdk_eigen and extra is None:
        raise RuntimeError('This Panda3D SDK requires Eigen headers. Install eigen3 or set EIGEN3_INCLUDE_DIR.')
    return include,library,extra


@lru_cache(maxsize=1)
def _library():
    from panda3d import core
    root=Path(__file__).resolve().parent
    include,library,eigen=_sdk_paths()
    sources=sorted((root/'native/viewer').glob('*.cpp'))
    headers=sorted((root/'native/viewer').glob('*.h'))+[root/'native/traffic/engine.h']
    compiler=os.environ.get('CXX','c++')
    flags=shlex.split(os.environ.get('PANDA3D_CXXFLAGS',''))
    libraries=[]
    for name in ('panda','pandaexpress','p3dtoolconfig','p3dtool'):
        candidates=[library/f'lib{name}.so.1.10',library/f'lib{name}.so',library/f'lib{name}.dylib']
        path=next((p for p in candidates if p.exists()),None)
        if path is None:raise RuntimeError(f'Matching Panda library lib{name} was not found in {library}')
        libraries.append(path)
    # Manylinux wheels use the old libstdc++ string ABI; distro SDKs generally do not.
    if sys.platform.startswith('linux'):
        panda=C.CDLL(str(libraries[0]))
        if hasattr(panda,'_ZN8NodePathC1ERKSsP6Thread'):
            flags.append('-D_GLIBCXX_USE_CXX11_ABI=0')
    fingerprint=b''.join(p.read_bytes() for p in sources+headers)+str((include,library,eigen,compiler,flags)).encode()
    fingerprint+=(include/'dtool_config.h').read_bytes()+(include/'pandaVersion.h').read_bytes()
    fingerprint+=core.PandaSystem.get_version_string().encode()
    digest=sha256(fingerprint).hexdigest()[:20]
    folder=root/'build/native-viewer';folder.mkdir(parents=True,exist_ok=True)
    target=folder/('viewer-'+digest+('.dylib' if sys.platform=='darwin' else '.so'))
    if not target.exists():
        fd,name=tempfile.mkstemp(prefix='viewer-',suffix=target.suffix,dir=folder);os.close(fd)
        try:
            command=[compiler,'-std=c++17','-O3','-fPIC','-shared','-Wall','-Wextra','-Werror',
                     '-isystem',str(include),*(['-isystem',str(eigen)] if eigen else []),*flags,
                     *map(str,sources),*map(str,libraries),f'-Wl,-rpath,{library}','-o',name]
            subprocess.run(command,check=True,capture_output=True,text=True)
            os.replace(name,target)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError('Native Panda viewer compilation failed:\n'+exc.stderr) from exc
        finally:Path(name).unlink(missing_ok=True)
    lib=C.CDLL(str(target))
    from native_traffic import NativeVehicleView,NativePedestrianState
    P=C.c_void_p;I=C.c_int;D=C.c_double
    signatures={
        'nv_abi':(I,[]),'nv_error':(C.c_char_p,[]),'nv_create':(P,[P,P]),'nv_destroy':(None,[P]),
        'nv_static':(I,[P,P,I,P,I]),'nv_register':(I,[P,C.POINTER(Visual),P,I]),
        'nv_clear_metadata':(I,[P]),'nv_parked':(I,[P,C.POINTER(Parked),I]),
        'nv_texts':(I,[P,C.POINTER(_Text),I]),
        'nv_camera':(I,[P,P]),'nv_bounds':(I,[P,D,D,D,D]),
        'nv_update':(I,[P,C.POINTER(NativeVehicleView),I,D]),
        'nv_pedestrians':(I,[P,C.POINTER(NativePedestrianState),I]),
        'nv_native_update':(I,[P,P,C.c_size_t,C.c_size_t,D]),
        'nv_stats':(I,[P,C.POINTER(_Stats)]),'nv_snapshot':(C.POINTER(_Pose),[P,C.POINTER(I)]),
    }
    for name,(restype,args) in signatures.items():
        fn=getattr(lib,name);fn.restype=restype;fn.argtypes=args
    if lib.nv_abi()!=1:raise RuntimeError('Incompatible native viewer ABI')
    return lib


def visual(handle,appearance,length,width,color):
    from color_palette import panda_rgba
    shape=3 if appearance.kind=='bus' else {'car':0,'material_truck':1,'crew_truck':2}[appearance.shape]
    if shape==1:color='#37e6ff'
    if shape==2:color='#ffb000'
    r,g,b,_=panda_rgba(color)
    return Visual(handle,shape,{'lumber':1,'stone':2,'steel':3}.get(appearance.cargo_key,0),appearance.workers,
                  length,width,5 if shape==0 else 8.5 if shape==2 else 8,r,g,b,appearance.load_fraction)


def _vertices(value):
    data=np.ascontiguousarray(value,dtype=np.float32)
    if data.ndim!=2 or data.shape[1]!=7:raise ValueError('Scene vertices require an Nx7 numeric array')
    return data


class NativeScene:
    def __init__(self,root,camera=None):
        self._lib=_library();self._root=root;self._camera=camera
        self._ptr=self._lib.nv_create(int(root.this),int(camera.this) if camera is not None else None)
        if not self._ptr:raise RuntimeError(self._lib.nv_error().decode())

    def _call(self,name,*args):
        if not self._ptr:raise RuntimeError('Native viewer scene is closed')
        result=getattr(self._lib,name)(self._ptr,*args)
        if result<0:raise ValueError(self._lib.nv_error().decode())
        return result

    def replace_static(self,triangles,lines):
        triangles,lines=_vertices(triangles),_vertices(lines)
        self._call('nv_static',triangles.ctypes.data,len(triangles),lines.ctypes.data,len(lines))

    def register_vehicle(self,handle,appearance,length,width,color,heights):
        heights=np.ascontiguousarray(heights,dtype=np.float64)
        if heights.ndim!=2 or heights.shape[1]!=2:raise ValueError('Route height rulers require Nx2 values')
        v=visual(handle,appearance,length,width,color)
        self._call('nv_register',C.byref(v),heights.ctypes.data,len(heights))

    def clear_metadata(self):self._call('nv_clear_metadata')

    def replace_parked(self,rows):
        data=(Parked*len(rows))(*rows)
        self._call('nv_parked',data,len(data))

    def update_states(self,rows,count,elapsed):self._call('nv_update',rows,count,elapsed)

    def replace_texts(self,rows):
        data=(_Text*len(rows))(*(_Text(*row[:-1],row[-1].encode('utf-8')) for row in rows))
        self._call('nv_texts',data,len(data))

    def update_native(self,engine,elapsed):
        if not engine._ptr:raise RuntimeError('Native traffic engine is closed')
        vehicles=C.cast(engine._lib.nt_states,C.c_void_p).value
        pedestrians=C.cast(engine._lib.nt_pedestrian_states,C.c_void_p).value
        self._call('nv_native_update',engine._ptr,vehicles,pedestrians,elapsed)

    def set_camera(self,camera):
        self._camera=camera;self._call('nv_camera',int(camera.this) if camera is not None else None)

    def set_bounds(self,bounds=None):
        self._call('nv_bounds',*(bounds if bounds is not None else (float('nan'),)*4))

    def stats(self):
        result=_Stats();self._call('nv_stats',C.byref(result))
        return {name:getattr(result,name) for name,_ in result._fields_}

    def snapshot(self):
        if not self._ptr:raise RuntimeError('Native viewer scene is closed')
        n=C.c_int();rows=self._lib.nv_snapshot(self._ptr,C.byref(n))
        if n.value<0:raise ValueError(self._lib.nv_error().decode())
        return [{name:getattr(rows[i],name) for name,_ in _Pose._fields_} for i in range(n.value)]

    def close(self):
        if self._ptr:self._lib.nv_destroy(self._ptr);self._ptr=None
