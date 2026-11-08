#include "scene.h"
#include "geomNode.h"
#include "geomTriangles.h"
#include "geomVertexWriter.h"
#include "geomVertexArrayFormat.h"
#include "geomVertexArrayData.h"
#include "omniBoundingVolume.h"
#include "boundingBox.h"
#include <cstring>
#include <algorithm>

namespace {
void box(std::vector<NVVertex>& out,float x,float y,float z,float w,float l,float h,
         float r,float g,float b,float role=1){
    const float xyz[8][3]={{x-w/2,y-l/2,z-h/2},{x+w/2,y-l/2,z-h/2},
        {x+w/2,y+l/2,z-h/2},{x-w/2,y+l/2,z-h/2},{x-w/2,y-l/2,z+h/2},
        {x+w/2,y-l/2,z+h/2},{x+w/2,y+l/2,z+h/2},{x-w/2,y+l/2,z+h/2}};
    const int faces[6][4]={{0,3,2,1},{4,5,6,7},{0,1,5,4},{1,2,6,5},{2,3,7,6},{3,0,4,7}};
    for(const auto& f:faces)for(int i:{f[0],f[1],f[2],f[0],f[2],f[3]})
        out.push_back({xyz[i][0],xyz[i][1],xyz[i][2],r,g,b,role});
}
const char* vertex_shader=R"GLSL(#version 330
uniform mat4 p3d_ModelViewProjectionMatrix;
in vec4 p3d_Vertex;
in vec4 p3d_Color;
in vec4 instance_pose;
in vec4 instance_size;
in vec4 instance_color;
in vec4 instance_lamps;
out vec4 tint;
void main(){
    vec3 p=p3d_Vertex.xyz*vec3(instance_size.z,instance_size.y,instance_size.w);
    vec2 forward=vec2(instance_pose.w,instance_size.x);
    vec2 right=vec2(forward.y,-forward.x);
    p.xy=instance_pose.xy+right*p.x+forward*p.y;
    p.z+=instance_pose.z;
    gl_Position=p3d_ModelViewProjectionMatrix*vec4(p,1.0);
    float role=p3d_Color.a;
    vec3 rgb=role<0.5?instance_color.rgb:p3d_Color.rgb;
    if(role>2.5&&role<3.5)rgb=instance_lamps.x>0.5?vec3(1.,.96,.70):vec3(.19,.22,.25);
    if(role>3.5&&role<4.5)rgb=instance_lamps.y>0.5?vec3(1.,.69,0.):vec3(.26,.23,.16);
    if(role>4.5)rgb=instance_lamps.z>0.5?vec3(1.,.69,0.):vec3(.26,.23,.16);
    tint=vec4(rgb,1.);
})GLSL";
const char* fragment_shader=R"GLSL(#version 330
in vec4 tint;
out vec4 fragColor;
void main(){fragColor=tint;}
)GLSL";
}

std::vector<NVVertex> nv_model(const NVVisual& v){
    std::vector<NVVertex> out;
    if(v.shape==4){box(out,0,0,.5,1,1,1,1,1,1,0);return out;}
    if(v.shape==0){
        box(out,0,-.01,.40,.90,.98,.40,1,1,1,0);
        box(out,0,-.06,.80,.72,.46,.40,.10,.17,.22);
        for(float x:{-.44f,.44f})for(float y:{-.30f,.30f})box(out,x,y,.16,.12,.13,.32,.08,.09,.10);
        box(out,0,.49,.43,.56,.02,.12,1,1,1,3);
        box(out,-.38,.49,.43,.12,.02,.12,1,1,1,4);
        box(out,.38,.49,.43,.12,.02,.12,1,1,1,5);
    }else{
        box(out,0,-.01,.25,.86,.88,.22,.20,.23,.25);
        for(float x:{-.48f,.48f})for(float y:{-.30f,.29f})box(out,x,y,.14,.13,.19,.28,.08,.09,.10);
        if(v.shape==1){
            box(out,0,-.15,.39,.82,.57,.08,.56,.59,.61);
            for(float x:{-.41f,.41f})box(out,x,-.15,.49,.035,.58,.2,.66,.69,.71);
            if(v.load>0){float h=(v.cargo==1?.06f:.08f)*std::max(.25f,v.load);
                float r=v.cargo==1?.74f:.55f,g=v.cargo==1?.54f:.58f,b=v.cargo==1?.34f:.62f;
                if(v.cargo==2){
                    for(float x:{-.20f,.20f})for(float y:{-.27f,-.06f})box(out,x,y,.47+h/2,.22,.14,h,r,g,b);
                }else for(float x:{-.24f,0.f,.24f})box(out,x,-.15,.47+h/2,.13,.42*std::max(.25f,v.load),h,r,g,b);
            }
        }else{
            box(out,0,-.15,.55,.86,.58,.52,.93,.88,.78);
            for(float x:{-.44f,.44f})box(out,x,-.15,.61,.02,.32,.18,.10,.17,.22);
            for(int i=0;i<std::min(3,v.workers);++i)box(out,(i-1)*.2f,-.15,.83,.08,.08,.05,1,.69,0);
        }
        box(out,0,.28,.58,.84,.36,.58,1,1,1,0);
        box(out,0,.465,.61,.62,.025,.25,.10,.17,.22);
        for(float x:{-.29f,.29f})box(out,x,.48,.42,.16,.025,.10,1,1,1,3);
        box(out,-.50,.48,.42,.08,.025,.10,1,1,1,4);
        box(out,.50,.48,.42,.08,.025,.10,1,1,1,5);
    }
    return out;
}

