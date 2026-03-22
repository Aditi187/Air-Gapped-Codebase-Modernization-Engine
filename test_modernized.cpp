#include <iostream>
#include <memory>
#include <string>

struct Node {
    int id;
    std::string name;
    std::unique_ptr<Node> next;

    Node(int id, const std::string& name) : id(id), name(name) {}
};

struct LinkedList {
    std::unique_ptr<Node> head;

    void insertFront(int id, const std::string& name) {
        auto node = std::make_unique<Node>(id, name);
        node->next = std::move(head);
        head = std::move(node);
    }

    Node* findNode(int id) {
        auto current = head.get();
        while (current != nullptr) {
            if (current->id == id) {
                return current;
            }
            current = current->next.get();
        }
        return nullptr;
    }

    void deleteNode(int id) {
        if (head == nullptr) return;

        if (head->id == id) {
            head = std::move(head->next);
            return;
        }

        auto current = head.get();
        while (current->next != nullptr) {
            if (current->next->id == id) {
                current->next = std::move(current->next->next);
                return;
            }
            current = current->next.get();
        }
    }

    void printList() const {
        for (auto current = head.get(); current != nullptr; current = current->next.get()) {
            std::cout << current->id << " " << current->name << std::endl;
        }
    }
};

int main() {
    LinkedList list;
    list.insertFront(1, "Alice");
    list.insertFront(2, "Bob");
    list.insertFront(3, "Charlie");
    list.printList();

    auto result = list.findNode(2);
    if (result != nullptr) {
        std::cout << "Found: " << result->name << std::endl;
    }

    list.deleteNode(1);
    list.printList();

    return 0;
}