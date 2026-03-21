#include <iostream>
#include <cstring>
#include <cstdlib>

class Student {
public:
    char* name;
    int age;

    Student(const char* n, int a) {
        name = (char*)malloc(strlen(n) + 1);
        strcpy(name, n);
        age = a;
    }

    ~Student() {
        free(name);
    }

    void print() {
        std::cout << "Name: " << name << ", Age: " << age << std::endl;
    }
};

class StudentManager {
private:
    Student** students;
    int size;
    int capacity;

public:
    StudentManager() {
        size = 0;
        capacity = 2;
        students = (Student**)malloc(sizeof(Student*) * capacity);
    }

    ~StudentManager() {
        for (int i = 0; i < size; i++) {
            delete students[i];
        }
        free(students);
    }

    void addStudent(const char* name, int age) {
        if (size == capacity) {
            capacity *= 2;
            students = (Student**)realloc(students, sizeof(Student*) * capacity);
        }
        students[size++] = new Student(name, age);
    }

    void printAll() {
        for (int i = 0; i < size; i++) {
            students[i]->print();
        }
    }
};

int main() {
    StudentManager manager;

    manager.addStudent("Alice", 20);
    manager.addStudent("Bob", 22);
    manager.addStudent("Charlie", 21);

    manager.printAll();

    return 0;
}