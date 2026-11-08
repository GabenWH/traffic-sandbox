#include "scene.h"
#include "geomNode.h"
#include "geomTriangles.h"
#include "geomLines.h"
#include "geomVertexWriter.h"
#include "geomVertexFormat.h"
#include "camera.h"
#include "lens.h"
#include <cmath>
#include <stdexcept>
#include <tuple>
#include <algorithm>

NodePath nv_geometry(const std::vector<NVVertex>& vertices,bool lines,
                     const NodePath& parent,const std::string& name) {
    PT(GeomVertexData) data=new GeomVertexData(name,GeomVertexFormat::get_v3c4(),Geom::UH_static);
    data->set_num_rows(static_cast<int>(vertices.size()));
    GeomVertexWriter p(data,"vertex"),c(data,"color");
    for(const auto& v:vertices){p.add_data3(v.x,v.y,v.z);c.add_data4(v.r,v.g,v.b,v.a);}
    PT(GeomPrimitive) prim;
    if(lines)prim=new GeomLines(Geom::UH_static);else prim=new GeomTriangles(Geom::UH_static);
    int size=lines?2:3;
    for(int i=0;i<static_cast<int>(vertices.size());i+=size){
        if(lines)prim->add_vertices(i,i+1);else prim->add_vertices(i,i+1,i+2);
    }
    prim->close_primitive();
    PT(Geom) geom=new Geom(data);geom->add_primitive(prim);
    PT(GeomNode) node=new GeomNode(name);node->add_geom(geom);
    return parent.attach_new_node(node);
}

