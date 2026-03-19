#include <algorithm>
#include <iostream>
#include <optional>
#include <string>
#include <string_view>

std::string GLOBAL_LOG_BUFFER;

struct LegacyRecord {
    int id{};
    std::string raw_data;
    std::size_t len{};
};

std::optional<LegacyRecord> load_record(int id) {
    if (id <= 0) {
        return std::nullopt;
    }

    constexpr std::string_view kRawData{"DEVICE_DATA_STREAM_0xCF"};

    LegacyRecord record{};
    record.id = id;
    record.raw_data.assign(kRawData.begin(), kRawData.end());
    record.len = record.raw_data.size();

    return record;
}

void process_data() {
    const auto rec = load_record(42);
    if (rec.has_value()) {
        std::cout << "Processing Record " << rec->id << ": " << rec->raw_data << "\n";
        return;
    }
    std::cout << "Failed to load record.\n";
}

int main() {
    process_data();
    return 0;
}