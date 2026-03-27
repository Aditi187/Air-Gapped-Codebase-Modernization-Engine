#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <memory>
#include <ctime>
#include <cstring>
#define MAX_SIZE 100

class Node {
public:
    int id;
    std::string name;
    std::unique_ptr<Node> next;
    Node(int id, std::string_view name) : id(id), name(name) {}
};

class Logger {
public:
    mutable std::ofstream file;
    mutable std::string buffer;
    void init(std::string_view filename) {
        file.open(filename.data(), std::ios_base::app);
        buffer = "LOG START\n";
        file << buffer;
    }
    void log_message(std::string_view message) {
        if (file.is_open()) {
            std::time_t rawtime;
            std::time(&rawtime);
            #ifdef _WIN32
            std::tm timeinfo;
            localtime_s(&timeinfo, &rawtime);
            #else
            std::tm* timeinfo = std::localtime(&rawtime);
            #endif
            file << "[" << timeinfo.tm_hour << ":" << timeinfo.tm_min << ":" << timeinfo.tm_sec << "] " << message << "\n";
            file.flush();
        }
    }
    void close() {
        if (file.is_open()) {
            file.close();
        }
    }
};

std::unique_ptr<Node> create_node(int id, std::string_view name) {
    return std::make_unique<Node>(id, name);
}

void append_node(std::unique_ptr<Node>& head, int id, std::string_view name) {
    if (!head) {
        head = create_node(id, name);
    } else {
        auto temp = head.get();
        while (temp->next) {
            temp = temp->next.get();
        }
        temp->next = create_node(id, name);
    }
}

void print_list(const std::unique_ptr<Node>& head) {
    auto temp = head.get();
    while (temp) {
        std::cout << "ID: " << temp->id << " Name: " << temp->name << "\n";
        temp = temp->next.get();
    }
}

void modern_string_ops() {
    std::string buffer = "Modern string example";
    std::cout << "String length = " << buffer.length() << "\n";
}

void modern_array_ops() {
    std::vector<int> numbers(5);
    for (auto& num : numbers) {
        num = 0; // Initialize with 0 instead of nullptr
    }
    for (size_t i = 0; i < numbers.size(); ++i) {
        numbers[i] = i * 10;
    }
    for (const auto& num : numbers) {
        std::cout << num << " ";
    }
    std::cout << "\n";
}

void modern_file_read() {
    std::ifstream file("data.txt");
    if (!file.is_open()) {
        std::cout << "file not found\n";
        return;
    }
    std::string line;
    while (std::getline(file, line)) {
        std::cout << line << "\n";
    }
}

class ModernClass {
public:
    std::vector<int> values;
    ModernClass() {
        values.resize(3);
        for (auto& val : values) {
            val = 0; // Initialize with 0 instead of nullptr
        }
        for (size_t i = 0; i < values.size(); ++i) {
            values[i] = i * 2;
        }
    }
    void print() const {
        for (const auto& val : values) {
            std::cout << val << "\n";
        }
    }
};

int main() {
    Logger logger;
    logger.init("app.log");
    logger.log_message("Program started");
    std::unique_ptr<Node> head = create_node(1, "Alice");
    append_node(head, 2, "Bob");
    append_node(head, 3, "Charlie");
    print_list(head);
    modern_string_ops();
    modern_array_ops();
    modern_file_read();
    ModernClass obj;
    obj.print();
    logger.log_message("Program finished");
    logger.close();
    return 0;
}