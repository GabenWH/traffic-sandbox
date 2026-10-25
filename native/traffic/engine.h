#pragma once
#include <cstddef>
#include <cstdint>

// ABI 2. All distances/speeds use the Python model's feet and feet/second.
extern "C" {
struct NTConnection {
    int intersection, control, maneuver, role, target;
    double hx, hy, px, py;
};
struct NTPoint { double x, y; };
struct NTSection { double start, end, offset; int key; };
struct NTMovement { double start, end, signal_start; int connection, incoming; };
struct NTSpawn {
    int handle, route, style, state, signal, generated;
    double distance, speed, length, width, cap, dwell, desired, entry;
};
struct NTState {
    int handle, state, signal, claim, alive;
    double distance, speed, x, y, hx, hy, desired, dwell, entry;
    const char *reason, *phantom;
};
struct NTRelation { int first, second, flags; };
struct NTGraphEdge {
    int source, destination, point_start, point_count, key, kind, connection, incoming;
    double cost, offset, control_offset, length;
};
struct NTEndpoint { double x, y; int out_start, out_count, in_start, in_count; };
struct NTGenerated { int handle, route, source, destination, color; int64_t number; };
struct NTBookkeeping { int handle, connection, kind; double value; };
struct NTClock { double time, stall, threshold; int winner, movement, hard; };
struct NTTrace { int handle, connection, priority, claimed, first_vehicle, vehicle_count, reservations; double distance, speed; };
int nt_abi();
const char* nt_error();
void* nt_create(double speed);
void nt_destroy(void*);
int nt_network(void*, const NTConnection*, int, const unsigned char*, const unsigned char*);
int nt_network_sparse(void*, const NTConnection*, int, const NTRelation*, int);
int nt_route(void*, const NTPoint*, int, const NTSection*, int, const NTMovement*, int);
int nt_connection_key(void*, int, int);
int nt_spawn(void*, const NTSpawn*, const char*, const char*, const char*);
int nt_place(void*, int, double);
int nt_resize(void*, int, double, double);
int nt_remove(void*, int);
int nt_claim(void*, int, int);
int nt_arrival(void*, int, int, double);
int nt_clock(void*, double, double, double);
int nt_waiting(void*, int, double);
int nt_winner(void*, int, int, int);
int nt_speed(void*, double);
int nt_control(void*, int, int);
int nt_step(void*, double);
const NTState* nt_states(void*, int*);
int nt_graph(void*, const NTPoint*, int, const NTGraphEdge*, int, const NTPoint*, int,
             const NTEndpoint*, int, const int*, int);
int nt_rng_set(void*, const uint32_t*, int);
int nt_rng_get(void*, uint32_t*, int);
int nt_choice(void*, int);
int nt_sources(void*, const int*, const double*, int, double, int, int64_t, int);
int nt_source_times(void*, double*, int);
int64_t nt_spawn_count(void*);
int nt_generate(void*, double);
int nt_generate_one(void*, int, int);
const NTGenerated* nt_generated(void*, int*);
int nt_find_route(void*, int, int);
int nt_find_position_route(void*, int, int, double, NTPoint, int, int, double, NTPoint);
const int* nt_route_edges(void*, int, int*);
const NTSection* nt_route_sections(void*, int, int*);
const NTMovement* nt_route_movements(void*, int, int*);
double nt_route_cost(void*, int);
int nt_admit(void*, const NTSpawn*, const char*);
const NTBookkeeping* nt_bookkeeping(void*, int*, NTClock*);
int nt_trace_enable(void*, int);
const NTTrace* nt_trace(void*, int*);
const int* nt_trace_vehicles(void*, int*);
}
