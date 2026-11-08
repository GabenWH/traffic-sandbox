#include "scene.h"
#include <string>
#include <stdexcept>
#include <exception>
#include "textNode.h"

namespace {
thread_local std::string error;
ViewerScene& get(void* p){if(!p)throw std::invalid_argument("Viewer scene is closed");return *static_cast<ViewerScene*>(p);}
template<class Fn> int checked(Fn fn){try{error.clear();fn();return 0;}catch(const std::exception& e){error=e.what();return -1;}}
}
extern "C" {
int nv_abi(){return 1;}
const char* nv_error(){return error.c_str();}
void* nv_create(void* root,void* camera){
    try{if(!root)throw std::invalid_argument("Missing Panda scene root");
        return new ViewerScene(*static_cast<NodePath*>(root),camera?*static_cast<NodePath*>(camera):NodePath());
    }catch(const std::exception& e){error=e.what();return nullptr;}
}
void nv_destroy(void* p){delete static_cast<ViewerScene*>(p);}
int nv_static(void* p,const NVVertex* t,int nt,const NVVertex* l,int nl){return checked([&]{get(p).replace_static(t,nt,l,nl);});}
int nv_register(void* p,const NVVisual* v,const double* heights,int count){return checked([&]{if(!v)throw std::invalid_argument("Missing visual");get(p).register_vehicle(*v,heights,count);});}
int nv_clear_metadata(void* p){return checked([&]{get(p).clear_metadata();});}
int nv_parked(void* p,const NVParked* rows,int n){return checked([&]{get(p).replace_parked(rows,n);});}
int nv_texts(void* p,const NVText* rows,int n){return checked([&]{
    auto& scene=get(p);if(n<0||(!rows&&n))throw std::invalid_argument("Invalid overlay text snapshot");
    NodePath replacement("overlay-text");
    for(int i=0;i<n;++i){const auto& t=rows[i];if(!t.text)throw std::invalid_argument("Missing overlay text");
        PT(TextNode) text=new TextNode("editor-label");text->set_text(t.text);
        text->set_text_color(t.r,t.g,t.b,t.a);text->set_align(t.align==1?TextNode::A_center:t.align==2?TextNode::A_right:TextNode::A_left);
        if(t.wrap>0&&t.size>0)text->set_wordwrap(t.wrap/t.size);
        auto node=replacement.attach_new_node(text);node.set_scale(t.size);node.set_pos(t.x,0,-t.y-t.size*.8f);
    }
    scene.text_root.remove_node();scene.text_root=replacement;scene.text_root.reparent_to(scene.world);
});}
int nv_camera(void* p,void* camera){return checked([&]{get(p).set_camera(camera?*static_cast<NodePath*>(camera):NodePath());});}
int nv_bounds(void* p,double l,double t,double r,double b){return checked([&]{get(p).set_bounds(l,t,r,b);});}
int nv_update(void* p,const NTState* rows,int n,double elapsed){return checked([&]{get(p).update(rows,n,elapsed);});}
int nv_pedestrians(void* p,const NTPedestrianState* rows,int n){return checked([&]{get(p).pedestrians(rows,n);});}
int nv_native_update(void* p,void* engine,std::uintptr_t vehicles,std::uintptr_t pedestrians,double elapsed){
    return checked([&]{
        if(!engine||!vehicles||!pedestrians)throw std::invalid_argument("Missing native traffic binding");
        using Vehicles=const NTState*(*)(void*,int*);using Pedestrians=const NTPedestrianState*(*)(void*,int*);
        int n=0;auto states=reinterpret_cast<Vehicles>(vehicles)(engine,&n);get(p).update(states,n,elapsed);
        // Consume the vehicle buffer before the next engine operation.
        n=0;auto people=reinterpret_cast<Pedestrians>(pedestrians)(engine,&n);get(p).pedestrians(people,n);
    });
}
int nv_stats(void* p,NVStats* out){return checked([&]{if(!out)throw std::invalid_argument("Missing stats output");*out=get(p).stats;});}
const NVPose* nv_snapshot(void* p,int* count){
    try{auto& s=get(p);if(!count)throw std::invalid_argument("Missing snapshot count");*count=static_cast<int>(s.poses.size());return s.poses.data();}
    catch(const std::exception& e){error=e.what();if(count)*count=-1;return nullptr;}
}
}
