#pragma once

// Native deterministic discrete-event kernel. No Unreal, Python or JS runtime.
#include <coroutine>
#include <cstdint>
#include <deque>
#include <exception>
#include <functional>
#include <memory>
#include <queue>
#include <stdexcept>
#include <utility>
#include <vector>

namespace brickflow {
struct Task {
    struct promise_type;
    using Handle = std::coroutine_handle<promise_type>;
    struct promise_type {
        std::coroutine_handle<> continuation{};
        std::exception_ptr error;
        Task get_return_object() { return Task{Handle::from_promise(*this)}; }
        std::suspend_always initial_suspend() noexcept { return {}; }
        struct Final {
            bool await_ready() noexcept { return false; }
            std::coroutine_handle<> await_suspend(Handle h) noexcept {
                return h.promise().continuation ? h.promise().continuation : std::noop_coroutine();
            }
            void await_resume() noexcept {}
        };
        Final final_suspend() noexcept { return {}; }
        void return_void() noexcept {}
        void unhandled_exception() noexcept { error = std::current_exception(); }
    };
    Handle handle;
    explicit Task(Handle h) : handle(h) {}
    Task(Task&& other) noexcept : handle(std::exchange(other.handle, {})) {}
    Task(const Task&) = delete;
    ~Task() { if (handle) handle.destroy(); }
    struct Awaiter {
        Handle handle;
        ~Awaiter() { if (handle) handle.destroy(); }
        bool await_ready() noexcept { return false; }
        std::coroutine_handle<> await_suspend(std::coroutine_handle<> parent) noexcept {
            handle.promise().continuation = parent;
            return handle;
        }
        void await_resume() {
            if (handle.promise().error) std::rethrow_exception(handle.promise().error);
        }
    };
    Awaiter operator co_await() && { return Awaiter{std::exchange(handle, {})}; }
};

class Clock {
    struct Scheduled {
        double time;
        std::uint64_t serial;
        std::function<void()> callback;
    };
    struct Later {
        bool operator()(const Scheduled& a, const Scheduled& b) const {
            return a.time == b.time ? a.serial > b.serial : a.time > b.time;
        }
    };
    std::priority_queue<Scheduled, std::vector<Scheduled>, Later> queue;
    std::vector<Task> tasks;
    std::uint64_t serial = 0;
public:
    double now = 0;
    std::uint64_t executed = 0;
    bool horizonReached = false;
    void at(double time, std::function<void()> callback) {
        if (time < now - 1e-9) throw std::runtime_error("Event scheduled in the past");
        queue.push({time, serial++, std::move(callback)});
    }
    void spawn(Task task) {
        auto h = task.handle;
        tasks.push_back(std::move(task));
        at(now, [h] { h.resume(); });
    }
    struct Sleep {
        Clock& clock;
        double seconds;
        bool await_ready() const noexcept { return false; }
        void await_suspend(std::coroutine_handle<> handle) const {
            if (seconds < 0) throw std::runtime_error("Negative process duration");
            clock.at(clock.now + seconds, [handle] { handle.resume(); });
        }
        void await_resume() const noexcept {}
    };
    Sleep sleep(double seconds) { return {*this, seconds}; }
    void auditTasks() {
        for (auto& task : tasks) if (task.handle.done() && task.handle.promise().error)
            std::rethrow_exception(task.handle.promise().error);
    }
    void run(double horizon = 24000) {
        while (!queue.empty()) {
            auto item = queue.top(); queue.pop();
            now = item.time;
            if (now > horizon) { horizonReached = true; break; }
            item.callback(); ++executed;
            if (executed % 10000 == 0) auditTasks();
        }
        auditTasks();
    }
};

struct Event {
    Clock& clock;
    bool done = false;
    std::vector<std::coroutine_handle<>> waiting;
    explicit Event(Clock& c) : clock(c) {}
    void succeed() {
        if (done) throw std::runtime_error("Duplicate confirmation");
        done = true;
        for (auto h : waiting) clock.at(clock.now, [h] { h.resume(); });
        waiting.clear();
    }
};
using Signal = std::shared_ptr<Event>;
inline Signal signal(Clock& clock, bool complete = false) {
    auto e = std::make_shared<Event>(clock);
    if (complete) e->succeed();
    return e;
}
struct EventAwaiter {
    Signal event;
    bool await_ready() const noexcept { return false; }
    void await_suspend(std::coroutine_handle<> handle) const {
        if (event->done) event->clock.at(event->clock.now, [handle] { handle.resume(); });
        else event->waiting.push_back(handle);
    }
    void await_resume() const noexcept {}
};
inline EventAwaiter operator co_await(Signal event) { return {std::move(event)}; }

struct Resource {
    Clock* clock = nullptr;
    int free = 1;
    std::deque<Signal> waiting;
    std::function<void()> changed;
    void init(Clock& c, std::function<void()> callback, int capacity = 1) {
        clock = &c; changed = std::move(callback); free = capacity;
    }
    Signal request() {
        auto e = signal(*clock);
        if (free) { --free; e->succeed(); } else waiting.push_back(e);
        return e;
    }
    void release() {
        if (waiting.empty()) ++free;
        else { auto e = waiting.front(); waiting.pop_front(); e->succeed(); }
        changed();
    }
};
}