NVBatch& ViewerScene::batch(std::map<std::array<int,6>,NVBatch>& groups,const NVVisual& v,const NodePath& parent,int cell_x,int cell_y){
    int load_bits=0;std::memcpy(&load_bits,&v.load,sizeof(float));
    std::array<int,6> key={v.shape,v.cargo,v.workers,load_bits,cell_x,cell_y};
    auto found=groups.find(key);if(found!=groups.end())return found->second;
    if(!shader)shader=Shader::make(Shader::SL_GLSL,vertex_shader,fragment_shader);
    PT(GeomVertexArrayFormat) vertex=new GeomVertexArrayFormat();
    vertex->add_column(InternalName::get_vertex(),3,Geom::NT_float32,Geom::C_point);
    vertex->add_column(InternalName::get_color(),4,Geom::NT_float32,Geom::C_other);
    PT(GeomVertexArrayFormat) inst=new GeomVertexArrayFormat();
    for(const char* name: {"instance_pose","instance_size","instance_color","instance_lamps"})
        inst->add_column(InternalName::make(name),4,Geom::NT_float32,Geom::C_other);
    inst->set_divisor(1);
    PT(GeomVertexFormat) format=new GeomVertexFormat();format->add_array(vertex);format->add_array(inst);
    auto registered=GeomVertexFormat::register_format(format);
    PT(GeomVertexData) data=new GeomVertexData("instances",registered,Geom::UH_stream);
    auto model=nv_model(v);data->modify_array(0)->set_num_rows(static_cast<int>(model.size()));
    GeomVertexWriter p(data,"vertex"),c(data,"color");
    for(const auto& point:model){p.add_data3(point.x,point.y,point.z);c.add_data4(point.r,point.g,point.b,point.a);}
    PT(GeomTriangles) triangles=new GeomTriangles(Geom::UH_static);
    for(int i=0;i<static_cast<int>(model.size());i+=3)triangles->add_vertices(i,i+1,i+2);
    triangles->close_primitive();PT(Geom) geom=new Geom(data);geom->add_primitive(triangles);
    PT(GeomNode) node=new GeomNode("instanced-model");node->add_geom(geom);
    if(&groups==&parked_batches)
        node->set_bounds(new BoundingBox(LPoint3(cell_x*500-80,cell_y*500-80,-10),
                                        LPoint3(cell_x*500+580,cell_y*500+580,1000)));
    else node->set_bounds(new OmniBoundingVolume());
    node->set_final(true);
    NodePath path=parent.attach_new_node(node);path.set_shader(shader);path.hide();
    auto result=groups.emplace(key,NVBatch{path,data,{}});return result.first->second;
}
void ViewerScene::upload(std::map<std::array<int,6>,NVBatch>& groups,int kind){
    for(auto& entry:groups){auto& b=entry.second;int n=static_cast<int>(b.instances.size());
        if(kind==0&&entry.first[0]==4)continue;
        if(kind==1&&entry.first[0]!=4)continue;
        if(!n){b.node.hide();continue;}
        auto handle=b.data->modify_array(1)->modify_handle();handle->set_num_rows(n);
        std::memcpy(handle->get_write_pointer(),b.instances.data(),b.instances.size()*sizeof(NVInstance));
        if(&groups==&parked_batches){
            LPoint3 low(1e30f,1e30f,1e30f),high(-1e30f,-1e30f,-1e30f);
            for(const auto& in:b.instances){
                float radius=std::max(in.heading_size[1],in.heading_size[2]);
                low.set(std::min(low[0],in.pose[0]-radius),std::min(low[1],in.pose[1]-radius),std::min(low[2],in.pose[2]));
                high.set(std::max(high[0],in.pose[0]+radius),std::max(high[1],in.pose[1]+radius),std::max(high[2],in.pose[2]+in.heading_size[3]));
            }
            b.node.node()->set_bounds(new BoundingBox(low,high));
        }
        b.node.set_instance_count(n);b.node.show();
    }
    for(auto it=groups.begin();it!=groups.end();){
        if(it->second.instances.empty()&&(&groups==&parked_batches||groups.size()>64)){
            it->second.node.remove_node();it=groups.erase(it);
        }else ++it;
    }
    stats.actor_geoms=0;
    for(const auto* collection:{&batches,&parked_batches})for(const auto& b:*collection)
        if(!b.second.instances.empty())++stats.actor_geoms;
}
