#pragma once
#include "nodePath.h"
#include "geomVertexData.h"
#include "shader.h"
#include "../traffic/engine.h"
#include <map>
#include <vector>
#include <array>
#include <cstdint>

struct NVVertex { float x,y,z,r,g,b,a; };
struct NVVisual { int handle,shape,cargo,workers; float length,width,height,r,g,b,load; };
struct NVParked { NVVisual visual; double x,y,z,hx,hy; };
struct NVPose { int handle,kind; double x,y,z,hx,hy; };
struct NVText { float x,y,size,r,g,b,a,wrap; int align; const char* text; };
struct NVStats {
    int static_geoms,static_triangles,static_lines,active_vehicles,visible_vehicles;
    int pedestrians,visible_pedestrians,parked_vehicles,actor_geoms;
    std::uint64_t frames;
};
struct NVInstance { float pose[4],heading_size[4],color[4],lamps[4]; };
struct NVRoute { std::vector<std::array<double,2>> points; };
struct NVActor { NVVisual visual; NVRoute heights; };
struct NVBatch { NodePath node; PT(GeomVertexData) data; std::vector<NVInstance> instances; };

class ViewerScene {
public:
    ViewerScene(const NodePath &root,const NodePath &camera);
    ~ViewerScene();
    void replace_static(const NVVertex*,int,const NVVertex*,int);
    void register_vehicle(const NVVisual&,const double*,int);
    void clear_metadata();
    void replace_parked(const NVParked*,int);
    void update(const NTState*,int,double);
    void pedestrians(const NTPedestrianState*,int);
    void set_camera(const NodePath&);
    void set_bounds(double,double,double,double);
    NodePath root,world,static_root,dynamic_root,parked_root,camera,text_root;
    std::map<int,NVActor> actors;
    std::map<std::array<int,6>,NVBatch> batches,parked_batches;
    std::vector<NVPose> poses;
    NVStats stats{};
private:
    PT(Shader) shader;
    bool bounded=false;
    std::array<double,4> bounds{};
    LMatrix4f view_projection;
    bool visible(double,double,double) const;
    NVBatch& batch(std::map<std::array<int,6>,NVBatch>&,const NVVisual&,const NodePath&,int=0,int=0);
    void upload(std::map<std::array<int,6>,NVBatch>&,int=-1);
};

NodePath nv_geometry(const std::vector<NVVertex>&,bool,const NodePath&,const std::string&);
std::vector<NVVertex> nv_model(const NVVisual&);
