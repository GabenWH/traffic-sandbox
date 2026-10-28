#include "engine.h"
#include "spawning.h"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <limits>
#include <map>
#include <memory>
#include <iomanip>
#include <sstream>
#include <set>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>

namespace {
constexpr double inf = std::numeric_limits<double>::infinity();
thread_local std::string error;
void require(bool ok, const char* message) { if (!ok) throw std::invalid_argument(message); }
void check_finite(double x) { require(std::isfinite(x), "nonfinite native input"); }
double clamp(double x, double lo, double hi) { return std::max(lo, std::min(hi, x)); }
struct Route {
    std::vector<NTPoint> points;
    std::vector<NTSection> sections;
    std::vector<NTMovement> movements;
    std::vector<double> ends;
    double length = 0;
    std::vector<int> edge_ids;
    double cost=0;
};
struct PedestrianLane {
    std::vector<NTPoint> points;
    std::vector<double> ends;
    double length=0, crossing=-1;
    NTPoint crossing_point{};
};
struct Pedestrian {
    int id=0, lane=0;
    size_t segment=0;
    double distance=0, speed=0;
    NTPoint position{};
    bool passed=false, waiting=false;
};
struct Car {
    NTSpawn s{};
    std::string id, reason, phantom;
    std::vector<int> claims;
    std::vector<int> signal_occupancy;
    int latest_claim=-1;
    int yellow_movement=-1;
    bool yellow_go=false;
    double cruise=0;
    NTPoint position{}, heading{1,0};
    size_t geometry=0, control_cursor=0, route_cursor=0, round_cursor=0, section_cursor=0;
    size_t section_first=0, section_stop=0;
    int order=0;
};
struct Arrival { int connection; double time; };
struct Entry { Car* car; double position; int segment; };
struct MergeVehicle { Car* car; double position; };
struct Reservation { double distance, time; };
struct Merge {
    double distance=0, length=0, cruise=0;
    std::vector<MergeVehicle> vehicles;
    std::vector<Reservation> reservations;
};
struct Choice { double desired=0, entry=0; bool clear=true; std::string reason, phantom; };
struct Decision { double desired=0, entry=-1; int state=0; bool stop=false, claim=false, signal_entry=false; std::string reason; };
struct Intent {
    Car* car;
    int movement=-1;
    bool claimed=false, merge=false, priority=false, contender=false;
    double stop_distance=-1, lead_gap=inf, travel=0, next_speed=0;
    Car* leader=nullptr;
    Decision decision;
};
struct Candidate { Car* car; int connection; bool clear; };

class Engine {
public:
    double speed, time=0, stall=0, threshold=5;
    int winner=-1, winner_connection=-1, admission_order=0;
    bool hard=false;
    std::vector<NTConnection> connections;
    std::unordered_map<uint64_t,unsigned char> relations;
    std::vector<std::vector<int>> signal_blocked_by_occupant;
    std::vector<std::vector<int>> signal_entry_blocked_by_occupant;
    std::vector<int> signal_block_counts, signal_entry_block_counts;
    std::vector<unsigned char> signal_aspects;
    std::vector<Route> routes;
    std::vector<PedestrianLane> pedestrian_lanes;
    std::vector<Pedestrian> pedestrians;
    std::unordered_map<int,size_t> pedestrian_indices;
    std::vector<NTPedestrianState> pedestrian_output, pedestrian_completed;
    int pedestrian_waits=0;
    std::map<int,std::unique_ptr<Car>> cars;
    std::map<int,Arrival> arrivals;
    std::map<int,std::vector<int>> external_claims;
    std::map<int,double> waiting;
    std::unordered_map<int,std::vector<Entry>> lanes;
    double max_vehicle_length=0;
    std::vector<NTState> output;
    std::vector<NTState> completed;
    std::vector<std::unique_ptr<Car>> retired; // completed strings valid until next step
    SpawnGraph graph;
    SpawnRandom random;
    bool rng_ready=false,index_dirty=true;
    std::map<std::pair<int,int>,int> spawn_routes;
    std::vector<int> sources;
    std::vector<double> source_times;
    double interval=1.5;
    int cap=60,next_handle=0;
    int64_t spawned_count=0;
    std::vector<NTGenerated> generated;
    std::vector<NTBookkeeping> bookkeeping;
    bool trace_enabled=false;
    std::vector<NTTrace> trace;
    std::vector<int> trace_vehicles;
    bool profile_enabled=false;
    NTProfile profile{};
    explicit Engine(double v):speed(v) { check_finite(v); require(v>0,"speed must be positive"); }
    Car& car(int h) { auto it=cars.find(h); require(it!=cars.end(),"unknown vehicle"); return *it->second; }
    Car& shared_car(int h) {
        auto it=cars.find(h);if(it!=cars.end()) return *it->second;
        for(auto& c:retired) if(c->s.handle==h) return *c;
        throw std::invalid_argument("unknown shared vehicle");
    }
    Route& route(Car& c) { return routes.at(static_cast<size_t>(c.s.route)); }
    bool has(Car& c,int m) { return std::find(c.claims.begin(),c.claims.end(),m)!=c.claims.end(); }
    bool occupies_signal(Car& c,int m) {
        return std::find(c.signal_occupancy.begin(),c.signal_occupancy.end(),m)!=c.signal_occupancy.end();
    }
    static uint64_t relation_key(int a,int b) {return (uint64_t(uint32_t(a))<<32)|uint32_t(b);}
    bool conflict(int a,int b) { auto it=relations.find(relation_key(a,b));return it!=relations.end() && (it->second&1); }
    bool yields(int a,int b) { auto it=relations.find(relation_key(a,b));return it!=relations.end() && (it->second&2); }
    void release(Car& c,int m) { c.claims.erase(std::remove(c.claims.begin(),c.claims.end(),m),c.claims.end()); c.latest_claim=c.claims.empty()?-1:c.claims.back(); }
    void claim(Car& c,int m) { if(!has(c,m)) c.claims.push_back(m); c.latest_claim=c.claims.back(); arrivals.erase(c.s.handle); }
    bool blocked_by_claims(Car& c,int m) {
        for(const auto& owner:external_claims)
            for(int other:owner.second) if(conflict(m,other)) return true;
        for(auto& pair:cars) if(pair.second.get()!=&c)
            for(int other:pair.second->claims) if(conflict(m,other)) return true;
        return false;
    }
    bool same_approach(int a,int b) const {
        const auto& x=connections.at(a);const auto& y=connections.at(b);
        return x.intersection==y.intersection && std::abs(x.px-y.px)<1e-6 &&
            std::abs(x.py-y.py)<1e-6 && std::abs(x.hx-y.hx)<1e-6 && std::abs(x.hy-y.hy)<1e-6;
    }
    void rebuild_signal_conflicts() {
        const size_t n=connections.size();
        signal_blocked_by_occupant.assign(n,{});
        signal_entry_blocked_by_occupant.assign(n,{});
        signal_block_counts.assign(n,0);
        signal_entry_block_counts.assign(n,0);
        if(signal_aspects.size()!=n) signal_aspects.assign(n,0);
        for(const auto& relation:relations) {
            if(!(relation.second&1)) continue;
            int candidate=static_cast<int>(relation.first>>32);
            int occupant=static_cast<int>(uint32_t(relation.first));
            if(occupant<0 || static_cast<size_t>(occupant)>=n ||
                candidate<0 || static_cast<size_t>(candidate)>=n || connections[occupant].control!=2) continue;
            signal_blocked_by_occupant[occupant].push_back(candidate);
            if(!same_approach(candidate,occupant)) signal_entry_blocked_by_occupant[occupant].push_back(candidate);
        }
        for(size_t i=0;i<n;++i) if(connections[i].control!=2) signal_aspects[i]=0;
        for(auto& pair:cars) for(int movement:pair.second->signal_occupancy)
            for(int blocked:signal_blocked_by_occupant[movement]) ++signal_block_counts[blocked];
        for(auto& pair:cars) for(int movement:pair.second->signal_occupancy)
            for(int blocked:signal_entry_blocked_by_occupant[movement]) ++signal_entry_block_counts[blocked];
    }
    void adjust_signal_occupancy(int movement,int delta) {
        if(movement<0 || static_cast<size_t>(movement)>=signal_blocked_by_occupant.size()) return;
        for(int blocked:signal_blocked_by_occupant[movement]) signal_block_counts[blocked]+=delta;
        for(int blocked:signal_entry_blocked_by_occupant[movement]) signal_entry_block_counts[blocked]+=delta;
    }
    void update_signal_occupancy(Car& c) {
        const double front=c.s.distance+c.s.length/2,rear=c.s.distance-c.s.length/2;
        for(size_t i=0;i<c.signal_occupancy.size();) {
            int occupied=c.signal_occupancy[i];
            bool overlaps=std::any_of(route(c).movements.begin(),route(c).movements.end(),
                [occupied,front,rear](const NTMovement& movement) {
                    return movement.connection==occupied && front>movement.start+1e-8 && rear<movement.end;
                });
            if(!overlaps) {
                adjust_signal_occupancy(occupied,-1);
                c.signal_occupancy.erase(c.signal_occupancy.begin()+static_cast<std::ptrdiff_t>(i));
            } else ++i;
        }
        for(const auto& m:route(c).movements) {
            if(connections[m.connection].control==2 && front>m.start+1e-8 && rear<m.end &&
                !occupies_signal(c,m.connection)) {
                c.signal_occupancy.push_back(m.connection);
                adjust_signal_occupancy(m.connection,1);
            }
        }
    }
    bool blocked(Car& c,int m) {
        if(blocked_by_claims(c,m)) return true;
        int own=0;
        for(int occupied:c.signal_occupancy) if(conflict(m,occupied)) ++own;
        return signal_block_counts.size()>static_cast<size_t>(m) && signal_block_counts[m]>own;
    }
    bool can_enter_signal(Car& c,int m) {
        if(blocked_by_claims(c,m)) return false;
        int own=0;
        for(int occupied:c.signal_occupancy)
            if(conflict(m,occupied) && !same_approach(m,occupied)) ++own;
        return signal_entry_block_counts.size()>static_cast<size_t>(m) &&
            signal_entry_block_counts[m]<=own;
    }
    auto key(Car& c, const Arrival& a) {
        auto& con=connections[a.connection];
        double angle=std::fmod(std::atan2(con.hx,-con.hy)+2*std::acos(-1.0),2*std::acos(-1.0));
        return std::make_tuple(std::nearbyint(a.time*1e6)/1e6,angle,c.id);
    }
    bool can_claim(Car& c,int m) {
        auto own=arrivals.find(c.s.handle);
        if(own==arrivals.end() || own->second.connection!=m || blocked(c,m)) return false;
        std::vector<std::pair<Car*,Arrival>> group;
        for(auto& pair:arrivals) if(connections[pair.second.connection].intersection==connections[m].intersection)
            group.push_back({&car(pair.first),pair.second});
        if(connections[m].control==1) {
            Car* best=&c; Arrival best_a=own->second;
            for(auto& a:group) if(conflict(m,a.second.connection) && key(*a.first,a.second)<key(*best,best_a)) {
                best=a.first; best_a=a.second;
            }
            return best==&c;
        }
        bool own_dep=false, any_free=false;
        Car* best=&c; Arrival best_a=own->second;
        for(auto& a:group) {
            bool dep=false;
            for(auto& b:group) if(a.first!=b.first && conflict(a.second.connection,b.second.connection) &&
                (b.second.time<a.second.time-0.75 || (std::abs(b.second.time-a.second.time)<=0.75 && yields(a.second.connection,b.second.connection)))) dep=true;
            if(a.first==&c) own_dep=dep;
            if(!dep) any_free=true;
            if(key(*a.first,a.second)<key(*best,best_a)) {best=a.first;best_a=a.second;}
        }
        return !own_dep || (!any_free && best==&c);
    }
    bool can_approach(Car& c,int m) {
        if(blocked(c,m)) return false;
        for(auto& pair:arrivals) if(pair.first!=c.s.handle && conflict(m,pair.second.connection)) return false;
        return true;
    }
    int next_control(Car& c) {
        auto& ms=route(c).movements;
        while(c.control_cursor<ms.size() && ms[c.control_cursor].end<=c.s.distance-c.s.length/2) ++c.control_cursor;
        for(size_t i=c.control_cursor;i<ms.size();++i) {
            auto& m=ms[i]; auto& con=connections[m.connection];
            if(con.role==3 || con.maneuver==3) continue;
            bool committed=con.control==2?occupies_signal(c,m.connection):has(c,m.connection);
            if(!(committed && c.s.distance+c.s.length/2>=m.start)) return static_cast<int>(i);
        }
        return -1;
    }
    int next_route(Car& c) {
        auto& ms=route(c).movements;
        while(c.route_cursor<ms.size() && ms[c.route_cursor].end<=c.s.distance) ++c.route_cursor;
        return c.route_cursor<ms.size()?static_cast<int>(c.route_cursor):-1;
    }
    std::unordered_map<int,double> key_speeds;
    double cruise(Car& c) {
        double mph=c.s.cap<0?speed:std::min(speed,c.s.cap), v=mph*22/15;
        auto& sections=route(c).sections;
        // Road limits share the canonical occupancy keys for all vehicle types.
        auto first=std::upper_bound(sections.begin(),sections.end(),c.s.distance,
            [](double distance,const NTSection& section){return distance<section.end;});
        for(auto it=first;it!=sections.end();++it) {
            auto& section=*it;
            if(section.start-c.s.distance>v*v/48) break;
            auto limit=key_speeds.find(section.key);
            if(limit==key_speeds.end()) continue;
            double road=limit->second*22/15;
            double ahead=std::max(0.0,section.start-c.s.distance);
            v=std::min(v,std::sqrt(road*road+48*ahead));
        }
        auto& ms=route(c).movements;
        while(c.round_cursor<ms.size() && ms[c.round_cursor].end<=c.s.distance-c.s.length/2) ++c.round_cursor;
        for(size_t i=c.round_cursor;i<ms.size();++i) {
            auto& con=connections[ms[i].connection];
            if(con.role) {
                double d=con.role==3?0:std::max(0.0,ms[i].start-c.s.distance-c.s.length/2);
                double curve=std::min(mph,12.0)*22/15;
                return std::min(v,std::sqrt(curve*curve+48*d));
            }
        }
        return v;
    }
    void geometry(Car& c) {
        auto& r=route(c); double d=c.s.distance;
        while(c.geometry<r.ends.size() && r.ends[c.geometry]<d) ++c.geometry;
        // Match reference subtraction at rounded corners.
        bool boundary=(c.geometry>0 && std::abs(d-r.ends[c.geometry-1])<=1e-8) ||
            (c.geometry<r.ends.size() && std::abs(d-r.ends[c.geometry])<=1e-8);
        if(boundary) {
            NTPoint last{1,0};
            for(size_t i=1;i<r.points.size();++i) {
                auto a=r.points[i-1],b=r.points[i]; double len=std::hypot(b.x-a.x,b.y-a.y);
                if(len==0) continue;
                last={(b.x-a.x)/len,(b.y-a.y)/len};
                if(d<=len) {double f=d/len;c.position={a.x+(b.x-a.x)*f,a.y+(b.y-a.y)*f};c.heading=last;return;}
                d-=len;
            }
            c.position=r.points.back(); c.heading=last; return;
        }
        size_t i=std::min(c.geometry,r.ends.size()-1);
        auto a=r.points[i],b=r.points[i+1]; double len=r.ends[i]-(i?r.ends[i-1]:0);
        c.heading={(b.x-a.x)/len,(b.y-a.y)/len};
        double local=d-(i?r.ends[i-1]:0);
        c.position={a.x+c.heading.x*local,a.y+c.heading.y*local};
    }
    std::pair<int,double> occupancy(Car& c) {
        auto& ss=route(c).sections;
        while(c.section_cursor<ss.size()) {
            auto& s=ss[c.section_cursor];
            if(c.s.distance<s.end || s.end==route(c).length)
                return {s.key,s.offset+clamp(c.s.distance-s.start,0,s.end-s.start)};
            ++c.section_cursor;
        }
        return {-1,0};
    }
    void index(const std::vector<Car*>& order) {
        // Entries persist across ticks; only section membership changes.
        std::unordered_map<int,std::vector<Entry>> additions;
        max_vehicle_length=0;
        for(Car* cp:order) {
            auto& c=*cp; auto& ss=route(c).sections;
            max_vehicle_length=std::max(max_vehicle_length,c.s.length);
            double low=c.s.distance-c.s.length/2-22,high=c.s.distance+c.s.length/2;
            while(c.section_first<ss.size() && ss[c.section_first].end<low) ++c.section_first;
            while(c.section_stop<ss.size() && ss[c.section_stop].start<=high) ++c.section_stop;
            int shadow=-1;
            int occupied_connection=!c.claims.empty()?c.claims.back():
                (!c.signal_occupancy.empty()?c.signal_occupancy.back():-1);
            if(occupied_connection>=0) {
                int con=occupied_connection, target=connections[con].target;
                if(target>=0) for(auto& m:route(c).movements) if(m.connection==con) {
                    if(high>=m.start && m.end-22<=high && high<m.end)
                        for(size_t i=c.section_stop;i<ss.size() && ss[i].start<=m.end+1e-8;++i)
                            if(std::abs(ss[i].start-m.end)<1e-8 && ss[i].key==target) {shadow=static_cast<int>(i);break;}
                    break;
                }
            }
            for(size_t i=c.section_first;i<c.section_stop;++i)
                additions[ss[i].key].push_back({&c,ss[i].offset+c.s.distance-ss[i].start,static_cast<int>(i)});
            if(shadow>=0 && !(static_cast<size_t>(shadow)>=c.section_first && static_cast<size_t>(shadow)<c.section_stop))
                additions[ss[shadow].key].push_back({&c,ss[shadow].offset+c.s.distance-ss[shadow].start,shadow});
        }
        // Retain each lane vector's allocation and ordering where unchanged.
        for(auto& pair:lanes) if(!additions.count(pair.first)) pair.second.clear();
        for(auto& pair:additions) {
            auto& entries=lanes[pair.first];
            entries.assign(pair.second.begin(),pair.second.end());
            auto less=[](const Entry& a,const Entry& b){return std::tie(a.position,a.car->order)<std::tie(b.position,b.car->order);};
            if(!std::is_sorted(entries.begin(),entries.end(),less)) std::stable_sort(entries.begin(),entries.end(),less);
        }
    }
    std::pair<Car*,double> lead(Car& c,double distance,double look=128) {
        Car* best=nullptr; double gap=inf;
        auto& ss=route(c).sections;
        auto first=std::lower_bound(ss.begin(),ss.end(),distance-c.s.length/2,[](auto& s,double d){return s.end<d;});
        for(auto it=first;it!=ss.end();++it) {
            auto& s=*it; if(s.start>distance+look) break;
            auto found=lanes.find(s.key); if(found==lanes.end()) continue;
            auto& entries=found->second;
            auto pos=std::lower_bound(entries.begin(),entries.end(),s.offset+distance-s.start-1e-8,
                [](auto& e,double p){return e.position<p;});
            Car* local=nullptr; double local_gap=inf; int order=0;
            for(;pos!=entries.end();++pos) {
                auto& e=*pos; double center=s.start+e.position-s.offset;
                // Lane entries are ordered by position. Once even the longest
                // vehicle cannot overlap the requested lookahead, later cars
                // cannot be leaders either. This avoids walking an entire
                // downstream queue for every follower.
                if(center>distance+look+(c.s.length+max_vehicle_length)/2) break;
                if(e.car==&c || center<distance) continue;
                double g=center-distance-(e.car->s.length+c.s.length)/2;
                if(g<=look && (g<local_gap || (g==local_gap && e.car->order<order))) {
                    local=e.car;local_gap=g;order=e.car->order;
                }
            }
            if(local && local_gap<gap) {best=local;gap=local_gap;}
        }
        return {best,gap};
    }
    static double arrival(double distance,double speed,double desired) {
        if(distance<=0) return 0;
        if(desired<=0.01) return inf;
        double a=desired>=speed?10:-24, t=(desired-speed)/a, d=(speed+desired)*t/2;
        if(distance<=d) return (std::sqrt(std::max(0.0,speed*speed+2*a*distance))-speed)/a;
        return t+(distance-d)/desired;
    }
    Merge observe_merge(Car& c,const NTMovement& m,const std::vector<Car*>& order) {
        Merge result;result.distance=std::max(0.0,m.end-c.s.distance);result.length=c.s.length;result.cruise=c.cruise;
        auto& con=connections[m.connection];
        double vmax=c.s.speed;for(Car* other:order) vmax=std::max(vmax,other->s.speed);
        double look=std::max(180.0,8*vmax);
        std::vector<NTSection> downstream;
        for(auto& s:route(c).sections) if(s.start>=m.end-1e-8 && s.start<=m.end+look) downstream.push_back(s);
        for(Car* op:order) {
            auto& o=*op; if(&o==&c) continue;
            if(o.s.entry>=0) for(auto& om:route(o).movements) {
                auto& oc=connections[om.connection];
                if(oc.target<0 || o.s.distance+o.s.length/2<om.start || o.s.distance-o.s.length/2>=om.end) continue;
                for(auto& s:downstream) if(s.key==oc.target) {
                    result.reservations.push_back({s.start-m.end,arrival(om.end+o.s.length/2-o.s.distance,o.s.speed,o.s.entry)});break;
                }
            }
            bool waiting_merge=false;
            for(auto& om:route(o).movements) if(connections[om.connection].intersection==con.intersection &&
                connections[om.connection].target>=0 && o.s.distance+o.s.length/2<om.start) {waiting_merge=true;break;}
            if(waiting_merge) continue;
            double position=inf;
            for(auto& s:route(o).sections) if(s.key==con.target && o.s.distance<=s.start) {position=o.s.distance-s.start;break;}
            if(position==inf) {
                auto occ=occupancy(o);
                if(occ.first>=0) for(auto& s:downstream) if(s.key==occ.first) {position=s.start-m.end+occ.second-s.offset;break;}
            }
            if(std::abs(position)<=look) result.vehicles.push_back({&o,position});
        }
        return result;
    }
    static bool gap(const Merge& m,double speed,double desired,double headway) {
        double begin=arrival(std::max(0.0,m.distance-m.length),speed,desired);
        double finish=arrival(m.distance+m.length/2,speed,desired);
        if(finish==inf) return false;
        for(auto& r:m.reservations) if(arrival(std::max(0.0,m.distance+r.distance-m.length),speed,std::max(desired,m.cruise))<r.time+headway) return false;
        for(auto& v:m.vehicles) {
            auto& o=*v.car; double allowance=(m.length+o.s.length)/2+4;
            if(v.position+o.s.speed*begin>=allowance+headway*desired) continue;
            double cap=std::max({o.s.speed,o.cruise,speed,desired}),accel=std::min(finish,(cap-o.s.speed)/10);
            double travel=o.s.speed*accel+5*accel*accel+cap*(finish-accel);
            if(v.position+travel>-(allowance+headway*cap)) return false;
        }
        return true;
    }
    static Choice merge_choice(Car& c,const Merge& m,double cruise) {
        Choice choice;choice.desired=cruise;choice.entry=cruise;
        if(c.s.style==1) {
            choice.clear=gap(m,c.s.speed,cruise,2);
            if(!choice.clear) choice.reason="waiting for a generous merge gap";
            return choice;
        }
        double progress=clamp(1-m.distance/128,0,1),strength=progress*progress*(3-2*progress);
        double t=arrival(m.distance,c.s.speed,cruise),nearest=inf;
        Car* leader=nullptr;double position=0;
        for(auto& v:m.vehicles) {
            double p=v.position+v.car->s.speed*t;
            if(p>=0 && (!leader || p<nearest)) {nearest=p;leader=v.car;position=v.position;}
        }
        if(leader) {
            choice.phantom=leader->id;
            double g=position+m.distance-(m.length+leader->s.length)/2,wanted=6+0.8*c.s.speed;
            double response=0.8*(g-wanted)+1.2*(leader->s.speed-c.s.speed);
            choice.desired=std::min(cruise,cruise*(1-strength)+std::max(0.0,c.s.speed+response)*strength);
            if(leader->s.speed>0.1) {
                double opening=std::max(0.0,(18+0.8*c.s.speed-position)/leader->s.speed);
                if(opening>0) choice.desired=std::min(choice.desired,std::max(0.0,m.distance-m.length)/opening);
            }
        }
        choice.entry=std::max(choice.desired,std::min(cruise,6.0));
        choice.clear=gap(m,c.s.speed,choice.entry,0.8);
        if(!choice.phantom.empty() && choice.desired<cruise) choice.reason="matching speed behind phantom car";
        if(!choice.clear) choice.reason="yielding until the merge gap opens";
        return choice;
    }
    bool physical_merge(Car& c,const NTMovement& m,const std::vector<Car*>& order) {
        auto obs=observe_merge(c,m,order);
        if(!obs.reservations.empty()) return false;
        for(auto& v:obs.vehicles) if(std::max(v.car->s.speed,v.car->cruise)>0.1 ||
            std::abs(v.position)<(c.s.length+v.car->s.length)/2+4) return false;
        return true;
    }
    bool path_clear(Car& c,int mi,const std::vector<Car*>& order) {
        auto& m=route(c).movements[mi];
        if(blocked(c,m.connection) || lead(c,c.s.distance).second<4 || lead(c,m.end).second<4) return false;
        if(connections[m.connection].target>=0 && !physical_merge(c,m,order)) return false;
        double end=m.end;
        for(auto& following:route(c).movements) {
            if(following.start<m.end) continue;
            if(following.start-end>=c.s.length+4) break;
            if(blocked(c,following.connection) || lead(c,following.end).second<4) return false;
            if(connections[following.connection].target>=0 && !physical_merge(c,following,order)) return false;
            end=following.end;
        }
        return true;
    }
    int choose(const std::vector<Candidate>& cs) {
        if(stall+1e-9<threshold) {winner=winner_connection=-1;hard=false;return -1;}
        if(winner>=0) {
            for(auto& c:cs) if(c.car->s.handle==winner && c.connection==winner_connection) {hard=!c.clear;return c.clear?winner:-1;}
            stall=0;winner=winner_connection=-1;hard=false;return -1;
        }
        const Candidate* best=nullptr;
        for(auto& c:cs) if(c.clear && (!best || waiting[c.car->s.handle]>waiting[best->car->s.handle] ||
            (waiting[c.car->s.handle]==waiting[best->car->s.handle] && c.car->id<best->car->id))) best=&c;
        hard=!cs.empty() && !best;
        if(!best) return -1;
        winner=best->car->s.handle;winner_connection=best->connection;return winner;
    }
    Decision decide(Car& c,Intent& i,double dt,double cruise_speed,int temporary,const std::vector<Car*>& order) {
        Decision d;d.desired=cruise_speed;std::string following;
        if(i.leader) {
            double available=i.lead_gap-(c.s.style?12+1.2*c.s.speed:6+0.8*c.s.speed);
            if(available<=0) {d.desired=0;following="following queued car";}
            else d.desired=std::min(d.desired,std::sqrt(36*available));
        }
        double physical=d.desired;Choice choice; c.phantom.clear();
        if(i.merge) {
            choice=merge_choice(c,observe_merge(c,route(c).movements[i.movement],order),d.desired);
            d.desired=std::min(d.desired,choice.desired);d.reason=choice.reason;c.phantom=choice.phantom;
        }
        const int movement_connection=i.movement<0?-1:route(c).movements[i.movement].connection;
        const bool signal_movement=movement_connection>=0 && connections[movement_connection].control==2;
        const int aspect=signal_movement && static_cast<size_t>(movement_connection)<signal_aspects.size()
            ?signal_aspects[movement_connection]:0;
        if(signal_movement && aspect==2) {
            if(c.yellow_movement!=movement_connection) {
                c.yellow_movement=movement_connection;
                double distance=std::max(0.0,i.stop_distance);
                c.yellow_go=c.s.speed*c.s.speed/36.0>distance;
            }
        } else {c.yellow_movement=-1;c.yellow_go=false;}
        const bool signal_go=signal_movement && (aspect==1 || (aspect==2 && c.yellow_go));
        const bool signal_stop=signal_movement && !i.claimed && !signal_go;
        bool must_stop=i.movement>=0 && !i.claimed && connections[movement_connection].control==1;
        bool must_yield=i.movement>=0 && !i.claimed && !must_stop && !signal_movement;
        bool inside=false;
        for(auto& m:route(c).movements)
            if((has(c,m.connection) || occupies_signal(c,m.connection)) &&
                m.start<=c.s.distance+c.s.length/2 && c.s.distance-c.s.length/2<m.end) inside=true;
        if(signal_stop && i.stop_distance>=0) {
            c.s.dwell=0;
            double distance=std::max(0.0,i.stop_distance);
            d.desired=std::min(d.desired,std::sqrt(36*distance));
            d.state=3;
            d.reason=aspect==2?"yellow signal":"red signal";
        } else if(signal_movement && signal_go && i.stop_distance>=0) {
            c.s.dwell=0;
            bool ready=!i.merge || (choice.clear && choice.entry>=std::min(6.0,cruise_speed));
            if(i.priority && ready) {d.state=4;d.signal_entry=true;}
            else {
                d.desired=std::min(d.desired,std::sqrt(36*std::max(0.0,i.stop_distance)));
                d.state=3;
                d.reason=i.merge && !choice.clear?choice.reason:
                    (i.decision.reason=="waiting for intersection priority"?
                        "waiting for conflicting traffic":i.decision.reason);
            }
        }
        else if(inside && !(must_stop || must_yield)) {d.state=5;c.s.dwell=0;}
        else if(must_yield && i.stop_distance>=0) {
            c.s.dwell=0;
            bool ready=!i.merge || (choice.clear && choice.entry>=std::min(6.0,cruise_speed));
            if(c.s.handle==temporary) {d.desired=std::min(physical,3.0);d.state=4;d.claim=true;d.reason="breaking soft deadlock";}
            else if(i.priority && ready) {d.state=4;d.claim=true;}
            else {
                d.desired=std::min(d.desired,std::sqrt(36*std::max(0.0,i.stop_distance)));d.state=3;
                d.reason=i.merge && !choice.clear?choice.reason:i.decision.reason;
            }
        } else if(must_stop && i.stop_distance>=0) {
            double distance=std::max(0.0,i.stop_distance);
            if(distance>0.05) {d.state=1;d.desired=std::min(d.desired,std::sqrt(36*distance));c.s.dwell=0;}
            else if(c.s.speed<=0.1) {
                d.desired=0;c.s.dwell+=dt;d.stop=true;
                if(c.s.dwell<0.5) {d.state=2;d.reason="completing stop dwell";}
                else if(i.priority || c.s.handle==temporary) {
                    d.state=4;d.desired=c.s.handle==temporary?std::min(cruise_speed,3.0):cruise_speed;d.claim=true;
                    if(c.s.handle==temporary) d.reason="breaking soft deadlock";
                } else {d.state=3;d.reason="waiting for all-way-stop priority";}
            } else {d.state=1;d.desired=0;}
        } else c.s.dwell=0;
        if(!following.empty()) d.reason=following;
        if(c.s.handle==temporary && !signal_movement) {d.desired=std::min(physical,3.0);d.state=4;d.reason="breaking soft deadlock";}
        if(c.s.handle==winner && temporary<0) {d.desired=0;d.state=3;d.reason="temporary winner path blocked";d.claim=false;}
        d.entry=i.merge?choice.entry:-1;
        if(c.s.handle==temporary && d.claim) d.entry=d.desired;
        else if(c.s.handle==winner && temporary<0) d.entry=-1;
        d.desired=std::max(0.0,d.desired);
        c.s.state=d.state;c.s.desired=d.desired;c.reason=d.reason;c.s.signal=0;
        int ri=next_route(c);
        if(ri>=0) {
            auto& m=route(c).movements[ri];auto& con=connections[m.connection];
            bool suppress=con.role==3 && m.signal_start>=0 && c.s.distance<m.signal_start;
            if(!suppress && (m.start<=c.s.distance || m.start-c.s.distance<=100)) {
                if(con.maneuver==1 || con.maneuver==3) c.s.signal=1;
                if(con.maneuver==2) c.s.signal=2;
            }
        }
        return d;
    }
    NTState state(Car& c,int alive=1) {
        return {c.s.handle,c.s.state,c.s.signal,c.latest_claim,alive,
            c.s.distance,c.s.speed,c.position.x,c.position.y,c.heading.x,c.heading.y,c.s.desired,c.s.dwell,c.s.entry,c.reason.c_str(),c.phantom.c_str(),c.yellow_movement,int(c.yellow_go)};
    }
    static uint64_t cell_key(int x,int y) {return (uint64_t(uint32_t(x))<<32)|uint32_t(y);}
    static NTPedestrianState pedestrian_state(const Pedestrian& p) {
        return {p.id,p.lane,int(p.waiting),p.distance,p.position.x,p.position.y};
    }
    static void pedestrian_position(Pedestrian& p,const PedestrianLane& lane) {
        while(p.segment+1<lane.ends.size() && p.distance>=lane.ends[p.segment]) ++p.segment;
        double start=p.segment?lane.ends[p.segment-1]:0.0;
        double length=lane.ends[p.segment]-start;
        double t=length>0?clamp((p.distance-start)/length,0,1):0;
        auto a=lane.points[p.segment],b=lane.points[p.segment+1];
        p.position={a.x+(b.x-a.x)*t,a.y+(b.y-a.y)*t};
    }
    void advance_pedestrians(double dt) {
        if(pedestrians.empty()) return;
        constexpr double cell=100.0,radius=60.0;
        std::unordered_map<uint64_t,std::vector<NTPoint>> traffic_grid;
        for(const auto& pair:cars) {
            NTPoint position=pair.second->position;
            traffic_grid[cell_key(int(std::floor(position.x/cell)),int(std::floor(position.y/cell)))].push_back(position);
        }
        // A lane's crossing is shared. Inspect nearby vehicles at most once
        // per lane per tick, not once per waiting pedestrian.
        std::vector<signed char> crossing_blocked(pedestrian_lanes.size(),-1);
        for(size_t i=0;i<pedestrians.size();) {
            auto& p=pedestrians[i];const auto& lane=pedestrian_lanes[size_t(p.lane)];
            double next=std::min(lane.length,p.distance+p.speed*dt);
            bool previously_waiting=p.waiting;p.waiting=false;
            if(!p.passed && lane.crossing>=0 && next>=lane.crossing) {
                signed char& cached=crossing_blocked[size_t(p.lane)];
                if(cached<0) {
                    bool blocked=false;int cx=int(std::floor(lane.crossing_point.x/cell)),cy=int(std::floor(lane.crossing_point.y/cell));
                    for(int dx=-1;dx<=1 && !blocked;++dx) for(int dy=-1;dy<=1 && !blocked;++dy) {
                        auto found=traffic_grid.find(cell_key(cx+dx,cy+dy));if(found==traffic_grid.end()) continue;
                        for(auto v:found->second) if(std::hypot(v.x-lane.crossing_point.x,v.y-lane.crossing_point.y)<=radius) {blocked=true;break;}
                    }
                    cached=blocked?1:0;
                }
                if(cached){next=lane.crossing;p.waiting=true;if(!previously_waiting)++pedestrian_waits;}else p.passed=true;
            }
            p.distance=next;pedestrian_position(p,lane);
            if(p.distance+1e-9>=lane.length && !p.waiting) {
                pedestrian_completed.push_back(pedestrian_state(p));pedestrian_indices.erase(p.id);
                if(i+1<pedestrians.size()){pedestrians[i]=pedestrians.back();pedestrian_indices[pedestrians[i].id]=i;}
                pedestrians.pop_back();
            } else ++i;
        }
    }
    void tick(double dt) {
        trace.clear();trace_vehicles.clear();
        time+=dt;
        using ProfileClock=std::chrono::steady_clock;
        auto phase_started=profile_enabled?ProfileClock::now():ProfileClock::time_point{};
        auto mark_phase=[&](double& target) {
            if(profile_enabled) {
                auto now=ProfileClock::now();
                target+=std::chrono::duration<double,std::milli>(now-phase_started).count();
                phase_started=now;
            }
        };
        std::vector<Car*> order; for(auto& p:cars) order.push_back(p.second.get());
        std::sort(order.begin(),order.end(),[](Car* a,Car* b){return a->id<b->id;});
        for(Car* c:order) {update_signal_occupancy(*c);c->cruise=cruise(*c);}
        index(order);
        mark_phase(profile.preparation_ms);
        if(profile_enabled) profile.vehicle_visits+=order.size();
        std::map<std::pair<int,int>,std::pair<Car*,int>> heads;
        for(Car* c:order) {
            int mi=next_control(*c);if(mi<0) continue;
            auto& m=route(*c).movements[mi];auto& con=connections[m.connection];
            if(con.target>=0 && has(*c,m.connection) && c->s.distance+c->s.length/2<m.start) release(*c,m.connection);
            auto k=std::make_pair(con.intersection,m.incoming);
            // incoming connector start is encoded by a separate route field below.
            double distance=connector_start(*c,m)-c->s.length/2-c->s.distance;
            auto found=heads.find(k);
            if(found==heads.end()) heads[k]={c,mi};
            else {
                auto* prev=found->second.first;auto& pm=route(*prev).movements[found->second.second];
                double pd=connector_start(*prev,pm)-prev->s.length/2-prev->s.distance;
                if(std::tie(distance,c->id)<std::tie(pd,prev->id)) found->second={c,mi};
            }
        }
        std::set<int> contenders;std::map<int,Arrival> eligible;
        for(auto& head:heads) {
            Car& c=*head.second.first;auto& m=route(c).movements[head.second.second];auto& con=connections[m.connection];
            if(con.target>=0 || con.control==2) continue;
            double distance=std::max(0.0,m.start-c.s.length/2-c.s.distance);
            if(!has(c,m.connection)) {
                if(distance>std::max(10.0,c.s.speed*0.6)) continue;
                if(con.control==1 && (distance>0.05 || c.s.speed>0.1)) continue;
                eligible.emplace(c.s.handle,Arrival{m.connection,con.control==1?time:time+distance/std::max(c.s.speed,1.0)});
            }
            contenders.insert(c.s.handle);
        }
        for(auto it=arrivals.begin();it!=arrivals.end();) {
            auto e=eligible.find(it->first);
            if(e==eligible.end() || e->second.connection!=it->second.connection) it=arrivals.erase(it);else ++it;
        }
        for(auto& e:eligible) arrivals.emplace(e);
        std::vector<Candidate> candidates;
        for(Car* c:order) {
            bool wait=c->s.speed<=0.1 && (c->s.state==3 || c->s.state==4);
            if(c->s.handle!=winner && !wait) continue;
            int mi=next_control(*c);if(mi<0) continue;
            int con=route(*c).movements[mi].connection;
            if(connections[con].control==2) continue;
            bool clear=(connections[con].target>=0 || contenders.count(c->s.handle)) && c->reason!="following queued car" && path_clear(*c,mi,order);
            candidates.push_back({c,con,clear});
        }
        int temporary=choose(candidates);
        mark_phase(profile.control_ms);
        std::vector<Intent> intents;
        for(Car* cp:order) {
            auto& c=*cp;Intent i{};i.car=&c;i.movement=next_control(c);i.contender=contenders.count(c.s.handle);
            i.decision.reason="waiting for intersection priority";
            if(i.movement>=0) {
                auto& m=route(c).movements[i.movement];auto& con=connections[m.connection];
                i.claimed=has(c,m.connection);i.merge=con.target>=0;
                if(!i.claimed) i.stop_distance=std::max(0.0,m.start-c.s.length/2-c.s.distance);
                if(con.control==2) {
                    int aspect=static_cast<size_t>(m.connection)<signal_aspects.size()?signal_aspects[m.connection]:0;
                    i.priority=(aspect==1 || aspect==2) &&
                        (i.stop_distance>std::max(10.0,c.s.speed*0.6) || can_enter_signal(c,m.connection));
                } else i.priority=i.merge?!blocked(c,m.connection):
                    (con.control!=1 && i.stop_distance>std::max(10.0,c.s.speed*0.6)?can_approach(c,m.connection):can_claim(c,m.connection));
                if(!i.claimed && !i.merge) {
                    if(lead(c,m.end).second<22+c.s.length/2) {i.priority=false;i.decision.reason="waiting for room beyond the junction";}
                    double end=m.end;
                    for(auto& f:route(c).movements) {
                        if(f.start<m.end) continue;
                        if(f.start-end>=c.s.length+4) break;
                        if(connections[f.connection].target>=0) {
                            auto choice=merge_choice(c,observe_merge(c,f,order),cruise(c));
                            if(!choice.clear || blocked(c,f.connection)) {i.priority=false;i.decision.reason="waiting before short link for the next yield";break;}
                        }
                        end=f.end;
                    }
                }
            }
            auto leader=lead(c,c.s.distance);i.leader=leader.first;i.lead_gap=leader.second;
            double v=cruise(c);
            if(c.s.entry>=0) for(auto& m:route(c).movements)
                if((has(c,m.connection) || occupies_signal(c,m.connection)) && connections[m.connection].target>=0 && c.s.distance+c.s.length/2>=m.start && c.s.distance-c.s.length/2<m.end) v=std::min(v,c.s.entry);
            i.decision=decide(c,i,dt,v,temporary,order);
            if(trace_enabled) {
                NTTrace row{c.s.handle,i.movement<0?-1:route(c).movements[i.movement].connection,int(i.priority),int(i.claimed),int(trace_vehicles.size()),0,0,c.s.distance,c.s.speed};
                if(i.merge) {auto observed=observe_merge(c,route(c).movements[i.movement],order);row.reservations=int(observed.reservations.size());
                    for(auto other:observed.vehicles) {trace_vehicles.push_back(other.car->s.handle);}
                    row.vehicle_count=int(observed.vehicles.size());}
                trace.push_back(row);
            }
            intents.push_back(std::move(i));
        }
        mark_phase(profile.decision_ms);
        std::vector<Intent*> requests;for(auto& i:intents) requests.push_back(&i);
        std::sort(requests.begin(),requests.end(),[&](Intent* a,Intent* b){
            auto priority=[&](Intent* i) {
                auto it=arrivals.find(i->car->s.handle);
                if(i->car->s.handle==temporary) return std::make_tuple(0,0.0,0.0,i->car->id);
                if(it!=arrivals.end()) {auto k=key(*i->car,it->second);return std::make_tuple(1,std::get<0>(k),std::get<1>(k),i->car->id);}
                return std::make_tuple(2,0.0,0.0,i->car->id);
            };return priority(a)<priority(b);
        });
        for(auto ip:requests) {
            auto& i=*ip;auto& c=*i.car;
            if(i.decision.claim && i.movement>=0 && (i.merge || i.contender) && std::max(0.0,i.stop_distance)<=std::max(10.0,c.s.speed*0.6)) {
                int con=route(c).movements[i.movement].connection;
                bool allowed=c.s.handle==temporary || i.merge ? !blocked(c,con):can_claim(c,con);
                if(allowed) {
                    claim(c,con);i.claimed=true;
                    if(i.merge) {c.s.entry=i.decision.entry;i.decision.desired=i.decision.entry;}
                } else i.claimed=false;
            }
        }
        for(auto& i:intents) if(i.decision.signal_entry && i.movement>=0) {
            int con=route(*i.car).movements[i.movement].connection;
            if(!can_enter_signal(*i.car,con)) {
                auto& c=*i.car;
                i.decision.signal_entry=false;
                i.decision.desired=std::min(i.decision.desired,
                    std::sqrt(36*std::max(0.0,i.stop_distance)));
                i.decision.state=3;
                i.decision.reason="waiting for conflicting traffic";
                c.s.state=i.decision.state;c.s.desired=i.decision.desired;c.reason=i.decision.reason;
            } else if(i.merge) {
                i.car->s.entry=i.decision.entry;
                i.decision.desired=i.decision.entry;
                i.car->s.desired=i.decision.desired;
            }
        }
        mark_phase(profile.arbitration_ms);
        std::unordered_map<int,double> travels;
        for(auto& i:intents) {
            auto& c=*i.car;double delta=i.decision.desired-c.s.speed,limit=(delta>0?10:24)*dt;
            i.next_speed=c.s.speed+clamp(delta,-limit,limit);i.travel=i.next_speed*dt;
            if(i.movement>=0 && !i.claimed && !i.decision.signal_entry)
                i.travel=std::min(i.travel,std::max(0.0,route(c).movements[i.movement].start-c.s.length/2-c.s.distance));
            travels[c.s.handle]=i.travel;
        }
        for(size_t pass=0;pass<intents.size();++pass) {
            bool changed=false;
            for(auto& i:intents) if(i.leader) {
                double safe=std::max(0.0,i.lead_gap+travels[i.leader->s.handle]-4);
                if(travels[i.car->s.handle]>safe) {travels[i.car->s.handle]=safe;changed=true;}
            }
            if(!changed) break;
        }
        bool entered=false;std::vector<int> done;
        size_t trace_index=0;
        for(auto& i:intents) {
            if(trace_enabled) trace[trace_index++].claimed=int(i.claimed);
            auto& c=*i.car;double travel=travels[c.s.handle];c.s.speed=travel>0?i.next_speed:0;
            // Preserve the baseline multiply/divide order of advance().
            c.s.distance=std::min(route(c).length,c.s.distance+c.s.speed*(c.s.speed>0?travel/c.s.speed:0));
            if(route(c).length-c.s.distance<1e-8) c.s.distance=route(c).length;
            geometry(c);
            update_signal_occupancy(c);
            if(c.s.handle==temporary && i.claimed && i.movement>=0 && c.s.distance+c.s.length/2>=route(c).movements[i.movement].start) entered=true;
            for(auto& m:route(c).movements) if(has(c,m.connection) && c.s.distance-c.s.length/2>=m.end) release(c,m.connection);
            if(c.s.distance>=route(c).length) done.push_back(c.s.handle);
        }
        bool winner_done=std::find(done.begin(),done.end(),winner)!=done.end();
        for(int h:done) {
            auto& c=car(h);c.claims.clear();c.latest_claim=-1;
            for(int movement:c.signal_occupancy) adjust_signal_occupancy(movement,-1);
            c.signal_occupancy.clear();arrivals.erase(h);completed.push_back(state(c,0));
            retired.push_back(std::move(cars.at(h)));cars.erase(h);
        }
        advance_pedestrians(dt);
        std::set<int> current;for(auto& c:candidates) current.insert(c.car->s.handle);
        for(auto it=waiting.begin();it!=waiting.end();) if(!current.count(it->first)) it=waiting.erase(it);else {it->second+=dt;++it;}
        for(int h:current) if(!waiting.count(h)) waiting[h]=dt;
        size_t stopped=0;for(auto& p:cars) if(p.second->s.speed<=0.1) ++stopped;
        bool flowing=!cars.empty() && stopped<0.8*cars.size();
        bool signal_wait=candidates.empty() && std::any_of(connections.begin(),connections.end(),
            [](const NTConnection& c){return c.control==2;});
        if(entered || winner_done || ((flowing || !done.empty() || signal_wait) && winner<0)) {stall=0;winner=winner_connection=-1;hard=false;}else stall+=dt;
        index_dirty=true;
        mark_phase(profile.movement_ms);
        if(profile_enabled) ++profile.ticks;
    }
    void index_current() {
        if(!index_dirty) return;
        std::vector<Car*> order;for(auto& pair:cars) order.push_back(pair.second.get());
        index(order);index_dirty=false;
    }
    void validate_spawn(const NTSpawn& s,const std::string& id) {
        require(!cars.count(s.handle),"duplicate handle");
        for(auto& pair:cars) require(pair.second->id!=id,"duplicate vehicle ID");
        require(s.route>=0 && size_t(s.route)<routes.size(),"unknown route");
        require(routes[s.route].length>0,"degenerate vehicle route");
        for(double v:{s.distance,s.speed,s.length,s.width,s.cap,s.dwell,s.desired,s.entry}) check_finite(v);
        require(s.speed>=0 && s.length>0 && s.width>0 && s.distance>=0 && s.distance<=routes[s.route].length && s.dwell>=0 && s.desired>=0,"invalid vehicle state");
        require((s.style==0 || s.style==1) && s.state>=0 && s.state<=5 && s.signal>=0 && s.signal<=2 && (s.generated==0 || s.generated==1),"invalid driver state");
    }
    void insert(const NTSpawn& s,const std::string& id,const char* reason="",const char* phantom="") {
        validate_spawn(s,id);
        auto c=std::make_unique<Car>();c->s=s;c->id=id;c->reason=reason?reason:"";c->phantom=phantom?phantom:"";c->order=admission_order++;
        c->signal_occupancy.reserve(4);geometry(*c);update_signal_occupancy(*c);cars.emplace(s.handle,std::move(c));index_dirty=true;
    }
    static bool overlaps(const Car& a,const Car& b) {
        double dx=b.position.x-a.position.x,dy=b.position.y-a.position.y;
        for(auto h:{a.heading,b.heading}) for(auto axis:{h,NTPoint{-h.y,h.x}}) {
            double separation=std::abs(dx*axis.x+dy*axis.y);
            auto radius=[&](const Car& c) {return std::abs(c.heading.x*axis.x+c.heading.y*axis.y)*c.s.length/2+
                std::abs(-c.heading.y*axis.x+c.heading.x*axis.y)*c.s.width/2;};
            if(separation>=radius(a)+radius(b)-0.01) return false;
        }
        return true;
    }
    bool admit(const NTSpawn& s,const std::string& id) {
        for(auto& pair:cars) if(pair.second->id==id) return false;
        require(s.route>=0 && size_t(s.route)<routes.size(),"unknown route");
        if(routes[s.route].length<=0) return false;
        validate_spawn(s,id);
        Car candidate;candidate.s=s;geometry(candidate);
        if(!key_speeds.empty()) candidate.s.speed=std::min(candidate.s.speed,cruise(candidate));
        for(auto& pair:cars) if(overlaps(candidate,*pair.second)) return false;
        index_current();
        if(lead(candidate,s.distance,22+s.length).second<22) return false;
        insert(candidate.s,id);return true;
    }
    int compile_path(const SpawnPath& path) {
        if(!path.found) return -1;
        Route r;r.edge_ids=path.edges;r.cost=path.cost;
        double travelled=0;
        std::vector<int> section_kinds;
        std::vector<double> connector_starts;
        for(int id:path.edges) {
            auto& edge=size_t(id)<graph.edges.size()?graph.edges.at(id):path.extras.at(size_t(id)-graph.edges.size());auto& data=edge.data;
            // Geometry length is an immutable graph fact. Using its canonical
            // value preserves Python math.dist rounding in control rulers.
            double length=data.length;
            for(auto p:edge.points) if(r.points.empty() || p.x!=r.points.back().x || p.y!=r.points.back().y) {
                if(!r.points.empty()) {r.length+=std::hypot(p.x-r.points.back().x,p.y-r.points.back().y);r.ends.push_back(r.length);}
                r.points.push_back(p);
            }
            if(length>0 && data.key>=0) {r.sections.push_back({travelled,travelled+length,data.offset,data.key});section_kinds.push_back(data.kind);}
            if(data.connection>=0) {r.movements.push_back({travelled+data.control_offset,travelled+length,-1,data.connection,data.incoming});connector_starts.push_back(travelled);}
            travelled+=length;
        }
        for(size_t movement=0;movement<r.movements.size();++movement) {
            auto& m=r.movements[movement];double connector=connector_starts[movement];
            for(size_t i=0;i<r.sections.size();++i) {
                auto& s=r.sections[i];int kind=section_kinds[i];
                if((kind==1 || kind==2) && s.end<=connector+1e-8) m.incoming=s.key;
                if(kind==1 && s.end<=m.start+1e-8) m.signal_start=s.start;
            }
        }
        routes.push_back(std::move(r));return int(routes.size()-1);
    }
    int find_route(int source,int destination) {
        auto key=std::make_pair(source,destination);auto found=spawn_routes.find(key);
        if(found!=spawn_routes.end()) return found->second;
        int result=compile_path(graph.find(source,destination));spawn_routes.emplace(key,result);return result;
    }
    int generated_active() {int n=0;for(auto& pair:cars) n+=pair.second->s.generated;return n;}
    bool generate_one(int source,int destination) {
        require(source>=0 && size_t(source)<graph.endpoints.size() && destination>=0 && size_t(destination)<graph.endpoints.size(),"unknown endpoint");
        if(source==destination || generated_active()>=cap) return false;
        int route_id=find_route(source,destination);if(route_id<0) return false;
        require(rng_ready,"random state is not configured");
        int64_t number=spawned_count+1;std::string id;
        for(;;++number) {
            std::ostringstream name;name<<"test-car-"<<std::setfill('0')<<std::setw(6)<<number;id=name.str();
            bool exists=false;for(auto& pair:cars) if(pair.second->id==id) {exists=true;break;}
            if(!exists) break;
        }
        int color=int(random.below(5));
        while(cars.count(next_handle)) ++next_handle;
        NTSpawn s{next_handle,route_id,number%5==0?1:0,0,0,1,0,speed*22/15,14,6,-1,0,0,-1};
        if(!admit(s,id)) return false;
        generated.push_back({next_handle++,route_id,source,destination,color,number});spawned_count=number;return true;
    }
    void generate(double dt) {
        generated.clear();
        if(sources.size()<2) return;
        int slots=cap-generated_active();
        for(size_t i=0;i<sources.size();++i) {
            source_times[i]+=dt;if(source_times[i]<interval) continue;
            source_times[i]=std::fmod(source_times[i],interval);
            std::vector<int> destinations;for(int destination:sources) if(destination!=sources[i]) destinations.push_back(destination);
            require(rng_ready,"random state is not configured");random.shuffle(destinations);
            if(slots<=0) continue;
            for(int destination:destinations) if(generate_one(sources[i],destination)) {--slots;break;}
        }
    }
    double connector_start(Car& c,const NTMovement& m) {
        // A movement's occupancy section starts before its internal control offset.
        for(auto& s:route(c).sections) if(s.key==connection_keys.at(m.connection) && s.start<=m.start && s.end==m.end) return s.start;
        return m.start;
    }
    std::vector<int> connection_keys;
};
Engine& engine(void* p) {require(p!=nullptr,"engine is closed");return *static_cast<Engine*>(p);}
template<class F> int guarded(F f) {try {error.clear();return f();}catch(const std::exception& e){error=e.what();return -1;}catch(...){error="native engine failure";return -1;}}
}
extern "C" {
int nt_abi(){return 4;}
const char* nt_error(){return error.c_str();}
void* nt_create(double speed){try{error.clear();return new Engine(speed);}catch(const std::exception& e){error=e.what();return nullptr;}}
void nt_destroy(void* p){delete static_cast<Engine*>(p);}
int nt_network(void* p,const NTConnection* cs,int n,const unsigned char* conflicts,const unsigned char* yields){return guarded([&]{
    auto& e=engine(p);require(n>=0,"invalid connection count");
    e.connections.assign(cs,cs+n);e.relations.clear();
    for(int i=0;i<n;++i) for(int j=0;j<n;++j) {int f=conflicts[size_t(i)*n+j]+2*yields[size_t(i)*n+j];if(f) e.relations[e.relation_key(i,j)]=static_cast<unsigned char>(f);}
    // Connection occupancy keys are supplied as a negative incoming code on a synthetic movement? No: target mapping is separate through route registration.
    e.connection_keys.resize(n,-1);e.signal_aspects.assign(n,0);e.rebuild_signal_conflicts();
    for(auto& pair:e.cars) e.update_signal_occupancy(*pair.second);
    return 0;});}
int nt_network_sparse(void* p,const NTConnection* cs,int n,const NTRelation* pairs,int count){return guarded([&]{
    auto& e=engine(p);require(n>=0 && count>=0 && (n==0 || cs) && (count==0 || pairs),"invalid network counts");
    std::unordered_map<uint64_t,unsigned char> relations;
    for(int i=0;i<count;++i) {auto row=pairs[i];require(row.first>=0 && row.first<n && row.second>=0 && row.second<n && row.flags>=0 && row.flags<=3,"invalid relationship");relations[e.relation_key(row.first,row.second)]=static_cast<unsigned char>(row.flags);}
    std::vector<NTConnection> connections;if(n) connections.assign(cs,cs+n);
    for(auto& c:connections) {require(c.intersection>=0 && c.control>=0 && c.control<=2,"invalid connection");for(double v:{c.hx,c.hy,c.px,c.py}) check_finite(v);}
    e.connections=std::move(connections);e.relations=std::move(relations);e.connection_keys.resize(n,-1);
    e.signal_aspects.assign(n,0);e.rebuild_signal_conflicts();
    for(auto& pair:e.cars) e.update_signal_occupancy(*pair.second);
    return 0;});}
int nt_route(void* p,const NTPoint* pts,int np,const NTSection* ss,int ns,const NTMovement* ms,int nm){return guarded([&]{
    auto& e=engine(p);require(np>=2 && pts && ns>=0 && (!ns || ss) && nm>=0 && (!nm || ms),"invalid route counts or buffers");Route r;
    for(int i=0;i<np;++i){check_finite(pts[i].x);check_finite(pts[i].y);if(r.points.empty() || std::hypot(pts[i].x-r.points.back().x,pts[i].y-r.points.back().y)>0){
        if(!r.points.empty()){r.length+=std::hypot(pts[i].x-r.points.back().x,pts[i].y-r.points.back().y);r.ends.push_back(r.length);}r.points.push_back(pts[i]);}}
    require(r.length>0,"degenerate route");if(ns) r.sections.assign(ss,ss+ns);if(nm) r.movements.assign(ms,ms+nm);
    for(auto& s:r.sections){check_finite(s.start);check_finite(s.end);check_finite(s.offset);require(s.end>=s.start && s.key>=0,"invalid route section");}
    for(auto& m:r.movements){require(m.connection>=0 && static_cast<size_t>(m.connection)<e.connections.size(),"unknown movement");check_finite(m.start);check_finite(m.end);check_finite(m.signal_start);}
    // Infer each connector's shared occupancy key from its end and section type.
    // Python sends its connection occupancy key in the explicit ABI registration below.
    e.routes.push_back(std::move(r));return static_cast<int>(e.routes.size()-1);});}
int nt_connection_key(void* p,int connection,int key){return guarded([&]{engine(p).connection_keys.at(connection)=key;return 0;});}
int nt_spawn(void* p,const NTSpawn* s,const char* id,const char* reason,const char* phantom){return guarded([&]{
    auto& e=engine(p);require(s!=nullptr && id!=nullptr,"missing spawn");e.insert(*s,id,reason,phantom);return 0;});}
int nt_yellow(void* p,int h,int movement,int go){return guarded([&]{auto& e=engine(p);
    require(movement>=-1 && (movement<0 || static_cast<size_t>(movement)<e.connections.size()),"unknown yellow movement");
    require(go==0 || go==1,"invalid yellow commitment");auto& c=e.car(h);c.yellow_movement=movement;c.yellow_go=go!=0;return 0;});}
int nt_place(void* p,int h,double d){return guarded([&]{check_finite(d);auto& e=engine(p);auto& c=e.car(h);c.s.distance=clamp(d,0,e.route(c).length);c.geometry=c.control_cursor=c.route_cursor=c.round_cursor=c.section_cursor=c.section_first=c.section_stop=0;e.geometry(c);e.update_signal_occupancy(c);e.index_dirty=true;return 0;});}
int nt_resize(void* p,int h,double l,double w){return guarded([&]{check_finite(l);check_finite(w);require(l>0 && w>0,"invalid dimensions");auto& e=engine(p);auto& c=e.car(h);c.s.length=l;c.s.width=w;c.section_first=c.section_stop=0;e.update_signal_occupancy(c);e.index_dirty=true;return 0;});}
int nt_remove(void* p,int h){return guarded([&]{auto& e=engine(p);auto& c=e.car(h);for(int movement:c.signal_occupancy)e.adjust_signal_occupancy(movement,-1);e.cars.erase(h);e.arrivals.erase(h);e.waiting.clear();e.stall=0;e.winner=e.winner_connection=-1;e.hard=false;e.index_dirty=true;return 0;});}
int nt_external_claim(void* p,int h,int con){return guarded([&]{auto& e=engine(p);
    require(h<0,"external claim handle must be negative");require(con>=0 && static_cast<size_t>(con)<e.connections.size(),"unknown external claim");
    auto& claims=e.external_claims[h];if(std::find(claims.begin(),claims.end(),con)==claims.end()) claims.push_back(con);return 0;});}
int nt_claim(void* p,int h,int con){return guarded([&]{auto& e=engine(p);require(con>=0 && static_cast<size_t>(con)<e.connections.size(),"unknown claim");e.claim(e.car(h),con);return 0;});}
int nt_arrival(void* p,int h,int con,double t){return guarded([&]{auto& e=engine(p);e.car(h);check_finite(t);require(con>=0 && static_cast<size_t>(con)<e.connections.size(),"unknown arrival");e.arrivals[h]={con,t};return 0;});}
int nt_clock(void* p,double t,double stall,double threshold){return guarded([&]{check_finite(t);check_finite(stall);check_finite(threshold);require(t>=0 && stall>=0 && threshold>=0,"invalid clock");auto& e=engine(p);e.time=t;e.stall=stall;e.threshold=threshold;return 0;});}
int nt_waiting(void* p,int h,double seconds){return guarded([&]{auto& e=engine(p);e.car(h);check_finite(seconds);require(seconds>=0,"invalid waiting duration");e.waiting[h]=seconds;return 0;});}
int nt_winner(void* p,int h,int connection,int hard){return guarded([&]{auto& e=engine(p);e.car(h);require(connection>=0 && static_cast<size_t>(connection)<e.connections.size(),"unknown winner movement");require(hard==0 || hard==1,"invalid gridlock state");e.winner=h;e.winner_connection=connection;e.hard=hard;return 0;});}
int nt_speed(void* p,double v){return guarded([&]{check_finite(v);require(v>0,"invalid cruise speed");engine(p).speed=v;return 0;});}
int nt_control(void* p,int con,int control){return guarded([&]{require(control>=0 && control<=2,"invalid control");auto& e=engine(p);auto& current=e.connections.at(con);
    if(current.control!=control) {current.control=control;e.rebuild_signal_conflicts();for(auto& pair:e.cars)e.update_signal_occupancy(*pair.second);}
    return 0;});}
int nt_signal_aspects(void* p,const unsigned char* aspects,int n){return guarded([&]{auto& e=engine(p);
    require(n==static_cast<int>(e.connections.size()) && (n==0 || aspects),"invalid signal aspect count");
    std::vector<unsigned char> next(static_cast<size_t>(n),0);
    for(int i=0;i<n;++i) {require(aspects[i]<=2,"invalid signal aspect");
        require(e.connections[i].control==2 || aspects[i]==0,"aspect on a non-signal movement");next[i]=aspects[i];}
    for(int i=0;i<n;++i) if(next[i])
        for(int conflicting:e.signal_entry_blocked_by_occupant[i])
            if(next[conflicting])
                throw std::invalid_argument("conflicting protected signal permissions");
    e.signal_aspects=std::move(next);return 0;});}
int nt_profile_enable(void* p,int enabled){return guarded([&]{require(enabled==0 || enabled==1,"invalid profile flag");auto& e=engine(p);
    e.profile={};e.profile_enabled=enabled!=0;return 0;});}
int nt_profile_read(void* p,NTProfile* profile){return guarded([&]{require(profile!=nullptr,"missing profile output");*profile=engine(p).profile;return 0;});}
int nt_step(void* p,double dt){return guarded([&]{check_finite(dt);require(dt>=0,"invalid timestep");auto& e=engine(p);e.completed.clear();e.retired.clear();e.pedestrian_completed.clear();double remaining=dt;
    if(dt<=0.05+1e-9) e.tick(dt);else while(remaining>1e-9){double part=std::min(0.05,remaining);e.tick(part);remaining-=part;}return 0;});}
int nt_pedestrian_lane(void* p,const NTPoint* points,int n,double crossing_fraction){return guarded([&]{
    auto& e=engine(p);check_finite(crossing_fraction);require(n>=2 && points && crossing_fraction>=-1 && crossing_fraction<=1,"invalid pedestrian lane");PedestrianLane lane;
    for(int i=0;i<n;++i){check_finite(points[i].x);check_finite(points[i].y);if(lane.points.empty() || std::hypot(points[i].x-lane.points.back().x,points[i].y-lane.points.back().y)>0){
        if(!lane.points.empty()){lane.length+=std::hypot(points[i].x-lane.points.back().x,points[i].y-lane.points.back().y);lane.ends.push_back(lane.length);}lane.points.push_back(points[i]);}}
    require(lane.length>0,"degenerate pedestrian lane");
    if(crossing_fraction>=0){lane.crossing=lane.length*crossing_fraction;Pedestrian p{};p.distance=lane.crossing;Engine::pedestrian_position(p,lane);lane.crossing_point=p.position;}
    e.pedestrian_lanes.push_back(std::move(lane));return int(e.pedestrian_lanes.size()-1);});}
int nt_pedestrian_spawn(void* p,int id,int lane,double speed){return guarded([&]{auto& e=engine(p);check_finite(speed);
    require(id>=0 && lane>=0 && size_t(lane)<e.pedestrian_lanes.size() && speed>0,"invalid pedestrian spawn");require(!e.pedestrian_indices.count(id),"duplicate pedestrian ID");
    Pedestrian walker{};walker.id=id;walker.lane=lane;walker.speed=speed;walker.position=e.pedestrian_lanes[size_t(lane)].points.front();
    e.pedestrian_indices[id]=e.pedestrians.size();e.pedestrians.push_back(walker);return 0;});}
int nt_pedestrian_waits(void* p){return guarded([&]{return engine(p).pedestrian_waits;});}
const NTPedestrianState* nt_pedestrian_states(void* p,int* count){try{auto& e=engine(p);e.pedestrian_output.clear();e.pedestrian_output.reserve(e.pedestrians.size());
    for(const auto& person:e.pedestrians){e.pedestrian_output.push_back(Engine::pedestrian_state(person));}
    *count=int(e.pedestrian_output.size());return e.pedestrian_output.data();
    }catch(const std::exception& ex){error=ex.what();*count=-1;return nullptr;}}
const NTPedestrianState* nt_pedestrian_completed(void* p,int* count){try{auto& e=engine(p);*count=int(e.pedestrian_completed.size());return e.pedestrian_completed.data();
    }catch(const std::exception& ex){error=ex.what();*count=-1;return nullptr;}}
const NTState* nt_states(void* p,int* count){try{auto& e=engine(p);e.output.clear();for(auto& pair:e.cars)e.output.push_back(e.state(*pair.second));e.output.insert(e.output.end(),e.completed.begin(),e.completed.end());*count=static_cast<int>(e.output.size());return e.output.data();}catch(const std::exception& ex){error=ex.what();*count=-1;return nullptr;}}
int nt_shared_vehicle(void* p,int h,NTSharedVehicle* view){return guarded([&]{require(view!=nullptr,"missing shared view");auto& c=engine(p).car(h);*view={&c.s,&c.position,&c.heading,&c.latest_claim,&c.yellow_movement,&c.yellow_go};return 0;});}
const char* nt_shared_text(void* p,int h,int field){try{require(field==0 || field==1,"unknown text field");auto& c=engine(p).shared_car(h);return field?c.phantom.c_str():c.reason.c_str();}catch(const std::exception& ex){error=ex.what();return nullptr;}}
const NTState* nt_completed(void* p,int* count){try{auto& e=engine(p);*count=static_cast<int>(e.completed.size());return e.completed.data();}catch(const std::exception& ex){error=ex.what();*count=-1;return nullptr;}}
int nt_graph(void* p,const NTPoint* nodes,int nn,const NTGraphEdge* edges,int ne,const NTPoint* points,int np,const NTEndpoint* ends,int nend,const int* ports,int nport){return guarded([&]{
    auto& e=engine(p);require(nn>=0 && ne>=0 && np>=0 && nend>=0 && nport>=0,"invalid graph counts");
    require((!nn || nodes) && (!ne || edges) && (!np || points) && (!nend || ends) && (!nport || ports),"missing graph data");
    SpawnGraph graph;if(nn) graph.nodes.assign(nodes,nodes+nn);graph.adjacency.resize(nn);
    for(auto node:graph.nodes) {check_finite(node.x);check_finite(node.y);}
    for(int i=0;i<ne;++i) {auto d=edges[i];require(d.source>=0 && d.source<nn && d.destination>=0 && d.destination<nn && d.point_start>=0 && d.point_count>=0 && d.point_start<=np && d.point_count<=np-d.point_start,"invalid graph edge");
        require(d.connection>=-1 && (d.connection<0 || size_t(d.connection)<e.connections.size()) && d.kind>=0 && d.kind<=3,"invalid edge metadata");
        require(d.kind==0 || d.point_count>=2,"graph travel edge requires geometry");
        check_finite(d.cost);check_finite(d.offset);check_finite(d.control_offset);check_finite(d.length);require(d.cost>=0 && d.length>=0,"negative edge cost or length");
        SpawnEdge edge;edge.data=d;if(d.point_count) edge.points.assign(points+d.point_start,points+d.point_start+d.point_count);
        for(auto point:edge.points) {check_finite(point.x);check_finite(point.y);}
        graph.edges.push_back(std::move(edge));graph.adjacency[d.source].push_back(i);
    }
    for(int i=0;i<nend;++i) {auto d=ends[i];check_finite(d.x);check_finite(d.y);
        require(d.out_start>=0 && d.out_count>=0 && d.out_start<=nport && d.out_count<=nport-d.out_start && d.in_start>=0 && d.in_count>=0 && d.in_start<=nport && d.in_count<=nport-d.in_start,"invalid endpoint ports");
        SpawnEndpoint end;end.point={d.x,d.y};
        for(int j=0;j<d.out_count;++j) {int n=ports[d.out_start+j];require(n>=0 && n<nn,"invalid outgoing port");end.outgoing.push_back(n);}
        for(int j=0;j<d.in_count;++j) {int n=ports[d.in_start+j];require(n>=0 && n<nn,"invalid incoming port");end.incoming.push_back(n);}
        graph.endpoints.push_back(std::move(end));
    }
    e.graph=std::move(graph);e.spawn_routes.clear();e.sources.clear();e.source_times.clear();return 0;});}
int nt_rng_set(void* p,const uint32_t* words,int n){return guarded([&]{require(words && n==625 && words[624]<=624,"invalid random state");auto& e=engine(p);std::copy(words,words+624,e.random.words.begin());e.random.index=words[624];e.rng_ready=true;return 0;});}
int nt_rng_get(void* p,uint32_t* words,int n){return guarded([&]{require(words && n==625,"invalid random output");auto& e=engine(p);require(e.rng_ready,"random state is not configured");std::copy(e.random.words.begin(),e.random.words.end(),words);words[624]=e.random.index;return 0;});}
int nt_choice(void* p,int n){return guarded([&]{auto& e=engine(p);require(e.rng_ready && n>0,"invalid random choice");return int(e.random.below(uint32_t(n)));});}
int nt_sources(void* p,const int* sources,const double* times,int n,double interval,int cap,int64_t count,int next){return guarded([&]{
    auto& e=engine(p);check_finite(interval);require(n>=0 && (!n || (sources && times)) && interval>0 && cap>=1 && count>=0 && count<INT64_MAX && next>=0,"invalid spawn configuration");
    std::set<int> seen;std::vector<int> ids;std::vector<double> clocks;
    for(int i=0;i<n;++i) {require(sources[i]>=0 && size_t(sources[i])<e.graph.endpoints.size() && seen.insert(sources[i]).second,"invalid spawn source");check_finite(times[i]);require(times[i]>=0,"invalid source clock");ids.push_back(sources[i]);clocks.push_back(times[i]);}
    e.sources=std::move(ids);e.source_times=std::move(clocks);e.interval=interval;e.cap=cap;e.spawned_count=count;e.next_handle=next;return 0;});}
int nt_source_times(void* p,double* times,int n){return guarded([&]{auto& e=engine(p);require(n==int(e.source_times.size()) && (!n || times),"invalid clock output");std::copy(e.source_times.begin(),e.source_times.end(),times);return 0;});}
int64_t nt_spawn_count(void* p){try{return engine(p).spawned_count;}catch(const std::exception& ex){error=ex.what();return -1;}}
int nt_generate(void* p,double dt){return guarded([&]{check_finite(dt);require(dt>=0 && dt<=0.05+1e-9,"invalid spawn timestep");engine(p).generate(dt);return 0;});}
int nt_generate_one(void* p,int source,int destination){return guarded([&]{auto& e=engine(p);e.generated.clear();return int(e.generate_one(source,destination));});}
const NTGenerated* nt_generated(void* p,int* count){try{auto& e=engine(p);*count=int(e.generated.size());return e.generated.data();}catch(const std::exception& ex){error=ex.what();*count=-1;return nullptr;}}
int nt_find_route(void* p,int source,int destination){return guarded([&]{return engine(p).find_route(source,destination)+1;});}
int nt_find_position_route(void* p,int source,int source_lane,double sd,NTPoint sp,int destination,int destination_lane,double dd,NTPoint dp){return guarded([&]{
    auto& e=engine(p);auto from=e.graph.query(source,source_lane,sd,sp),to=e.graph.query(destination,destination_lane,dd,dp);
    return e.compile_path(e.graph.find(from,to,source_lane<0 && destination_lane<0 && source==destination))+1;});}
const int* nt_route_edges(void* p,int route,int* count){try {auto& r=engine(p).routes.at(route);*count=int(r.edge_ids.size());return r.edge_ids.data();}catch(const std::exception& ex){error=ex.what();*count=-1;return nullptr;}}
const NTSection* nt_route_sections(void* p,int route,int* count){try {auto& rows=engine(p).routes.at(route).sections;*count=int(rows.size());return rows.data();}catch(const std::exception& ex){error=ex.what();*count=-1;return nullptr;}}
const NTMovement* nt_route_movements(void* p,int route,int* count){try {auto& rows=engine(p).routes.at(route).movements;*count=int(rows.size());return rows.data();}catch(const std::exception& ex){error=ex.what();*count=-1;return nullptr;}}
double nt_route_cost(void* p,int route){try{return engine(p).routes.at(route).cost;}catch(const std::exception& ex){error=ex.what();return -1;}}
int nt_admit(void* p,const NTSpawn* s,const char* id){return guarded([&]{require(s && id,"missing admission");return int(engine(p).admit(*s,id));});}
const NTBookkeeping* nt_bookkeeping(void* p,int* count,NTClock* clock){try{auto& e=engine(p);e.bookkeeping.clear();
    for(auto& pair:e.cars) {
        for(int claim:pair.second->claims) e.bookkeeping.push_back({pair.first,claim,0,0});
        for(int occupied:pair.second->signal_occupancy) e.bookkeeping.push_back({pair.first,occupied,3,0});
    }
    for(auto& pair:e.external_claims) for(int con:pair.second) e.bookkeeping.push_back({pair.first,con,0,0});
    for(auto& pair:e.arrivals) e.bookkeeping.push_back({pair.first,pair.second.connection,1,pair.second.time});
    for(auto& pair:e.waiting) e.bookkeeping.push_back({pair.first,-1,2,pair.second});
    *clock={e.time,e.stall,e.threshold,e.winner,e.winner_connection,int(e.hard)};*count=int(e.bookkeeping.size());return e.bookkeeping.data();}catch(const std::exception& ex){error=ex.what();*count=-1;return nullptr;}}
int nt_trace_enable(void* p,int enabled){return guarded([&]{engine(p).trace_enabled=enabled!=0;return 0;});}
const NTTrace* nt_trace(void* p,int* count){try{auto& e=engine(p);*count=int(e.trace.size());return e.trace.data();}catch(const std::exception& ex){error=ex.what();*count=-1;return nullptr;}}
const int* nt_trace_vehicles(void* p,int* count){try{auto& e=engine(p);*count=int(e.trace_vehicles.size());return e.trace_vehicles.data();}catch(const std::exception& ex){error=ex.what();*count=-1;return nullptr;}}
}

int nt_key_speed(void* p,int key,double mph){return guarded([&]{check_finite(mph);require(mph>0,"invalid road speed");engine(p).key_speeds[key]=mph;return 0;});}
