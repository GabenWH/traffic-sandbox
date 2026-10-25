// A test oracle consumer, not the C++ traffic engine. No Python runtime needed.
#include "value.hpp"

#include <array>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <utility>

namespace {
using Point = std::array<double, 2>;
using Route = std::vector<Point>;
using parity::require;

std::pair<Point, Point> position(const Route& route, double distance) {
    auto remaining = std::max(0.0, distance);
    Point heading{1, 0};
    for (std::size_t i = 1; i < route.size(); ++i) {
        const auto& a = route[i-1];
        const auto& b = route[i];
        const auto length = std::hypot(b[0] - a[0], b[1] - a[1]);
        if (length == 0) continue;
        heading = {(b[0]-a[0])/length, (b[1]-a[1])/length};
        if (remaining <= length) {
            const auto fraction = remaining/length;
            return {{a[0] + (b[0]-a[0])*fraction, a[1] + (b[1]-a[1])*fraction}, heading};
        }
        remaining -= length;
    }
    return {route.back(), heading};
}

bool near(double a, double b) { return std::abs(a-b) <= 1e-8 + 1e-12*std::max(std::abs(a),std::abs(b)); }

struct Checker {
    std::map<std::size_t, Route> routes;
    std::map<std::string, std::string> test_status;
    std::set<std::string> observed_tests;
    std::size_t assertions = 0, samples = 0, failures = 0;
    bool ended = false;

    void fail(const std::string& context, const std::string& message) {
        ++failures;
        if (failures <= 20) std::cerr << context << ": " << message << '\n';
    }

    void record(std::istream& input) {
        const auto type = parity::token(input);
        require(!ended, "record after END");
        if (type == "R") {
            const auto id = parity::count(input), count = parity::count(input);
            require(id > 0 && count >= 2, "invalid route");
            require(routes.find(id) == routes.end(), "duplicate route");
            Route route;
            for (std::size_t i = 0; i < count; ++i)
                route.push_back({parity::number(input), parity::number(input)});
            routes.emplace(id, std::move(route));
        } else if (type == "A") {
            const auto test = parity::unhex(parity::token(input));
            const auto file = parity::unhex(parity::token(input));
            const auto line = parity::count(input);
            const auto operation = parity::unhex(parity::token(input));
            const auto actual = parity::read_value(input);
            const auto expected = parity::read_value(input);
            const auto options = parity::read_value(input);
            ++assertions;
            observed_tests.insert(test);
            if (!parity::assertion(operation, actual, expected, options))
                fail(test + " " + file + ":" + std::to_string(line), operation + " failed");
        } else if (type == "P") {
            const auto test = parity::unhex(parity::token(input));
            const auto sample = parity::count(input);
            const auto car = parity::unhex(parity::token(input));
            const auto route_id = parity::count(input);
            const auto distance = parity::number(input);
            const auto speed = parity::number(input);
            const auto length = parity::number(input), width = parity::number(input);
            const auto total_length = parity::number(input);
            const Point actual{parity::number(input), parity::number(input)};
            const Point heading{parity::number(input), parity::number(input)};
            const auto state = parity::unhex(parity::token(input));
            const auto signal = parity::unhex(parity::token(input));
            const auto lane = parity::unhex(parity::token(input));
            const auto lane_distance = parity::number(input);
            const auto desired_speed = parity::number(input);
            const auto stopped_elapsed = parity::number(input);
            const auto wait_reason = parity::unhex(parity::token(input));
            const auto claim = parity::unhex(parity::token(input));
            (void)lane; (void)lane_distance; (void)wait_reason; (void)claim;
            require(sample == samples + 1, "motion sample missing or duplicated");
            ++samples;
            observed_tests.insert(test);
            const auto found = routes.find(route_id);
            require(found != routes.end(), "position references unknown route");
            const auto context = test + " car=" + car + " sample=" + std::to_string(sample);
            if (speed < 0 || length <= 0 || width <= 0 || total_length <= 0 ||
                desired_speed < 0 || stopped_elapsed < 0)
                fail(context, "invalid vehicle state");
            const std::set<std::string> states{
                "cruising", "approaching_stop", "stopped", "waiting_for_priority",
                "entering_intersection", "clearing_intersection"};
            if (!states.count(state) || (signal != "none" && signal != "left" && signal != "right"))
                fail(context, "invalid brain state or signal");
            const auto expected = position(found->second, distance);
            if (!near(actual[0], expected.first[0]) || !near(actual[1], expected.first[1]))
                fail(context, "position differs from route progress");
            if (!near(heading[0], expected.second[0]) || !near(heading[1], expected.second[1]))
                fail(context, "heading differs from route progress");
        } else if (type == "T") {
            const auto test = parity::unhex(parity::token(input));
            const auto status = parity::unhex(parity::token(input));
            require(test_status.emplace(test, status).second, "duplicate test result");
            const std::set<std::string> statuses{
                "passed", "skipped", "expected_failure", "failed", "error", "unexpected_success"};
            require(statuses.count(status) != 0, "unknown Python test status");
            if (status == "failed" || status == "error" || status == "unexpected_success")
                fail(test, "Python regression " + status);
        } else if (type == "END") {
            const auto expected_assertions = parity::count(input);
            const auto expected_samples = parity::count(input);
            const auto expected_tests = parity::count(input);
            require(assertions == expected_assertions && samples == expected_samples &&
                    test_status.size() == expected_tests, "incomplete corpus counts");
            require(assertions > 0, "empty assertion corpus");
            for (const auto& test : observed_tests)
                require(test_status.count(test) != 0, "missing test result for " + test);
            ended = true;
        } else {
            throw std::runtime_error("unknown record type: " + type);
        }
        std::string extra;
        require(!(input >> extra), "unexpected trailing fields");
    }
};
} // namespace

int main(int argc, char** argv) {
    if (argc != 2) { std::cerr << "Usage: check_python_baseline corpus.parity\n"; return 2; }
    std::size_t line_number = 1;
    try {
        std::ifstream source(argv[1]);
        require(source.good(), "cannot open corpus");
        std::string line;
        require(bool(std::getline(source, line)) && line == "TRAFFIC_PARITY 1", "invalid corpus header");
        Checker checker;
        while (std::getline(source, line)) {
            ++line_number;
            std::istringstream input(line);
            checker.record(input);
        }
        require(checker.ended, "missing END record (truncated corpus)");
        std::size_t skipped = 0;
        for (const auto& result : checker.test_status) if (result.second == "skipped") ++skipped;
        std::cout << "Native baseline: " << checker.test_status.size() << " Python test results ("
                  << skipped << " skipped), " << checker.assertions << " regression assertions, "
                  << checker.samples << " vehicle position/heading samples, "
                  << checker.failures << " failures\n";
        return checker.failures == 0 ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << "Corpus line " << line_number << ": " << error.what() << '\n';
        return 2;
    }
}