ViewerScene::ViewerScene(const NodePath &parent,const NodePath &cam):root(parent),camera(cam){
    world=root.attach_new_node("native-world");world.set_scale(1,-1,1);world.set_two_sided(true);
    static_root=world.attach_new_node("static");
    dynamic_root=world.attach_new_node("actors");
    parked_root=world.attach_new_node("parked");
}
ViewerScene::~ViewerScene(){world.remove_node();}
void ViewerScene::set_camera(const NodePath& cam){camera=cam;}
void ViewerScene::set_bounds(double l,double t,double r,double b){
    bounded=std::isfinite(l)&&std::isfinite(t)&&std::isfinite(r)&&std::isfinite(b);
    bounds={l,t,r,b};
}
void ViewerScene::replace_static(const NVVertex* triangles,int nt,const NVVertex* lines,int nl){
    if(nt<0||nl<0||nt%3||nl%2||(!triangles&&nt)||(!lines&&nl))throw std::invalid_argument("Invalid static geometry counts");
    using Key=std::tuple<int,int,int>;
    std::map<Key,std::vector<NVVertex>> cells;
    auto append=[&](const NVVertex* data,int count,int step,int kind){
        for(int i=0;i<count;i+=step){
            double x=0,y=0;
            for(int j=0;j<step;++j){
                const auto& v=data[i+j];const float values[]={v.x,v.y,v.z,v.r,v.g,v.b,v.a};
                for(float value:values)if(!std::isfinite(value))throw std::invalid_argument("Non-finite static geometry");
                x+=v.x;y+=v.y;
            }
            auto &out=cells[{static_cast<int>(std::floor(x/step/500)),static_cast<int>(std::floor(y/step/500)),kind}];
            out.insert(out.end(),data+i,data+i+step);
        }
    };
    append(triangles,nt,3,0);append(lines,nl,2,1);
    // Construct a detached replacement first: malformed data cannot erase the world.
    NodePath replacement("static");
    for(const auto& entry:cells)nv_geometry(entry.second,std::get<2>(entry.first)!=0,replacement,"cell");
    static_root.remove_node();static_root=replacement;static_root.reparent_to(world);
    stats.static_geoms=static_cast<int>(cells.size());stats.static_triangles=nt/3;stats.static_lines=nl/2;
}
void ViewerScene::register_vehicle(const NVVisual& v,const double* heights,int count){
    const float values[]={v.length,v.width,v.height,v.r,v.g,v.b,v.load};
    for(float value:values)if(!std::isfinite(value))throw std::invalid_argument("Non-finite vehicle appearance");
    if(v.handle<0||v.shape<0||v.shape>3||v.length<=0||v.width<=0||v.height<=0||count<1||!heights)
        throw std::invalid_argument("Invalid vehicle appearance or route ruler");
    NVActor actor;actor.visual=v;
    for(int i=0;i<count;++i){
        double d=heights[2*i],z=heights[2*i+1];
        if(!std::isfinite(d)||!std::isfinite(z)||d<0||(i&&d<heights[2*i-2]))throw std::invalid_argument("Invalid route height ruler");
        actor.heights.points.push_back({d,z});
    }
    actors[v.handle]=std::move(actor);
}
void ViewerScene::clear_metadata(){actors.clear();}
bool ViewerScene::visible(double x,double y,double z) const {
    if(bounded)return x>=bounds[0]-64&&x<=bounds[2]+64&&y>=bounds[1]-64&&y<=bounds[3]+64;
    if(camera.is_empty())return true;
    LVecBase4f p(static_cast<float>(x),static_cast<float>(y),static_cast<float>(z),1);
    p=p*view_projection;
    float w=p[3];return w>0&&std::abs(p[0])<=w*1.1f&&std::abs(p[1])<=w*1.1f&&p[2]>=-w&&p[2]<=w;
}
void ViewerScene::update(const NTState* rows,int count,double elapsed){
    if(count<0||(!rows&&count)||!std::isfinite(elapsed))throw std::invalid_argument("Invalid actor snapshot");
    if(!camera.is_empty()){
        const auto* cam=DCAST(Camera,camera.node());
        view_projection=world.get_mat(camera)*cam->get_lens()->get_projection_mat();
    }
    for(auto& b:batches)if(b.first[0]!=4)b.second.instances.clear();
    poses.clear();stats.active_vehicles=0;stats.visible_vehicles=0;
    const bool flash=std::fmod(elapsed,1.)<.5;
    for(int i=0;i<count;++i){
        const auto& s=rows[i];if(!s.alive)continue;
        auto entry=actors.find(s.handle);if(entry==actors.end())throw std::invalid_argument("Unregistered native vehicle handle");
        const auto& actor=entry->second;const auto& h=actor.heights.points;
        auto hi=std::upper_bound(h.begin(),h.end(),s.distance,[](double d,const auto& v){return d<v[0];});
        double z;
        if(hi==h.begin())z=h.front()[1];else if(hi==h.end())z=h.back()[1];
        else {auto lo=hi-1;double d=(*hi)[0]-(*lo)[0];double f=d>0?(s.distance-(*lo)[0])/d:1;z=(*lo)[1]+f*((*hi)[1]-(*lo)[1]);}
        poses.push_back({s.handle,0,s.x,s.y,z,s.hx,s.hy});++stats.active_vehicles;
        if(!visible(s.x,s.y,z))continue;
        const auto& v=actor.visual;NVInstance in{};
        in.pose[0]=s.x;in.pose[1]=s.y;in.pose[2]=z;in.pose[3]=s.hx;
        in.heading_size[0]=s.hy;in.heading_size[1]=v.length;in.heading_size[2]=v.width;in.heading_size[3]=v.height;
        in.color[0]=v.r;in.color[1]=v.g;in.color[2]=v.b;in.color[3]=1;
        // Native SignalIntent order: off, left, right, hazard.
        in.lamps[0]=1;in.lamps[1]=flash&&(s.signal==1||s.signal==3);in.lamps[2]=flash&&(s.signal==2||s.signal==3);
        batch(batches,v,dynamic_root).instances.push_back(in);++stats.visible_vehicles;
    }
    upload(batches,0);++stats.frames;
}
void ViewerScene::pedestrians(const NTPedestrianState* rows,int count){
    if(count<0||(!rows&&count))throw std::invalid_argument("Invalid pedestrian snapshot");
    // A separate kind key prevents a pedestrian update from clearing cars.
    NVVisual v{};v.handle=-1;v.shape=4;v.length=2;v.width=2;v.height=5;
    auto& b=batch(batches,v,dynamic_root);b.instances.clear();stats.pedestrians=count;stats.visible_pedestrians=0;
    for(int i=0;i<count;++i){const auto& p=rows[i];if(!visible(p.x,p.y,1))continue;
        NVInstance in{};in.pose[0]=p.x;in.pose[1]=p.y;in.pose[2]=1;in.pose[3]=0;
        in.heading_size[0]=1;in.heading_size[1]=2;in.heading_size[2]=2;in.heading_size[3]=5;
        in.color[0]=p.waiting?.90f:.55f;in.color[1]=p.waiting?.66f:.19f;in.color[2]=p.waiting?.20f:.74f;in.color[3]=1;
        b.instances.push_back(in);++stats.visible_pedestrians;
    }
    upload(batches,1);
}
void ViewerScene::replace_parked(const NVParked* rows,int count){
    if(count<0||(!rows&&count))throw std::invalid_argument("Invalid parked snapshot");
    for(auto& b:parked_batches)b.second.instances.clear();
    for(int i=0;i<count;++i){const auto& p=rows[i];const auto& v=p.visual;NVInstance in{};
        in.pose[0]=p.x;in.pose[1]=p.y;in.pose[2]=p.z;in.pose[3]=p.hx;
        in.heading_size[0]=p.hy;in.heading_size[1]=v.length;in.heading_size[2]=v.width;in.heading_size[3]=v.height;
        in.color[0]=v.r;in.color[1]=v.g;in.color[2]=v.b;in.color[3]=1;
        batch(parked_batches,v,parked_root,static_cast<int>(std::floor(p.x/500)),
              static_cast<int>(std::floor(p.y/500))).instances.push_back(in);
    }
    upload(parked_batches);stats.parked_vehicles=count;
}
