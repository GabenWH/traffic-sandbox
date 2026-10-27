#include "spawning.h"
#include <iostream>
#include <memory>

void check(bool ok,const char* message) {if(!ok) throw std::runtime_error(message);}
using EngineOwner=std::unique_ptr<void,decltype(&nt_destroy)>;
int lane(void* engine,double x,double y,double dx,double dy,int key) {
    NTPoint points[]={{x,y},{x+dx,y+dy}};
    NTSection section{0,std::hypot(dx,dy),0,key};
    int route=nt_route(engine,points,2,&section,1,nullptr,0);
    check(route>=0,nt_error());return route;
}
NTSpawn car(int handle,int route,double distance=0,double length=14,double width=6) {
    return {handle,route,0,0,0,0,distance,25*22.0/15,length,width,-1,0,0,-1};
}
void admission_tests() {
    {
        EngineOwner e(nt_create(25),nt_destroy);
        auto a=car(0,lane(e.get(),0,-50,0,100,0),50);
        check(nt_spawn(e.get(),&a,"existing","","")==0,nt_error());
        auto b=car(1,lane(e.get(),0,0,100,0,1));
        check(nt_admit(e.get(),&b,"crossing")==0,"crossing body admitted");
    }
    {
        EngineOwner e(nt_create(25),nt_destroy);
        auto a=car(0,lane(e.get(),0,0,100,0,0),0,40,10);
        check(nt_admit(e.get(),&a,"truck")==1,nt_error());
        auto b=car(1,lane(e.get(),15,0,0,100,1));
        check(nt_admit(e.get(),&b,"car")==0,"long body ignored");
    }
    {
        EngineOwner e(nt_create(25),nt_destroy);
        auto a=car(0,lane(e.get(),0,0,100,0,0));
        auto b=car(1,lane(e.get(),0,12,100,0,1));
        check(nt_admit(e.get(),&a,"first")==1,nt_error());
        check(nt_admit(e.get(),&b,"parallel")==1,"parallel lane rejected");
    }
    {
        EngineOwner e(nt_create(25),nt_destroy);
        int route=lane(e.get(),0,0,100,0,0);
        auto a=car(0,route,30),b=car(1,route);
        check(nt_spawn(e.get(),&a,"leader","","")==0,nt_error());
        check(nt_admit(e.get(),&b,"follower")==0,"short forward gap admitted");
        check(nt_place(e.get(),0,36)==0,nt_error());
        check(nt_admit(e.get(),&b,"follower")==1,"22-foot gap rejected");
    }
}
void routing_tests() {
    SpawnGraph graph;
    graph.nodes={{0,0},{1,0},{1,0},{2,0}};
    graph.adjacency={{0,1},{2},{3},{}};
    for(auto pair:{std::pair<int,int>{0,1},{0,2},{1,3},{2,3}}) {
        SpawnEdge edge{};edge.data.source=pair.first;edge.data.destination=pair.second;edge.data.cost=1;
        graph.edges.push_back(edge);
    }
    SpawnEndpoint first,last;first.point={0,0};first.outgoing={0};last.point={2,0};last.incoming={3};
    graph.endpoints={first,last};
    check(graph.find(0,1).edges==std::vector<int>({0,2}),"A* equal-cost order changed");
    graph.adjacency[0]={1,0};
    check(graph.find(0,1).edges==std::vector<int>({1,3}),"A* ignored insertion order");
    check(!graph.find(1,0).found,"unreachable route found");
}
void scheduling_tests(const SpawnRandom& random) {
    EngineOwner e(nt_create(25),nt_destroy);
    uint32_t state[625];std::copy(random.words.begin(),random.words.end(),state);state[624]=random.index;
    check(nt_rng_set(e.get(),state,625)==0,nt_error());
    NTPoint points[]={{0,0},{100,0}};
    NTGraphEdge edge{};edge.source=0;edge.destination=1;edge.point_count=2;
    edge.kind=1;edge.key=0;edge.connection=-1;edge.incoming=-1;edge.cost=100;edge.length=100;
    NTEndpoint endpoints[]={{0,0,0,1,0,0},{100,0,0,0,1,1}};int ports[]={0,1};
    check(nt_graph(e.get(),points,2,&edge,1,points,2,endpoints,2,ports,2)==0,nt_error());
    int sources[]={0,1};double elapsed[]={0,.5};
    check(nt_sources(e.get(),sources,elapsed,2,1,1,0,0)==0,nt_error());
    for(int i=0;i<40;++i) check(nt_generate(e.get(),.05)==0,nt_error());
    check(nt_spawn_count(e.get())==1,"cap or blocked spawn changed count");
    check(nt_place(e.get(),0,60)==0,nt_error());
    check(nt_sources(e.get(),sources,elapsed,2,1,2,1,1)==0,nt_error());
    for(int i=0;i<20;++i) check(nt_generate(e.get(),.05)==0,nt_error());
    check(nt_spawn_count(e.get())==2,"cleared source did not retry");
}

int main() {
    SpawnRandom rng;
    for (auto& word : rng.words) std::cin >> word;
    std::cin >> rng.index;
    int count; std::cin >> count;
    for (int i=0; i<count; ++i) {
        uint32_t n, expected; std::cin >> n >> expected;
        if (rng.below(n) != expected) return 1;
    }
    try {routing_tests();admission_tests();scheduling_tests(rng);}
    catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 2;}
    for (auto word : rng.words) std::cout << word << ' ';
    std::cout << rng.index << '\n';
}
