#include <iostream>
#include <string>
#include <vector>
#include <memory>

class Student {
public:
    std::string name;
    int age;
    Student(const std::string& n, int a) : name(n), age(a) {}
    void print() const {
        std::cout << "Name: " << name << ", Age: " << age << std::endl;
    }
};

class StudentManager {
private:
    std::vector<std::unique_ptr<Student>> students_;
public:
    void addStudent(std::string name, int age) {
        students_.emplace_back(std::make_unique<Student>(std::move(name), age));
    }
    void printAll() const {
        for (const auto& student : students_) {
            student->print();
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