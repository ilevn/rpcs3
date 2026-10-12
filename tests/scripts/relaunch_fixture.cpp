// Standalone Linux process-launch fixture. RPCS3 logging/filesystem dependencies are stubbed.
#include <cassert>
#include <cerrno>
#include <chrono>
#include <cstring>
#include <ctime>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
#include <spawn.h>
#include <unistd.h>
#include <sys/wait.h>
using usz = size_t;
using u32 = uint32_t;
extern char** environ;
static bool fail_spawn = false, fail_readlink = false, interrupt_readlink = false;
static int copies = 0, errors = 0;
static bool g_frame_hook_installed = false;
struct logger { template<class... T> void error(T...) { ++errors; } template<class... T> void success(T...) {} } rb_log;
namespace fs { std::string get_log_dir() { return "/tmp/"; } bool copy_file(const std::string&, const std::string&, bool) { ++copies; return true; } int g_tls_error = 0; }
namespace fmt { template<class... T> std::string format(T...) { return "archive"; } }
extern "C" int __real_posix_spawn(pid_t*, const char*, const posix_spawn_file_actions_t*, const posix_spawnattr_t*, char* const[], char* const[]);
extern "C" int __wrap_posix_spawn(pid_t* pid, const char* path, const posix_spawn_file_actions_t* actions, const posix_spawnattr_t* attrs, char* const argv[], char* const envp[]) {
    if (fail_spawn) return EACCES;
    return __real_posix_spawn(pid, path, actions, attrs, argv, envp);
}
extern "C" ssize_t __real_readlink(const char*, char*, size_t);
extern "C" ssize_t __wrap_readlink(const char* path, char* out, size_t size) {
    if (fail_readlink || interrupt_readlink) { errno = fail_readlink ? ENOENT : EINTR; interrupt_readlink = false; return -1; }
    return __real_readlink(path, out, size);
}
// The runner extracts this function from rb_input.cpp; its implementation is not copied here.
#include "relaunch_under_test.inc"

int main(int argc, char** argv) {
    alarm(10);
    if (argc > 1) {
        assert(argc == 3);
        assert(std::string(argv[1]) == "--");
        assert(std::string(argv[2]) == std::getenv("RB_RELAUNCH_EXPECT"));
        assert(std::string(argv[0]) != "/proc/self/exe");
        assert(std::string(std::getenv("RB_RELAUNCH_INHERITED")) == "preserved");
        return 0;
    }
    assert(!relaunch_for_boot("unused"));
    assert(copies == 0);
    g_frame_hook_installed = true;
    fail_readlink = true;
    assert(!relaunch_for_boot("unused"));
    assert(copies == 0);
    fail_readlink = false;
    fail_spawn = true;
    assert(!relaunch_for_boot("unused"));
    assert(copies == 1);
    fail_spawn = false;
    setenv("RB_RELAUNCH_INHERITED", "preserved", 1);
    const char* paths[] = {"/tmp/game path \"quotes\" 'apostrophe' $(no_shell); literal", "--leading-dash", "Tekken-\xC4\x8D/\xE6\xB8\xB8\xE6\x88\x8F"};
    for (const char* path : paths) {
        setenv("RB_RELAUNCH_EXPECT", path, 1);
        interrupt_readlink = true;
        assert(relaunch_for_boot(path));
        int status = 0;
        assert(waitpid(-1, &status, 0) > 0);
        assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
    }
    assert(copies == 4);
    assert(errors == 2);
    puts("PASS: no relaunch without hook; readlink/spawn failure; EINTR; exact argv; Unicode; inherited environment; log preservation; long executable path");
}
