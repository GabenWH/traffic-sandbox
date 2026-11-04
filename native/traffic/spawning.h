#pragma once
#include "engine.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <queue>
#include <stdexcept>
#include <tuple>
#include <vector>

// Python's Random state is imported directly, avoiding seed-algorithm differences.
struct SpawnRandom {
    std::array<uint32_t,624> words{};
    unsigned index=624;
    uint32_t next() {
        if(index>=624) {
            for(unsigned i=0;i<624;++i) {
                uint32_t y=(words[i]&0x80000000U)|(words[(i+1)%624]&0x7fffffffU);
                words[i]=words[(i+397)%624]^(y>>1)^((y&1)?0x9908b0dfU:0);
            }
            index=0;
        }
        uint32_t y=words[index++];y^=y>>11;y^=(y<<7)&0x9d2c5680U;
        y^=(y<<15)&0xefc60000U;y^=y>>18;return y;
    }
    uint32_t below(uint32_t n) {
        if(!n) throw std::invalid_argument("empty random choice");
        unsigned k=0;for(auto value=n;value;value>>=1) ++k;
        uint32_t r;
        do {r=next()>>(32-k);} while(r>=n);
        return r;
    }
    void shuffle(std::vector<int>& values) {
        for(size_t i=values.size();i>1;--i) std::swap(values[i-1],values[below(static_cast<uint32_t>(i))]);
    }
};

struct SpawnEdge { NTGraphEdge data; std::vector<NTPoint> points; };
struct SpawnEndpoint { NTPoint point; std::vector<int> outgoing, incoming; int lane=-1, reverse_lane=-1; double distance=0; };
struct SpawnPath { std::vector<int> edges; double cost=0; bool found=false; std::vector<SpawnEdge> extras; };
struct SpawnGraph {
    std::vector<NTPoint> nodes;
    std::vector<SpawnEdge> edges;
    std::vector<std::vector<int>> adjacency;
    std::vector<SpawnEndpoint> endpoints;

    static double length(const std::vector<NTPoint>& points) {
        double total=0;for(size_t i=1;i<points.size();++i) total+=std::hypot(points[i].x-points[i-1].x,points[i].y-points[i-1].y);return total;
    }
    static NTPoint at(const std::vector<NTPoint>& points,double distance) {
        for(size_t i=1;i<points.size();++i) {auto a=points[i-1],b=points[i];double d=std::hypot(b.x-a.x,b.y-a.y);if(!d) continue;
            if(distance<=d) {double f=distance/d;return {a.x+(b.x-a.x)*f,a.y+(b.y-a.y)*f};}distance-=d;}
        return points.back();
    }
    SpawnEdge partial(int lane,double from,double to,int source,int destination) const {
        SpawnEdge result=edges.at(lane);double total=result.data.length;
        from=std::max(0.0,std::min(total,from));to=std::max(from,std::min(total,to));
        std::vector<NTPoint> points{at(result.points,from)};double travelled=0;
        for(size_t i=1;i<result.points.size();++i) {auto a=result.points[i-1],b=result.points[i];travelled+=std::hypot(b.x-a.x,b.y-a.y);if(from<travelled && travelled<to) points.push_back(b);}
        auto end=at(result.points,to);if(points.size()==1 || std::hypot(points.back().x-end.x,points.back().y-end.y)>1e-9) points.push_back(end);
        result.points=std::move(points);result.data.source=source;result.data.destination=destination;
        result.data.cost=to-from;result.data.offset=from;result.data.length=length(result.points);return result;
    }
    SpawnEndpoint query(int junction,int lane,double distance,NTPoint point) const {
        if(lane<0) return endpoints.at(junction);
        auto& edge=edges.at(lane);
        if(edge.data.kind!=1 || edge.points.size()<2 || !std::isfinite(distance) || distance<0 || distance>edge.data.length+1e-8 || !std::isfinite(point.x) || !std::isfinite(point.y)) throw std::invalid_argument("invalid lane endpoint");
        SpawnEndpoint result;result.point=point;result.lane=lane;result.distance=distance;return result;
    }

