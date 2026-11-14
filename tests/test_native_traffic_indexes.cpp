#include "../native/traffic/engine.cpp"
#include <cassert>
#include <ctime>
#include <iostream>
#include <string_view>
#include <initializer_list>

namespace {

int add_route(Engine& engine, double length, std::initializer_list<NTSection> sections,
              std::initializer_list<NTMovement> movements = {}) {
    const NTPoint points[] = {{0, 0}, {length, 0}};
    int route = nt_route(&engine, points, 2, sections.begin(), int(sections.size()),
                         movements.begin(), int(movements.size()));
    assert(route >= 0);
    return route;
}

void add_car(Engine& engine, int handle, int route, const char* id, double distance,
             double speed = 0, double entry = -1) {
    const NTSpawn spawn{handle, route, 0, 0, 0, 0, distance, speed, 14, 6, -1, 0, 0, entry};
    assert(nt_spawn(&engine, &spawn, id, "", "") == 0);
}

void test_merge_observation_order_and_future_visits() {
    Engine engine(25);
    const NTConnection network[] = {
        {0, 0, 0, 0, 7, 1, 0, 80, 0},
        {1, 0, 0, 0, 8, 1, 0, 0, 0},
    };
    assert(nt_network_sparse(&engine, network, 2, nullptr, 0) == 0);
    assert(nt_connection_key(&engine, 0, 22) == 0);
    assert(nt_connection_key(&engine, 1, 23) == 0);
    int join = add_route(engine, 300, {{0, 80, 0, 1}, {80, 100, 0, 22},
                                       {100, 130, 10, 7}, {130, 300, 0, 8}},
                         {{80, 100, -1, 0, 1}});
    int loop = add_route(engine, 300, {{0, 125, 0, 8}, {125, 275, 0, 4}, {275, 300, 0, 7}});
    // The native route API permits overlapping sections ordered by end.
    int overlapping = add_route(engine, 200, {{0, 25, 0, 9}, {30, 40, 0, 7},
                                              {15, 60, 0, 10}, {100, 200, 0, 11}});
    int through = add_route(engine, 200, {{0, 100, 0, 5}, {100, 200, 0, 7}});
    int downstream = add_route(engine, 300, {{0, 300, 0, 8}});
    // The car is already committed to the downstream merge. Its later movement
    // at the first junction excludes it as a through car there.
    int committed = add_route(engine, 200, {{0, 80, 0, 23}, {80, 90, 0, 6},
                                            {90, 110, 0, 22}, {110, 200, 0, 7}},
                              {{0, 80, -1, 1, 6}, {90, 110, -1, 0, 6}});
    add_car(engine, 0, join, "joining", 70);
    add_car(engine, 1, loop, "alpha-loop", 72);
    add_car(engine, 2, through, "zulu-through", 70);
    add_car(engine, 3, committed, "reservation", 50, 10, 10);
    assert(nt_claim(&engine, 3, 1) == 0);
    assert(nt_trace_enable(&engine, 1) == 0);

    auto observed = [&] {
        assert(nt_step(&engine, 0) == 0);
        int count = 0;
        const NTTrace* rows = nt_trace(&engine, &count);
        for (int i = 0; i < count; ++i) {
            if (rows[i].handle != 0) continue;
            assert(rows[i].connection == 0 && rows[i].reservations == 1);
            int vehicle_count = 0;
            const int* ids = nt_trace_vehicles(&engine, &vehicle_count);
            return std::vector<int>(ids + rows[i].first_vehicle,
                                    ids + rows[i].first_vehicle + rows[i].vehicle_count);
        }
        assert(false && "joining car disappeared from the trace");
        return std::vector<int>{};
    };
    // Its future target is 203 feet away, so the loop car's currently
    // occupied downstream lane does not make it a merge candidate.
    assert((observed() == std::vector<int>{2}));
    // The first future visit now lies exactly at the 180 ft boundary.
    assert(nt_place(&engine, 1, 95) == 0);
    assert((observed() == std::vector<int>{1, 2}));
    assert(nt_remove(&engine, 1) == 0);
    assert((observed() == std::vector<int>{2}));
    add_car(engine, 4, overlapping, "bravo-overlap", 20);
    assert((observed() == std::vector<int>{4, 2}));
    add_car(engine, 5, downstream, "charlie-downstream", 150);
    assert((observed() == std::vector<int>{4, 5, 2})); // projected position is 30 + 150
    assert(nt_place(&engine, 5, 151) == 0);
    assert((observed() == std::vector<int>{4, 2}));
}

void test_claim_lifetimes_and_topology_replacement() {
    Engine engine(25);
    const NTConnection network[] = {
        {0, 0, 0, 0, -1, 1, 0, 0, 0},
        {0, 0, 0, 0, -1, 0, 1, 0, 0},
        {1, 0, 0, 0, -1, 1, 0, 0, 0},
    };
    const NTRelation relations[] = {{0, 1, 1}, {1, 0, 1}};
    assert(nt_network_sparse(&engine, network, 3, relations, 2) == 0);
    int route = add_route(engine, 100, {{0, 100, 0, 5}});
    add_car(engine, 0, route, "query", 50);
    add_car(engine, 1, route, "removed", 0);
    add_car(engine, 2, route, "completes", 100);

    Car& query = engine.car(0);
    assert(nt_claim(&engine, 0, 1) == 0);
    assert(!engine.blocked_by_claims(query, 0));
    assert(nt_claim(&engine, 1, 1) == 0);
    assert(nt_claim(&engine, 1, 1) == 0);
    assert(engine.blocked_by_claims(query, 0));
    assert(!engine.blocked_by_claims(query, 2));
    assert(nt_remove(&engine, 1) == 0);
    assert(!engine.blocked_by_claims(query, 0));

    assert(nt_claim(&engine, 2, 1) == 0);
    assert(engine.blocked_by_claims(query, 0));
    assert(nt_step(&engine, 0) == 0);
    assert(!engine.blocked_by_claims(query, 0));

    assert(nt_external_claim(&engine, -1, 1) == 0);
    assert(engine.blocked_by_claims(query, 0));
    assert(nt_network_sparse(&engine, network, 3, nullptr, 0) == 0);
    assert(!engine.blocked_by_claims(query, 0));
    assert(nt_network_sparse(&engine, network, 3, relations, 2) == 0);
    assert(engine.blocked_by_claims(query, 0));
}

void test_arrival_priority_and_lifetimes() {
    Engine engine(25);
    NTConnection network[] = {
        {0, 1, 0, 0, -1, 1, 0, 0, 0},
        {0, 1, 0, 0, -1, 1, 0, 0, 0},
        {1, 1, 0, 0, -1, 1, 0, 0, 0},
    };
    const NTRelation relations[] = {{0, 0, 1}, {0, 1, 3}, {1, 0, 3}, {0, 2, 1}};
    assert(nt_network_sparse(&engine, network, 3, relations, 4) == 0);
    int route = add_route(engine, 300, {{0, 80, 0, 5}, {80, 100, 0, 6},
                                       {100, 300, 0, 7}}, {{80, 100, -1, 0, 5}});
    int other_route = add_route(engine, 300, {{0, 300, 0, 8}});
    add_car(engine, 0, route, "a-query", 73);
    add_car(engine, 1, other_route, "b-conflicting", 0);
    add_car(engine, 2, other_route, "c-remote", 100);
    Car& query = engine.car(0);
    Car& conflicting = engine.car(1);

    assert(nt_arrival(&engine, 0, 0, 1.0) == 0);
    assert(engine.can_approach(query, 0)); // Exclude its own arrival even for a self-conflict.
    assert(nt_arrival(&engine, 2, 2, 0.0) == 0);
    assert(!engine.can_approach(query, 0)); // Honor a directional relation supplied by the ABI.
    assert(engine.can_claim(query, 0)); // Stop priority is local to the junction.
    network[2].intersection = 0;
    assert(nt_network_sparse(&engine, network, 3, relations, 4) == 0);
    assert(!engine.can_claim(query, 0));
    assert(nt_remove(&engine, 2) == 0);
    assert(engine.can_approach(query, 0));

    assert(nt_arrival(&engine, 1, 1, 0.5) == 0);
    assert(!engine.can_claim(query, 0));
    assert(nt_arrival(&engine, 1, 1, 1.5) == 0);
    assert(engine.can_claim(query, 0));
    assert(nt_control(&engine, 0, 0) == 0);
    assert(nt_control(&engine, 1, 0) == 0);
    assert(nt_arrival(&engine, 1, 1, 1.0) == 0);
    // Both yield to each other. The stable vehicle ID breaks the tie.
    assert(engine.can_claim(query, 0));
    assert(!engine.can_claim(conflicting, 1));

    network[2].intersection = 1;
    assert(nt_network_sparse(&engine, network, 3, relations, 3) == 0);
    assert(nt_arrival(&engine, 1, 2, 1.0) == 0);
    assert(engine.can_approach(query, 0));
    assert(nt_arrival(&engine, 1, 1, 1.0) == 0);
    assert(!engine.can_approach(query, 0));
    assert(nt_claim(&engine, 1, 1) == 0);
    engine.release(conflicting, 1);
    assert(engine.can_approach(query, 0));

    assert(nt_control(&engine, 0, 1) == 0);
    assert(nt_step(&engine, 0) == 0);
    int count = 0;
    NTClock clock{};
    const NTBookkeeping* published = nt_bookkeeping(&engine, &count, &clock);
    assert(count == 1 && published[0].handle == 0 && published[0].value == 1.0);
    assert(nt_place(&engine, 0, 50) == 0);
    assert(nt_step(&engine, 0) == 0);
    assert(!engine.can_claim(query, 0));
    assert(engine.can_approach(query, 0));
}

void test_room_checks_across_lanes() {
    Engine engine(25);
    const NTConnection movement{0, 0, 0, 0, -1, 1, 0, 80, 0};
    assert(nt_network_sparse(&engine, &movement, 1, nullptr, 0) == 0);
    int route = add_route(engine, 300, {{0, 80, 0, 5}, {80, 100, 0, 6},
                                       {100, 138, 0, 7}, {138, 300, 0, 8}},
                         {{80, 100, -1, 0, 5}});
    add_car(engine, 0, route, "query", 50);
    Car& query = engine.car(0);

    // The bus is on a section that begins beyond the required 29 ft gap.
    // Its rear still determines whether the car can clear the junction.
    NTObstacle bus{1, 8, 18, 40, 8, 156, 0, 1, 0};
    assert(nt_lane_obstacle(&engine, &bus, "bus") == 0);
    assert(nt_step(&engine, 0) == 0);
    assert(query.reason.empty());
    --bus.distance;
    --bus.x;
    assert(nt_lane_obstacle(&engine, &bus, "bus") == 0);
    assert(nt_step(&engine, 0) == 0);
    assert(query.reason == "waiting for room beyond the junction");
    assert(nt_remove_obstacle(&engine, "bus") == 1);

    // During a lane change the original lane still constrains a clear path.
    NTObstacle source_leader{2, 9, 68, 14, 6, 68, 10, 1, 0};
    assert(nt_lane_obstacle(&engine, &source_leader, "source-leader") == 0);
    query.lane_source = 9;
    query.lane_source_distance = 50;
    const std::vector<Car*> cars{&query};
    MergeSnapshot snapshot(cars);
    assert(engine.path_clear(query, 0, snapshot)); // Exactly 4 ft of clearance.
    ++query.lane_source_distance;
    assert(!engine.path_clear(query, 0, snapshot));
}

double decision_cpu_seconds(int junctions, bool merge) {
    Engine engine(25);
    std::vector<NTConnection> network;
    for (int i = 0; i < junctions; ++i) {
        // Red signals still evaluate merge observations but bypass claim checks.
        // The uncontrolled through scenario isolates the claim checks.
        network.push_back({i, merge ? 2 : 0, 0, 0, merge ? 3*i+2 : -1, 1, 0, 80, 0});
    }
    assert(nt_network_sparse(&engine, network.data(), junctions, nullptr, 0) == 0);
    for (int i = 0; i < junctions; ++i) {
        const int lane = 3*i;
        assert(nt_connection_key(&engine, i, lane+1) == 0);
        int approach = add_route(engine, 300, {{0, 80, 0, lane}, {80, 100, 0, lane+1},
                                               {100, 300, 0, lane+2}}, {{80, 100, -1, i, lane}});
        int downstream = add_route(engine, 200, {{0, 200, 0, lane+2}});
        add_car(engine, 2*i, approach, ("approach-"+std::to_string(i)).c_str(), 50);
        add_car(engine, 2*i+1, downstream, ("downstream-"+std::to_string(i)).c_str(), 50);
    }
    assert(nt_step(&engine, 0) == 0);
    const int ticks = junctions == 64 ? 256 : 16;
    const auto start = std::clock();
    for (int tick = 0; tick < ticks; ++tick) assert(nt_step(&engine, 0) == 0);
    return double(std::clock() - start) / CLOCKS_PER_SEC / ticks;
}

int check_scaling(bool merge) {
    // Local traffic is identical at each junction. Allow up to 4x more work
    // per junction for larger working sets and sorting. A fleet-wide scan
    // repeated per junction grows roughly 16x per junction at these sizes.
    const double small = decision_cpu_seconds(64, merge);
    const double large = decision_cpu_seconds(1024, merge);
    constexpr double growth_budget = 64;
    std::cout << (merge ? "Merge" : "Claim") << " CPU per tick at 64/1024 junctions: "
              << small * 1000 << " / " << large * 1000 << " ms ("
              << large / small << "x, budget " << growth_budget << "x)\n";
    return large > small * growth_budget;
}

double arrival_query_cpu_seconds(int junctions, bool claim) {
    Engine engine(25);
    std::vector<NTConnection> network;
    std::vector<NTRelation> relations;
    for (int i = 0; i < junctions; ++i) {
        network.push_back({i, 1, 0, 0, -1, 1, 0, 0, 0});
        relations.push_back({i, i, 1});
    }
    assert(nt_network_sparse(&engine, network.data(), junctions, relations.data(), junctions) == 0);
    int route = add_route(engine, 100, {{0, 100, 0, 5}});
    std::vector<Car*> queries;
    for (int i = 0; i < junctions; ++i) {
        add_car(engine, i, route, ("arrival-" + std::to_string(i)).c_str(), 50);
        assert(nt_arrival(&engine, i, i, 1.0) == 0);
        queries.push_back(&engine.car(i));
    }
    const int repeats = 262144 / junctions;
    const auto start = std::clock();
    for (int repeat = 0; repeat < repeats; ++repeat)
        for (int i = 0; i < junctions; ++i)
            assert(claim ? engine.can_claim(*queries[i], i) : engine.can_approach(*queries[i], i));
    return double(std::clock() - start) / CLOCKS_PER_SEC / repeats;
}

int check_arrival_scaling() {
    // Hold each junction's queue length constant while increasing the number
    // of occupied junctions. Neither query should scan those other arrivals.
    bool exceeded = false;
    for (bool claim : {false, true}) {
        const double small = arrival_query_cpu_seconds(64, claim);
        const double large = arrival_query_cpu_seconds(1024, claim);
        constexpr double growth_budget = 64;
        std::cout << (claim ? "Claim" : "Approach") << " CPU at 64/1024 occupied junctions: "
                  << small * 1000 << " / " << large * 1000 << " ms ("
                  << large / small << "x, budget " << growth_budget << "x)\n";
        exceeded |= large > small * growth_budget;
    }
    return exceeded;
}

} // namespace

int main(int argc, char** argv) {
    if (argc == 2) {
        const std::string_view mode = argv[1];
        if (mode == "arrival") return check_arrival_scaling();
        return check_scaling(mode == "merge");
    }
    test_merge_observation_order_and_future_visits();
    test_claim_lifetimes_and_topology_replacement();
    test_arrival_priority_and_lifetimes();
    test_room_checks_across_lanes();
}
