// Included inside Engine: lane policy, reservations and route alternatives.
    std::unordered_map<int,NTLane> parallel_lanes;
    std::unordered_map<int,int> key_edges;
    std::map<int,std::vector<int>> lane_groups;
    std::map<std::tuple<int,int,int>,int> lane_alternatives;
    std::unordered_map<int,std::set<std::tuple<int,int,int>>> alternative_users;
    std::map<std::vector<double>,int> compiled_routes;
    std::unordered_map<int,std::map<std::vector<double>,int>::iterator> compiled_route_entries;
    std::map<std::pair<int,int>,std::vector<int>> spawn_choices;
    std::vector<NTLaneChange> lane_events;
    int released_routes_since_sweep=0;

    void forget_route(int id) {
        // A recycled route slot must not inherit any cached alternative from
        // its former occupant, whether that route was the source or target.
        auto users=alternative_users.find(id);
        if(users!=alternative_users.end()) {
            for(const auto& key:users->second) lane_alternatives.erase(key);
            alternative_users.erase(users);
        }
        auto first=lane_alternatives.lower_bound(
            std::make_tuple(id,std::numeric_limits<int>::min(),std::numeric_limits<int>::min()));
        while(first!=lane_alternatives.end() && std::get<0>(first->first)==id) {
            auto references=alternative_users.find(first->second);
            if(references!=alternative_users.end()) {
                references->second.erase(first->first);
                if(references->second.empty()) alternative_users.erase(references);
            }
            first=lane_alternatives.erase(first);
        }
        auto compiled=compiled_route_entries.find(id);
        if(compiled!=compiled_route_entries.end()) {
            compiled_routes.erase(compiled->second);
            compiled_route_entries.erase(compiled);
            for(auto it=spawn_choices.begin();it!=spawn_choices.end();) {
                const auto& options=it->second;
                if(std::find(options.begin(),options.end(),id)!=options.end()) it=spawn_choices.erase(it);
                else ++it;
            }
        }
    }

    void collect_unused_alternatives() {
        // Route IDs may be cached by other lane alternatives, forming cycles.
        // Mark from public routes, live vehicles and spawn choices, then free
        // only private alternatives unreachable from any of those roots.
        released_routes_since_sweep=0;
        std::vector<unsigned char> reachable(routes.size(),0);
        std::vector<int> pending;
        auto mark=[&](int id) {
            if(id>=0 && size_t(id)<routes.size() && routes[size_t(id)].length>0 && !reachable[size_t(id)]) {
                reachable[size_t(id)]=1;pending.push_back(id);
            }
        };
        for(size_t i=0;i<routes.size();++i)
            if(!routes[i].private_lane_alternative) mark(int(i));
        for(const auto& pair:cars) mark(pair.second->s.route);
        for(const auto& vehicle:retired) mark(vehicle->s.route);
        for(const auto& pair:spawn_choices) for(int id:pair.second) mark(id);
        while(!pending.empty()) {
            int id=pending.back();pending.pop_back();
            auto it=lane_alternatives.lower_bound(
                std::make_tuple(id,std::numeric_limits<int>::min(),std::numeric_limits<int>::min()));
            for(;it!=lane_alternatives.end() && std::get<0>(it->first)==id;++it) mark(it->second);
        }
        std::vector<int> unused;
        for(size_t i=0;i<routes.size();++i)
            if(routes[i].length>0 && routes[i].private_lane_alternative && !reachable[i]) unused.push_back(int(i));
        for(int id:unused) {
            forget_route(id);routes[size_t(id)]=Route{};free_routes.push_back(id);
        }
    }

    static double project(const std::vector<NTPoint>& points,NTPoint p) {
        double best=inf,at=0,walked=0;
        for(size_t i=1;i<points.size();++i) {
            auto a=points[i-1],b=points[i];double dx=b.x-a.x,dy=b.y-a.y,len=std::hypot(dx,dy);
            if(len<=0) continue;
            double t=clamp(((p.x-a.x)*dx+(p.y-a.y)*dy)/(len*len),0,1);
            double d=std::hypot(p.x-a.x-t*dx,p.y-a.y-t*dy);
            if(d<best){best=d;at=walked+t*len;} walked+=len;
        }
        return at;
    }
    std::vector<int> itinerary(const Route& r,size_t start=0) {
        std::vector<int> result;
        for(size_t i=start;i<r.sections.size();++i) {
            int key=r.sections[i].key;auto edge=key_edges.find(key);
            if(edge==key_edges.end() || graph.edges[edge->second].data.kind!=1) continue;
            auto lane=parallel_lanes.find(key);
            result.push_back(lane==parallel_lanes.end()?-key-1:lane->second.group);
        }
        return result;
    }
    int alternate(Car& c,size_t section,int target) {
        auto cache_key=std::make_tuple(c.s.route,int(section),target);
        auto cached=lane_alternatives.find(cache_key);if(cached!=lane_alternatives.end()) return cached->second;
        const auto original=route(c); // compile_path may grow routes
        int result=-1;
        auto end=key_edges.find(original.sections.back().key);
        if(end!=key_edges.end()) {
            SpawnEndpoint from,to;auto& lane=graph.edges[parallel_lanes.at(target).edge];
            from.point=lane.points.front();from.outgoing={lane.data.source};
            auto& last=graph.edges[end->second];
            double stop=original.sections.back().offset+original.sections.back().end-original.sections.back().start;
            // Preserve an exact mid-lane destination. Full lane endpoints use ordinary graph nodes.
            if(last.data.kind==1 && stop<last.data.length-1e-6) {
                to.lane=end->second;to.distance=stop;to.point=SpawnGraph::at(last.points,stop);
            } else {
                to.incoming={last.data.destination};to.point=last.points.back();
                auto terminal=parallel_lanes.find(last.data.key);
                if(original.terminal_flexible && terminal!=parallel_lanes.end()) {
                    to.incoming.clear();
                    for(int key:lane_groups[terminal->second.group])
                        to.incoming.push_back(graph.edges[parallel_lanes.at(key).edge].data.destination);
                }
            }
            auto path=graph.find(from,to);
            if(path.found) {
                int candidate=compile_path(path,original.terminal_flexible,true);
                if(itinerary(routes[candidate])==itinerary(original,section)) result=candidate;
            }
        }
        lane_alternatives[cache_key]=result;
        if(result>=0) alternative_users[result].insert(cache_key);
        return result;
    }
    std::pair<Car*,double> lane_leader(Car& c,int key,double position) {
        Car* best=nullptr;double gap=inf;
        auto inspect=[&](const auto& index) {
            auto found=index.find(key);if(found==index.end()) return;
            const auto& entries=found->second;
            auto first=std::lower_bound(entries.begin(),entries.end(),position,
                [](const Entry& e,double p){return e.position<p;});
            for(auto it=first;it!=entries.end();++it) if(it->car!=&c && it->car->id!=c.id) {
                double g=it->position-position-(it->car->s.length+c.s.length)/2;
                if(g<gap){gap=g;best=it->car;} break;
            }
        };
        inspect(lanes);inspect(obstacle_lanes);
        return {best,gap};
    }
    int ahead_count(Car& c,int key,double position) {
        int count=0;
        auto inspect=[&](const auto& index) {
            auto found=index.find(key);if(found==index.end()) return;
            const auto& entries=found->second;
            auto first=std::lower_bound(entries.begin(),entries.end(),position-1e-6,
                [](const Entry& e,double p){return e.position<p;});
            count+=int(entries.end()-first);
            for(auto it=first;it!=entries.end() && it->position<=position+1e-6;++it)
                if(it->car==&c || it->car->id==c.id) --count;
        };
        inspect(lanes);inspect(obstacle_lanes);
        return count;
    }
    Choice lane_merge_choice(Car& c,int key,double position) {
        Merge observed;observed.distance=0;observed.lateral_duration=3;
        observed.length=c.s.length;observed.cruise=c.cruise;
        double join=position,look=std::max(180.0,8*speed*22/15);
        auto inspect=[&](const auto& index) {
            auto found=index.find(key);
            if(found==index.end()) return;
            const auto& entries=found->second;
            auto first=std::lower_bound(entries.begin(),entries.end(),join-look,
                [](const Entry& e,double p){return e.position<p;});
            for(auto it=first;it!=entries.end() && it->position<=join+look;++it)
                if(it->car!=&c && it->car->id!=c.id)
                    observed.vehicles.push_back({it->car,it->position-join});
        };
        inspect(lanes);inspect(obstacle_lanes);
        // Exactly the same phantom leader, speed matching and merge-style policy
        // as ramps/lane drops. Only the observation's joining ruler differs.
        return merge_choice(c,observed,c.cruise);
    }
    void geometry(Car& c) {
        route_geometry(c);
        if(c.lane_source<0) return;
        auto found=key_edges.find(c.lane_source);if(found==key_edges.end()) return;
        const auto& points=graph.edges[found->second].points;
        auto source=SpawnGraph::at(points,c.lane_source_distance);
        double t=clamp(c.lane_elapsed/c.lane_duration,0,1),blend=t*t*(3-2*t);
        auto destination=c.position;
        c.position={source.x+(destination.x-source.x)*blend,source.y+(destination.y-source.y)*blend};
        double rate=6*t*(1-t)/c.lane_duration;
        double hx=c.heading.x*std::max(c.s.speed,1.0)+(destination.x-source.x)*rate;
        double hy=c.heading.y*std::max(c.s.speed,1.0)+(destination.y-source.y)*rate;
        double len=std::hypot(hx,hy);if(len>0) c.heading={hx/len,hy/len};
    }
    void change_lane(Car& c,int key,double position,int new_route) {
        auto occupied=occupancy(c);int old_key=occupied.first;
        const double previous_distance=c.s.distance;
        c.lane_source=old_key;c.lane_target=key;c.lane_source_distance=occupied.second;
        c.lane_elapsed=0;c.lane_duration=3;c.lane_cooldown=5;
        c.lane_signal=parallel_lanes.at(key).rank>parallel_lanes.at(old_key).rank?1:2;
        c.s.route=new_route;c.s.distance=position;
        c.geometry=c.control_cursor=c.route_cursor=c.round_cursor=c.section_cursor=c.section_first=c.section_stop=0;
        c.s.dwell=0;c.s.entry=-1;c.yellow_movement=-1;c.yellow_go=false;
        erase_arrival(c);waiting.erase(c.s.handle);
        if(winner==c.s.handle) {winner=winner_connection=-1;hard=false;}
        geometry(c);c.cruise=cruise(c);
        lane_events.push_back({c.s.handle,c.s.route,old_key,key,c.lane_source_distance,0,3,5,
                               previous_distance,position});
        auto& target=lanes[key];target.push_back({&c,position,0});
        std::stable_sort(target.begin(),target.end(),[](const Entry& a,const Entry& b){return a.position<b.position;});
    }
    void select_lanes(const std::vector<Car*>& order,double dt) {
        if(parallel_lanes.empty()) return;
        for(Car* cp:order) {
            auto& c=*cp;c.lane_desired=inf;c.lane_phantom.clear();c.lane_reason.clear();
            c.lane_cooldown=std::max(0.0,c.lane_cooldown-dt);
            if(c.lane_source>=0) {
                auto occupied=occupancy(c);
                auto choice=lane_merge_choice(c,occupied.first,occupied.second);
                c.lane_desired=choice.desired;c.lane_phantom=choice.phantom;c.lane_reason=choice.reason;
                continue;
            }
            if(c.lane_cooldown>0 || !c.claims.empty() || !c.signal_occupancy.empty()) continue;
            auto occupied=occupancy(c);auto lane=parallel_lanes.find(occupied.first);
            if(lane==parallel_lanes.end()) continue;
            const auto section=route(c).sections[c.section_cursor];
            double available=section.end-c.s.distance-c.s.length/2;
            if(c.s.distance-section.start<c.s.length/2 || available<std::max(35.0,c.s.speed*3.5)) continue;
            auto leader=lane_leader(c,occupied.first,occupied.second);
            int current_count=ahead_count(c,occupied.first,occupied.second);
            bool passing=leader.first && leader.first->s.speed+2<c.cruise && leader.second<std::max(128.0,c.s.speed*4);
            int best=-1,best_route=-1,best_count=current_count;double best_position=0;
            for(int key:lane_groups[lane->second.group]) {
                auto candidate=parallel_lanes.at(key);
                if(std::abs(candidate.rank-lane->second.rank)!=1) continue;
                const auto& points=graph.edges[candidate.edge].points;
                double position=project(points,c.position);
                int count=ahead_count(c,key,position);
                auto ahead=lane_leader(c,key,position);
                bool queue=leader.first && leader.first->s.speed<5 && count<current_count;
                bool pass=passing && candidate.rank>lane->second.rank &&
                    (!ahead.first || ahead.second>leader.second+30);
                bool keep_right=candidate.rank<lane->second.rank && count<=current_count &&
                    (!ahead.first || ahead.second>std::max(128.0,c.s.speed*4));
                if(!(queue || pass || keep_right)) continue;
                if(best>=0 && count>=best_count) continue;
                int alternative=alternate(c,c.section_cursor,key);if(alternative<0) continue;
                if(routes[alternative].sections.empty() || routes[alternative].sections.front().key!=key) continue;
                if(routes[alternative].sections.front().end-position<c.s.length/2+std::max(35.0,c.s.speed*3.5)) continue;
                auto choice=lane_merge_choice(c,key,position);
                c.lane_desired=choice.desired;c.lane_phantom=choice.phantom;c.lane_reason=choice.reason;
                if(!choice.clear) continue;
                best=key;best_count=count;best_position=position;best_route=alternative;
            }
            if(best>=0) change_lane(c,best,best_position,best_route);
        }
    }
    int choose_spawn_route(int source,int destination) {
        int original=find_route(source,destination);if(original<0 || parallel_lanes.empty()) return original;
        auto cache_key=std::make_pair(source,destination);
        auto found=spawn_choices.find(cache_key);
        if(found==spawn_choices.end()) {
            std::vector<int> candidates;
            auto wanted=itinerary(routes[original]);
            for(int node:graph.endpoints[source].outgoing) {
                auto from=graph.endpoints[source];from.outgoing={node};
                auto path=graph.find(from,graph.endpoints[destination]);if(!path.found) continue;
                int candidate=compile_path(path,true,true);
                if(itinerary(routes[candidate])==wanted) candidates.push_back(candidate);
            }
            found=spawn_choices.emplace(cache_key,std::move(candidates)).first;
        }
        return best_entry_route(found->second,original,14);
    }
    int best_entry_route(const std::vector<int>& candidates,int original,double length) {
        index_current();
        int best=original;auto score=std::make_tuple(INT32_MAX,INT32_MAX);
        for(int candidate:candidates) {
            auto& r=routes[candidate];if(r.sections.empty()) continue;
            auto lane=parallel_lanes.find(r.sections.front().key);if(lane==parallel_lanes.end()) continue;
            int count=int(lanes[lane->first].size());
            auto stopped=obstacle_lanes.find(lane->first);
            if(stopped!=obstacle_lanes.end()) count+=int(stopped->second.size());
            auto value=std::make_tuple(count,lane->second.rank);
            // A car's body at the entry blocks this lane, independent of queue depth.
            bool blocked=false;
            for(auto entry:lanes[lane->first]) if(entry.position<22+(entry.car->s.length+length)/2) {blocked=true;break;}
            if(!blocked && stopped!=obstacle_lanes.end())
                for(auto entry:stopped->second) if(entry.position<22+(entry.car->s.length+length)/2) {blocked=true;break;}
            if(!blocked && value<score){score=value;best=candidate;}
        }
        return best;
    }

    int choose_external_entry(int original,double length) {
        const auto& r=routes.at(original);
        if(r.sections.empty() || !parallel_lanes.count(r.sections.front().key)) return original;
        auto lane=parallel_lanes.at(r.sections.front().key);
        Car candidate;candidate.s.route=original;
        std::vector<int> choices{original};
        for(int key:lane_groups[lane.group]) if(key!=lane.key) {
            int other=alternate(candidate,0,key);if(other>=0) choices.push_back(other);
        }
        return best_entry_route(choices,original,length);
    }
