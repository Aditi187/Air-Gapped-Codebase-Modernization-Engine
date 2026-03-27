#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MAX_SIZE 100
#define MULTIPLY(a,b) ((a)*(b))

typedef struct Node {
    int id;
    char name[50];
    struct Node* next;
} Node;

typedef struct Logger {
    FILE* file;
    char* buffer;
} Logger;


void init_logger(Logger* logger, const char* filename) {
    logger->file = fopen(filename, "a");

    logger->buffer = (char*) malloc(256);

    if(logger->buffer != NULL) {
        strcpy(logger->buffer, "LOG START\n");
        fprintf(logger->file, "%s", logger->buffer);
    }
}


void log_message(Logger* logger, const char* message) {

    if(logger->file != NULL) {

        time_t rawtime;

        struct tm* timeinfo;

        time(&rawtime);

        timeinfo = localtime(&rawtime);

        fprintf(
            logger->file,
            "[%d:%d:%d] %s\n",
            timeinfo->tm_hour,
            timeinfo->tm_min,
            timeinfo->tm_sec,
            message
        );

        fflush(logger->file);
    }
}


void close_logger(Logger* logger) {

    if(logger->file != NULL) {

        fclose(logger->file);
    }

    if(logger->buffer != NULL) {

        free(logger->buffer);
    }
}


Node* create_node(int id, const char* name) {

    Node* node = (Node*) malloc(sizeof(Node));

    node->id = id;

    strcpy(node->name, name);

    node->next = NULL;

    return node;
}


void append_node(Node* head, int id, const char* name) {

    Node* new_node = create_node(id, name);

    Node* temp = head;

    while(temp->next != NULL) {

        temp = temp->next;
    }

    temp->next = new_node;
}


void print_list(Node* head) {

    Node* temp = head;

    while(temp != NULL) {

        printf("ID: %d Name: %s\n", temp->id, temp->name);

        temp = temp->next;
    }
}


void free_list(Node* head) {

    Node* temp = head;

    while(temp != NULL) {

        Node* next = temp->next;

        free(temp);

        temp = next;
    }
}


void legacy_string_ops() {

    char buffer[MAX_SIZE];

    strcpy(buffer, "Legacy string example");

    int len = strlen(buffer);

    printf("String length = %d\n", len);
}


void legacy_array_ops() {

    int* numbers = (int*) malloc(5 * sizeof(int));

    for(int i = 0; i < 5; i++) {

        numbers[i] = MULTIPLY(i, 10);
    }

    for(int i = 0; i < 5; i++) {

        printf("%d ", numbers[i]);
    }

    printf("\n");

    free(numbers);
}


void legacy_file_read() {

    FILE* file = fopen("data.txt", "r");

    if(file == NULL) {

        printf("file not found\n");

        return;
    }

    char line[128];

    while(fgets(line, sizeof(line), file)) {

        printf("%s", line);
    }

    fclose(file);
}


class LegacyClass {

public:

    int* values;

    LegacyClass() {

        values = new int[3];

        for(int i = 0; i < 3; i++) {

            values[i] = i * 2;
        }
    }

    ~LegacyClass() {

        delete[] values;
    }

    void print() {

        for(int i = 0; i < 3; i++) {

            printf("%d\n", values[i]);
        }
    }
};


int main() {

    Logger logger;

    init_logger(&logger, "app.log");

    log_message(&logger, "Program started");


    Node* head = create_node(1, "Alice");

    append_node(head, 2, "Bob");

    append_node(head, 3, "Charlie");

    print_list(head);


    legacy_string_ops();

    legacy_array_ops();

    legacy_file_read();


    LegacyClass obj;

    obj.print();


    log_message(&logger, "Program finished");

    close_logger(&logger);

    free_list(head);

    return 0;
}