#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef struct Logger {
    FILE* file;
    char* buffer;
} Logger;

void init_logger(Logger* l, const char* filename) {
    l->file = fopen(filename, "a");
    l->buffer = (char*)malloc(1024); // Manual buffer
}

void log_message(Logger* l, const char* msg) {
    if (l->file) {
        time_t rawtime;
        struct tm* timeinfo;
        time(&rawtime);
        timeinfo = localtime(&rawtime);
        
        fprintf(l->file, "[%d:%d:%d] %s\n", 
                timeinfo->tm_hour, timeinfo->tm_min, timeinfo->tm_sec, msg);
        fflush(l->file);
    }
}

void close_logger(Logger* l) {
    if (l->file) {
        fclose(l->file);
    }
    if (l->buffer) {
        free(l->buffer);
    }
}

int main() {
    Logger myLogger;
    init_logger(&myLogger, "app.log");
    log_message(&myLogger, "System started");
    log_message(&myLogger, "Processing data...");
    close_logger(&myLogger);
    return 0;
}