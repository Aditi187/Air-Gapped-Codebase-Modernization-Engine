#include <fstream>
#include <iostream>
#include <string>
#include <ctime>
#include <memory>

class Logger {
public:
    Logger(const std::string& filename) : file_(filename, std::ios_base::app) {}

    void log_message(const std::string& msg) {
        if (file_.is_open()) {
            auto now = std::time(nullptr);
            auto timeinfo = std::localtime(&now);
            char buffer[80];
            std::strftime(buffer, sizeof(buffer), "%H:%M:%S", timeinfo);
            file_ << "[" << buffer << "] " << msg << std::endl;
        }
    }

    ~Logger() = default;

private:
    std::ofstream file_;
};

int main() {
    Logger myLogger("app.log");
    myLogger.log_message("System started");
    myLogger.log_message("Processing data...");
    return 0;
}