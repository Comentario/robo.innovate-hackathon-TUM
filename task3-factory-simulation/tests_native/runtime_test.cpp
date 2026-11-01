#include "EventRuntime.h"
#include <cassert>
#include <string>

using namespace brickflow;

Task worker(Clock& clock, Resource& resource, std::string& order, char id) {
    co_await resource.request();
    order += id;
    co_await clock.sleep(2);
    order += id;
    resource.release();
}
Task nested(Clock& clock, std::string& order) {
    order += 'n';
    co_await clock.sleep(1);
    order += 'N';
}
Task parent(Clock& clock, std::string& order) {
    co_await nested(clock, order);
    order += 'P';
}
Task fail() {
    throw std::runtime_error("Expected coroutine failure");
    co_return;
}
int main() {
    {
        Clock c; Resource r; r.init(c, []{}); std::string order;
        c.spawn(worker(c,r,order,'a')); c.spawn(worker(c,r,order,'b'));
        c.run(); assert(order == "aabb"); assert(c.now == 4); assert(r.free == 1);
    }
    {
        Clock c; std::string order;
        c.spawn(parent(c,order)); c.run(); assert(order=="nNP");
        auto e=signal(c); e->succeed();
        bool rejected=false; try { e->succeed(); } catch(...) { rejected=true; }
        assert(rejected);
    }
    {
        Clock c; c.spawn(fail()); bool rejected=false;
        try { c.run(); } catch(...) { rejected=true; } assert(rejected);
    }
}