    SpawnPath find(int source,int destination) const {
        return find(endpoints.at(source),endpoints.at(destination),source==destination);
    }
    SpawnPath find(const SpawnEndpoint& from,const SpawnEndpoint& to,bool same=false) const {
        int start=static_cast<int>(nodes.size()),goal=start+1;
        std::vector<SpawnEdge> extras;
        std::vector<int> first, last, direct;
        // Query-local endpoint overlays; the compiled adjacency is never copied.
        auto origins=[&](const SpawnEndpoint& endpoint) {
            std::vector<std::pair<int,double>> lanes;
            if(endpoint.lane>=0) lanes.emplace_back(endpoint.lane,endpoint.distance);
            if(endpoint.reverse_lane>=0)
                lanes.emplace_back(endpoint.reverse_lane,edges[endpoint.reverse_lane].data.length-endpoint.distance);
            return lanes;
        };
        auto from_lanes=origins(from),to_lanes=origins(to);
        for(auto [lane,distance]:from_lanes) {
            first.push_back(int(edges.size()+extras.size()));
            extras.push_back(partial(lane,distance,edges[lane].data.length,start,edges[lane].data.destination));
        }
        for(auto [lane,distance]:to_lanes) {
            last.push_back(int(edges.size()+extras.size()));
            extras.push_back(partial(lane,0,distance,edges[lane].data.source,goal));
        }
        for(auto [source,sd]:from_lanes) for(auto [destination,dd]:to_lanes)
            if(source==destination && dd>=sd) {
                direct.push_back(int(edges.size()+extras.size()));
                extras.push_back(partial(source,sd,dd,start,goal));
            }
        double infinity=std::numeric_limits<double>::infinity();
        std::vector<double> best(nodes.size()+2,infinity);
        std::vector<int> previous(nodes.size()+2,-1),via(nodes.size()+2,-1);
        using Item=std::tuple<double,uint64_t,double,int>;
        std::priority_queue<Item,std::vector<Item>,std::greater<Item>> frontier;
        uint64_t sequence=0;
        auto estimate=[&](int node){auto p=node==goal?to.point:(node==start?from.point:nodes[node]);
            return std::hypot(p.x-to.point.x,p.y-to.point.y);};
        best[start]=0;frontier.emplace(estimate(start),sequence++,0,start);
        while(!frontier.empty()) {
            auto [priority,order,cost,node]=frontier.top();frontier.pop();
            (void)priority;(void)order;
            if(cost!=best[node]) continue;
            if(node==goal) {
                SpawnPath path;path.found=true;path.cost=cost;path.extras=extras;
                for(int current=goal;current!=start;current=previous[current])
                    if(via[current]>=0) path.edges.push_back(via[current]);
                std::reverse(path.edges.begin(),path.edges.end());return path;
            }
            auto push=[&](int next,double step,int edge) {
                double candidate=cost+step;
                if(candidate>=best[next]) return;
                best[next]=candidate;previous[next]=node;via[next]=edge;
                frontier.emplace(candidate+estimate(next),sequence++,candidate,next);
            };
            if(node==start) {
                for(int id:first) {auto& edge=extras[id-int(edges.size())];push(edge.data.destination,edge.data.cost,id);}
                if(first.empty()) for(int next:from.outgoing) push(next,0,-1);
                for(int id:direct) {auto& edge=extras[id-int(edges.size())];push(goal,edge.data.cost,id);}
                if(direct.empty() && same) push(goal,0,-1);
            } else {
                for(int edge:adjacency[node]) push(edges[edge].data.destination,edges[edge].data.cost,edge);
                for(int id:last) {auto& edge=extras[id-int(edges.size())];if(edge.data.source==node) push(goal,edge.data.cost,id);}
                if(last.empty()) for(int incoming:to.incoming) if(incoming==node) push(goal,0,-1);
            }
        }
        return {};
    }
};
