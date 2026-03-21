#include <iostream>
#include <string>
#include <vector>
#include <memory>

class Shape {
public:
    std::string color;
    Shape(const std::string& c) : color(c) {}
    virtual ~Shape() = default;
    virtual void draw() = 0;
};

class Circle : public Shape {
public:
    Circle(const std::string& c) : Shape(c) {}
    void draw() override {
        std::cout << "Drawing Circle (" << color << ")" << std::endl;
    }
};

class Rectangle : public Shape {
public:
    Rectangle(const std::string& c) : Shape(c) {}
    void draw() override {
        std::cout << "Drawing Rectangle (" << color << ")" << std::endl;
    }
};

class ShapeList {
public:
    std::vector<std::unique_ptr<Shape>> shapes;
    ShapeList() = default;
    ~ShapeList() = default;
    void add(std::unique_ptr<Shape> s) {
        shapes.push_back(std::move(s));
    }
    void drawAll() const {
        for (const auto& shape : shapes) {
            shape->draw();
        }
    }
};

int main() {
    ShapeList list;
    list.add(std::make_unique<Circle>("Red"));
    list.add(std::make_unique<Rectangle>("Blue"));
    list.drawAll();
    return 0;
}