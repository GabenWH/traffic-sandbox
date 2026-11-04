#pragma once
#include "engine.h"
#include <cmath>
#include <limits>
#include <memory>
#include <queue>
#include <stdexcept>
#include <tuple>
#include <vector>

// Separate from Engine: a worker can never touch live traffic through this API.
struct RoutingGraph {
    int nodes;
    std::vector<NTRouteEdge> edges;
    std::vector<std::vector<int>> incoming;
    RoutingGraph(int n,const NTRouteEdge* rows,int count):nodes(n) {
        if(n<=0 || count<0 || (count && !rows)) throw std::invalid_argument("invalid routing graph size");
        incoming.resize(n);
        for(int i=0;i<count;++i) {
            auto edge=rows[i];
            if(edge.source<0 || edge.source>=n || edge.destination<0 || edge.destination>=n ||
               !std::isfinite(edge.cost) || edge.cost<0) throw std::invalid_argument("invalid routing edge");
            edges.push_back(edge);incoming[edge.destination].push_back(i);
        }
    }
};
using RoutingGraphOwner=std::shared_ptr<const RoutingGraph>;

struct RoutingTree {
    RoutingGraphOwner graph;
    std::vector<double> distance;
    std::vector<int> next, root;
    RoutingTree(RoutingGraphOwner g,const int* targets,const double* finals,int count,
                const double* weights,int weight_count):graph(std::move(g)) {
        if(count<=0 || !targets || !finals || (weight_count && (!weights || weight_count!=int(graph->edges.size()))))
            throw std::invalid_argument("invalid routing tree roots or weights");
        for(int i=0;i<weight_count;++i) if(!std::isfinite(weights[i]) || weights[i]<0)
            throw std::invalid_argument("invalid routing weight");
        distance.assign(graph->nodes,std::numeric_limits<double>::infinity());
        next.assign(graph->nodes,-1);root.assign(graph->nodes,-1);
        std::vector<bool> settled(graph->nodes,false);
        using Item=std::tuple<double,int>;
        std::priority_queue<Item,std::vector<Item>,std::greater<Item>> queue;
        for(int i=0;i<count;++i) {
            int node=targets[i];double cost=finals[i];
            if(node<0 || node>=graph->nodes || !std::isfinite(cost) || cost<0)
                throw std::invalid_argument("invalid routing target");
            if(cost<distance[node]) {distance[node]=cost;root[node]=i;queue.emplace(cost,node);}
        }
        while(!queue.empty()) {
            auto [cost,node]=queue.top();queue.pop();
            if(settled[node] || cost!=distance[node]) continue;
            settled[node]=true;
            for(int id:graph->incoming[node]) {
                auto edge=graph->edges[id];
                if(settled[edge.source]) continue;
                double candidate=cost+(weights?weights[id]:edge.cost);
                if(candidate>=distance[edge.source]) continue;
                distance[edge.source]=candidate;next[edge.source]=id;root[edge.source]=root[node];
                queue.emplace(candidate,edge.source);
            }
        }
    }
    int path(const int* sources,const double* initials,int count,int* edges,int capacity,
             int* origin,int* target,double* total) const {
        if(count<=0 || !sources || !initials || !edges || capacity<graph->nodes || !origin || !target || !total)
            throw std::invalid_argument("invalid routing path buffer");
        double best=std::numeric_limits<double>::infinity();int node=-1;*origin=-1;*target=-1;
        for(int i=0;i<count;++i) {
            int from=sources[i];double cost=initials[i];
            if(from<0 || from>=graph->nodes || !std::isfinite(cost) || cost<0)
                throw std::invalid_argument("invalid routing origin");
            double candidate=cost+distance[from];
            if(candidate<best) {best=candidate;node=from;*origin=i;}
        }
        if(node<0) return -2;
        *target=root[node];*total=best;int length=0;
        while(next[node]>=0) {
            if(length>=capacity) throw std::runtime_error("routing tree cycle");
            int edge=next[node];edges[length++]=edge;node=graph->edges[edge].destination;
        }
        return length;
    }
};
