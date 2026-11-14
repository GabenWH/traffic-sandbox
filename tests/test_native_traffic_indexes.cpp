#include "../native/traffic/engine.cpp"
#include <cassert>
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

} // namespace

int main() {
    test_merge_observation_order_and_future_visits();
    test_claim_lifetimes_and_topology_replacement();
}
