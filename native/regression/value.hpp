// Test-only typed operands for replaying Python's existing regression assertions.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <istream>
#include <stdexcept>
#include <string>
#include <vector>

namespace parity {

inline void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}

inline std::string unhex(const std::string& token) {
    if (token == "-") return "";
    require(token.size() % 2 == 0, "invalid hex string");
    auto digit = [](char c) -> unsigned {
        if (c >= '0' && c <= '9') return unsigned(c - '0');
        if (c >= 'a' && c <= 'f') return unsigned(c - 'a' + 10);
        throw std::runtime_error("invalid hex digit");
    };
    std::string result;
    for (std::size_t i = 0; i < token.size(); i += 2)
        result.push_back(char(16 * digit(token[i]) + digit(token[i+1])));
    return result;
}

inline std::string token(std::istream& input) {
    std::string value;
    require(bool(input >> value), "truncated record");
    return value;
}

inline std::size_t count(std::istream& input) {
    const auto raw = token(input);
    require(!raw.empty() && raw.find_first_not_of("0123456789") == std::string::npos,
            "invalid count");
    std::size_t consumed = 0;
    const auto number = std::stoull(raw, &consumed);
    require(consumed == raw.size() && number <= 10000000, "count outside supported range");
    return std::size_t(number);
}

inline double number(std::istream& input) {
    const auto raw = token(input);
    std::size_t consumed = 0;
    const auto value = std::stod(raw, &consumed);
    require(consumed == raw.size() && std::isfinite(value), "nonfinite/invalid number");
    return value;
}

struct Value {
    char kind = 'n';
    double numeric = 0;
    std::string text;
    std::vector<Value> items;

    bool is_number() const { return kind == 'b' || kind == 'i' || kind == 'f'; }
    bool truth() const {
        if (kind == 'n') return false;
        if (is_number()) return numeric != 0;
        if (kind == 's') return !text.empty();
        return !items.empty();
    }
};

inline Value read_value(std::istream& input, unsigned depth = 0) {
    require(depth <= 30, "operand nesting exceeds 30");
    const auto raw = token(input);
    require(raw.size() == 1, "invalid value tag");
    Value value;
    value.kind = raw.front();
    if (value.kind == 'n') return value;
    if (value.is_number()) {
        value.numeric = number(input);
        if (value.kind == 'b') require(value.numeric == 0 || value.numeric == 1, "invalid boolean");
        if (value.kind == 'i') require(std::trunc(value.numeric) == value.numeric &&
                                      std::abs(value.numeric) <= 9007199254740992.0, "invalid integer");
    } else if (value.kind == 's') {
        value.text = unhex(token(input));
    } else {
        require(value.kind == 'l' || value.kind == 't' || value.kind == 'e' || value.kind == 'm',
                "unknown value tag");
        const auto size = count(input) * (value.kind == 'm' ? 2 : 1);
        for (std::size_t i = 0; i < size; ++i) value.items.push_back(read_value(input, depth+1));
    }
    return value;
}

inline bool equal(const Value& a, const Value& b);

inline bool multiset_equal(const std::vector<Value>& a, const std::vector<Value>& b) {
    if (a.size() != b.size()) return false;
    std::vector<bool> used(b.size(), false);
    for (const auto& item : a) {
        bool found = false;
        for (std::size_t j = 0; j < b.size(); ++j) {
            if (!used[j] && equal(item, b[j])) { used[j] = true; found = true; break; }
        }
        if (!found) return false;
    }
    return true;
}

inline bool equal(const Value& a, const Value& b) {
    if (a.is_number() && b.is_number()) return a.numeric == b.numeric;
    if (a.kind != b.kind) return false;
    if (a.kind == 'n') return true;
    if (a.kind == 's') return a.text == b.text;
    if (a.items.size() != b.items.size()) return false;
    if (a.kind == 'e') return multiset_equal(a.items, b.items);
    if (a.kind == 'm') {
        for (std::size_t i = 0; i < a.items.size(); i += 2) {
            bool found = false;
            for (std::size_t j = 0; j < b.items.size(); j += 2) {
                if (equal(a.items[i], b.items[j]) && equal(a.items[i+1], b.items[j+1])) {
                    found = true; break;
                }
            }
            if (!found) return false;
        }
        return true;
    }
    for (std::size_t i = 0; i < a.items.size(); ++i)
        if (!equal(a.items[i], b.items[i])) return false;
    return true;
}

