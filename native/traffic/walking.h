#pragma once
#include "spawning.h"

// A world revision owns one immutable snapshot. All query state is stack-local,
// so walking queries may run concurrently without touching the traffic engine.
struct WalkingGraph {
    SpawnGraph graph;
    std::vector<int> reverse;

    static void valid(bool condition,const char* message) {
        if(!condition) throw std::invalid_argument(message);
    }
    static void finite(NTPoint point) {
        valid(std::isfinite(point.x) && std::isfinite(point.y),"nonfinite walking coordinate");
    }
    WalkingGraph(const NTPoint* nodes,int n,const NTWalkEdge* edges,int m,const NTPoint* points,int count) {
        valid(n>=0 && m>=0 && count>=0 && (!n || nodes) && (!m || edges) && (!count || points),"invalid walking graph buffers");
        for(int i=0;i<n;++i) {finite(nodes[i]);graph.nodes.push_back(nodes[i]);}
        graph.adjacency.resize(n);
        for(int i=0;i<m;++i) {
            const auto& input=edges[i];
            valid(input.source>=0 && input.source<n && input.destination>=0 && input.destination<n &&
                  input.point_start>=0 && input.point_count>=2 && input.point_start<=count &&
                  input.point_count<=count-input.point_start && input.reverse>=-1 && input.reverse<m,
                  "invalid walking edge");
            SpawnEdge edge{};
            for(int j=0;j<input.point_count;++j) {
                auto point=points[input.point_start+j];finite(point);edge.points.push_back(point);
            }
            // Geometric edge costs make the Euclidean A* estimate admissible.
            auto a=edge.points.front(),b=edge.points.back();
            valid(std::hypot(a.x-nodes[input.source].x,a.y-nodes[input.source].y)<1e-6 &&
                  std::hypot(b.x-nodes[input.destination].x,b.y-nodes[input.destination].y)<1e-6,
                  "walking geometry does not meet nodes");
            edge.data.source=input.source;edge.data.destination=input.destination;
            edge.data.key=i;edge.data.kind=1;
            edge.data.cost=edge.data.length=SpawnGraph::length(edge.points);
            graph.edges.push_back(std::move(edge));
            graph.adjacency[input.source].push_back(i);reverse.push_back(input.reverse);
        }
        for(int i=0;i<m;++i) if(reverse[i]>=0) {
            int other=reverse[i];
            valid(reverse[other]==i && edges[i].source==edges[other].destination &&
                  edges[i].destination==edges[other].source &&
                  graph.edges[i].points.size()==graph.edges[other].points.size(),"invalid reverse walking lane");
            const auto& a=graph.edges[i].points;const auto& b=graph.edges[other].points;
            for(size_t j=0;j<a.size();++j)
                valid(a[j].x==b[b.size()-1-j].x && a[j].y==b[b.size()-1-j].y,"reverse walking geometry differs");
        }
    }

    SpawnEndpoint project(NTPoint point) const {
        finite(point);
        double best=std::numeric_limits<double>::infinity();
        SpawnEndpoint result;
        for(size_t i=0;i<graph.edges.size();++i) {
            // Only lanes are eligible for snapping, never junction connectors.
            if(reverse[i]<0 || static_cast<int>(i)>reverse[i]) continue;
            const auto& points=graph.edges[i].points;
            double travelled=0;
            for(size_t j=1;j<points.size();++j) {
                auto a=points[j-1],b=points[j];double dx=b.x-a.x,dy=b.y-a.y;
                double squared=dx*dx+dy*dy,length=std::sqrt(squared);
                if(!squared) continue;
                double fraction=std::clamp(((point.x-a.x)*dx+(point.y-a.y)*dy)/squared,0.0,1.0);
                NTPoint projected{a.x+fraction*dx,a.y+fraction*dy};
                double distance=std::hypot(point.x-projected.x,point.y-projected.y);
                if(distance<best) {
                    best=distance;result.point=projected;result.lane=int(i);
                    result.reverse_lane=reverse[i];result.distance=travelled+fraction*length;
                }
                travelled+=length;
            }
        }
        valid(result.lane>=0,"No pedestrian lanes");
        return result;
    }
};
