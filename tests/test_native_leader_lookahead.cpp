#include "../native/traffic/engine.cpp"
#include <cassert>
#include <memory>

int main() {
    Engine engine(25.0);
    Route route;
    route.length = 1000.0;
    route.sections.push_back(NTSection{0.0, 1000.0, 0.0, 7});
    engine.routes.push_back(route);

    Car follower;
    follower.id = "follower";
    follower.order = 0;
    follower.s.handle = 0;
    follower.s.route = 0;
    follower.s.distance = 500.0;
    follower.s.length = 14.0;

    Car leader;
    leader.id = "leader";
    leader.order = 1;
    leader.s.handle = 1;
    leader.s.route = 0;
    leader.s.length = 14.0;

    // A bumper gap exactly at the 128 ft lookahead is visible.
    leader.s.distance = 642.0;
    engine.index({&follower, &leader});
    auto [visible, gap] = engine.lead(follower, follower.s.distance, 128.0);
    assert(visible == &leader);
    assert(gap == 128.0);

    // One foot beyond the lookahead must not be returned as a leader.
    leader.s.distance = 643.0;
    engine.index({&follower, &leader});
    auto [outside, outside_gap] = engine.lead(follower, follower.s.distance, 128.0);
    assert(outside == nullptr);
    assert(std::isinf(outside_gap));

    // A longer vehicle may have its center beyond the cutoff while its rear
    // still reaches into the lookahead, so the conservative bound must retain it.
    leader.s.length = 40.0;
    leader.s.distance = 655.0; // bumper gap is 128 ft
    engine.index({&follower, &leader});
    auto [long_visible, long_gap] = engine.lead(follower, follower.s.distance, 128.0);
    assert(long_visible == &leader);
    assert(long_gap == 128.0);
}
