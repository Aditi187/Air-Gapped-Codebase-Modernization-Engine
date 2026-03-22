#include <iostream>
#include <cstring>
#include <cstdlib>

typedef struct Node
{
    int id;
    char name[100];
    struct Node* next;

} Node;


typedef struct LinkedList
{
    Node* head;

} LinkedList;


void initList(LinkedList* list)
{
    list->head = NULL;
}


Node* createNode(int id, const char* name)
{
    Node* node = (Node*) malloc(sizeof(Node));

    if(node == NULL)
    {
        std::cout << "Memory allocation failed\n";
        exit(1);
    }

    node->id = id;

    strcpy(node->name, name);

    node->next = NULL;

    return node;
}


void insertFront(LinkedList* list, int id, const char* name)
{
    Node* node = createNode(id, name);

    node->next = list->head;

    list->head = node;
}


Node* findNode(LinkedList* list, int id)
{
    Node* temp = list->head;

    while(temp != NULL)
    {
        if(temp->id == id)
        {
            return temp;
        }

        temp = temp->next;
    }

    return NULL;
}


void deleteNode(LinkedList* list, int id)
{
    Node* current = list->head;

    Node* prev = NULL;

    while(current != NULL)
    {
        if(current->id == id)
        {
            if(prev == NULL)
            {
                list->head = current->next;
            }
            else
            {
                prev->next = current->next;
            }

            free(current);

            return;
        }

        prev = current;

        current = current->next;
    }
}


void printList(LinkedList* list)
{
    Node* temp = list->head;

    while(temp != NULL)
    {
        std::cout << temp->id << " "
                  << temp->name << std::endl;

        temp = temp->next;
    }
}


void freeList(LinkedList* list)
{
    Node* temp = list->head;

    while(temp != NULL)
    {
        Node* next = temp->next;

        free(temp);

        temp = next;
    }

    list->head = NULL;
}


int main()
{
    LinkedList list;

    initList(&list);

    insertFront(&list, 1, "Alice");

    insertFront(&list, 2, "Bob");

    insertFront(&list, 3, "Charlie");

    printList(&list);

    Node* result = findNode(&list, 2);

    if(result != NULL)
    {
        std::cout << "Found: "
                  << result->name
                  << std::endl;
    }

    deleteNode(&list, 1);

    printList(&list);

    freeList(&list);

    return 0;
}