inline bool contains(const Value& container, const Value& item) {
    if (container.kind == 's') {
        require(item.kind == 's', "string membership needs a string operand");
        return container.text.find(item.text) != std::string::npos;
    }
    require(container.kind == 'l' || container.kind == 't' ||
            container.kind == 'e' || container.kind == 'm', "unsupported membership operand");
    const auto stride = container.kind == 'm' ? 2 : 1;
    for (std::size_t i = 0; i < container.items.size(); i += stride)
        if (equal(container.items[i], item)) return true;
    return false;
}

inline int compare(const Value& a, const Value& b) {
    if (a.is_number() && b.is_number())
        return a.numeric < b.numeric ? -1 : a.numeric > b.numeric ? 1 : 0;
    if (a.kind == 's' && b.kind == 's')
        return a.text < b.text ? -1 : a.text > b.text ? 1 : 0;
    if ((a.kind == 'l' || a.kind == 't') && a.kind == b.kind) {
        for (std::size_t i = 0; i < std::min(a.items.size(), b.items.size()); ++i) {
            if (!equal(a.items[i], b.items[i])) return compare(a.items[i], b.items[i]);
        }
        return a.items.size() < b.items.size() ? -1 : a.items.size() > b.items.size() ? 1 : 0;
    }
    throw std::runtime_error("unsupported ordered operands");
}

inline std::vector<Value> iterable_items(const Value& value) {
    if (value.kind == 's') {
        std::vector<Value> result;
        for (std::size_t i = 0; i < value.text.size();) {
            const auto first = static_cast<unsigned char>(value.text[i]);
            const std::size_t width = first < 0x80 ? 1 : first < 0xe0 ? 2 : first < 0xf0 ? 3 : 4;
            require(i + width <= value.text.size(), "invalid UTF-8 character");
            Value character;
            character.kind = 's';
            character.text = value.text.substr(i, width);
            result.push_back(character);
            i += width;
        }
        return result;
    }
    if (value.kind == 'm') {
        std::vector<Value> keys;
        for (std::size_t i = 0; i < value.items.size(); i += 2) keys.push_back(value.items[i]);
        return keys;
    }
    require(value.kind == 'l' || value.kind == 't' || value.kind == 'e', "operand is not iterable");
    return value.items;
}

inline bool assertion(const std::string& operation, const Value& a, const Value& b,
                      const Value& options) {
    if (operation == "assertEqual" || operation == "assertListEqual" ||
        operation == "assertTupleEqual" || operation == "assertDictEqual" ||
        operation == "assertSetEqual" ||
        operation == "assertMultiLineEqual") return equal(a, b);
    if (operation == "assertSequenceEqual") {
        const auto first = iterable_items(a), second = iterable_items(b);
        if (first.size() != second.size()) return false;
        for (std::size_t i = 0; i < first.size(); ++i)
            if (!equal(first[i], second[i])) return false;
        return true;
    }
    if (operation == "assertNotEqual") return !equal(a, b);
    if (operation == "assertTrue") return a.truth();
    if (operation == "assertFalse") return !a.truth();
    if (operation == "assertIsNone") return a.kind == 'n';
    if (operation == "assertIsNotNone") return a.kind != 'n';
    if (operation == "assertIn") return contains(b, a);
    if (operation == "assertNotIn") return !contains(b, a);
    if (operation == "assertGreater") return compare(a, b) > 0;
    if (operation == "assertGreaterEqual") return compare(a, b) >= 0;
    if (operation == "assertLess") return compare(a, b) < 0;
    if (operation == "assertLessEqual") return compare(a, b) <= 0;
    if (operation == "assertCountEqual") return multiset_equal(iterable_items(a), iterable_items(b));
    if (operation == "assertAlmostEqual") {
        require(a.is_number() && b.is_number(), "almost-equal needs numeric operands");
        require(options.kind == 'l' && options.items.size() == 2, "invalid tolerance options");
        if (equal(a, b)) return true;
        const auto difference = std::abs(a.numeric - b.numeric);
        const auto& delta = options.items[1];
        if (delta.kind != 'n') {
            require(delta.is_number(), "delta must be numeric");
            return difference <= delta.numeric;
        }
        require(options.items[0].is_number(), "places must be numeric");
        // Compare against the decimal half threshold without rounding a scaled
        // double first: 0.005*100 becomes exactly 0.5, but Python round(0.005,2)
        // is 0.01 because the original binary float is slightly above the half.
        const auto half = 0.5L * std::pow(10.0L, -static_cast<long double>(options.items[0].numeric));
        return static_cast<long double>(difference) <= half;
    }
    throw std::runtime_error("unknown assertion: " + operation);
}

} // namespace parity
