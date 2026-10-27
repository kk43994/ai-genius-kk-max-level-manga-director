#import <Cocoa/Cocoa.h>
#include <mach-o/dyld.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

static void showError(void) {
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
    [NSApp activateIgnoringOtherApps:YES];
    NSAlert *alert = [[NSAlert alloc] init];
    alert.messageText = @"资产实验室暂时无法打开";
    alert.informativeText = @"请先退出正在运行的工作台，再双击桌面图标重试。如果仍然无法打开，请联系交付人员。已有项目和账号资料不会被替换。";
    [alert addButtonWithTitle:@"知道了"];
    [alert runModal];
}

int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc == 2 && strcmp(argv[1], "--show-error") == 0) {
            showError(); return 1;
        }
        uint32_t size = 0;
        _NSGetExecutablePath(NULL, &size);
        char *buffer = malloc(size);
        if (!buffer || _NSGetExecutablePath(buffer, &size)) { showError(); return 1; }
        NSString *binary = [[[NSString stringWithUTF8String:buffer] stringByResolvingSymlinksInPath] stringByStandardizingPath];
        free(buffer);
        NSString *contents = [[binary stringByDeletingLastPathComponent] stringByDeletingLastPathComponent];
        NSString *server = [contents stringByAppendingPathComponent:@"Resources/runtime/AssetLabServer"];
        if (access(server.fileSystemRepresentation, X_OK) != 0) { showError(); return 1; }
        char **args = calloc((size_t)argc + 1, sizeof(char *));
        if (!args) { showError(); return 1; }
        args[0] = (char *)server.fileSystemRepresentation;
        for (int i = 1; i < argc; i++) args[i] = argv[i];
        pid_t pid = fork();
        if (pid < 0) { free(args); showError(); return 1; }
        if (pid == 0) {
            setsid();
            int null = open("/dev/null", O_RDWR);
            if (null >= 0) { dup2(null, 0); dup2(null, 1); dup2(null, 2); if (null > 2) close(null); }
            setenv("PYINSTALLER_RESET_ENVIRONMENT", "1", 1);
            execv(args[0], args);
            _exit(127);
        }
        free(args);
        // Exit this app so every later desktop double-click starts a fresh opener.
        return 0;
    }
}
