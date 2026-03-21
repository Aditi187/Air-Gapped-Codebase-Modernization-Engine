#include <iostream>
#include <string>
#include <vector>
#include <memory>

class Shape {
public:
    std::string color;
    Shape(const char* c) : color(c ? c : "") {}
    virtual ~Shape() = default;
    virtual void draw() = 0;
};

class Circle : public Shape {
public:
    Circle(const char* c) : Shape(c) {}
    void draw() override {
        std::cout << "Drawing Circle (" << color << ")" << std::endl;
    }
};

class Rectangle : public Shape {
public:
    Rectangle(const char* c) : Shape(c) {}
    void draw() override {
        std::cout << "Drawing Rectangle (" << color << ")" << std::endl;
    }
};

class ShapeList {
public:
    std::vector<std::unique_ptr<Shape>> shapes;
    ShapeList() = default;
    ~ShapeList() = default;
    void add(Shape* s) {
        shapes.push_back(std::unique_ptr<Shape>(s));
    }
    void drawAll() {
        for (const auto& s : shapes) {
            s->draw();
        }
    }
};

int main() {
    ShapeList list;
    list.add(std::make_unique<Circle>("Red").release());
    list.add(std::make_unique<Rectangle>("Blue").release());
    list.drawAll();
    return 0;
}