#!/usr/bin/env python3
"""Test RPCS3's actual CLI boot-path consumption with QtCore, without the emulator.

Usage: python3 tests/scripts/test_cli_boot.py [--cxx c++]
Requires a C++20 compiler and Qt6Core development files discoverable by pkg-config.

The fixture extracts argument splitting, boot-path selection, guest argument
propagation, and path normalization from rpcs3.cpp. It uses QCoreApplication and
QCommandLineParser, with logging and RPCS3's checked indexing stubbed. It does not
start the GUI, load a game, or test Emulator::BootGame itself.
"""

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import tempfile


def extract(source, start, end):
    if source.count(start) != 1:
        raise RuntimeError(f"Cannot uniquely locate extraction marker: {start!r}")
    begin = source.index(start)
    return source[begin:source.index(end, begin)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="c++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    source = (root / "rpcs3/rpcs3.cpp").read_text()
    find_arg = extract(source, "int find_arg(", "\nQCoreApplication* create_application(")
    split = extract(source, "\tstd::span<char* const> argv_span", "\n\t// Only run RPCS3 to display an error")
    boot = extract(source, "\t\tu32 emu_argv_pos = 0;", "\n\t\tstd::string config_path;")
    normalize = extract(source, '\t\tif (!spath.starts_with("%RPCS3_"))', "\n\t\t// Postpone startup to main event loop")
    prefix_source = (root / "rpcs3/Emu/System.h").read_text()
    prefixes = "\n".join(line for line in prefix_source.splitlines()
                         if "static constexpr std::string_view" in line
                         and ("game_id_boot_prefix" in line or "vfs_boot_prefix" in line))
    if len(prefixes.splitlines()) != 2:
        raise RuntimeError("Cannot extract both special boot prefixes")

    fixture = r'''
#include <QCoreApplication>
#include <QCommandLineParser>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <span>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>
using usz = std::size_t;
using u32 = std::uint32_t;
template<class T, class U> T narrow(U value) { return static_cast<T>(value); }
template<class T> decltype(auto) at32(const T& container, std::size_t index)
{
    if (index >= static_cast<std::size_t>(container.size()))
        throw std::out_of_range("RPCS3 attempted to read an absent positional argument");
    return container[static_cast<qsizetype>(index)];
}
struct logger
{
    template<class... T> void notice(T...) {}
    template<class... T> void error(T...) {}
    template<class... T> void success(T...) {}
} sys_log;
struct Emulator { PREFIXES };
constexpr auto arg_emulation_barrier = "";
FIND_ARG
int main(int argc, char** argv)
{
    SPLIT
    int qt_argc = static_cast<int>(qt_argv.size());
    QCoreApplication app(qt_argc, const_cast<char**>(qt_argv.data()));
    QCommandLineParser parser;
    parser.addOption(QCommandLineOption("no-gui"));
    parser.process(app.arguments());
    const QStringList args = parser.positionalArguments();
    if (args.isEmpty() && emu_argv.empty())
    {
        std::cout << "{}";
        return 0;
    }
    BOOT
    NORMALIZE
    QJsonArray guest_args;
    for (const auto& arg : rpcs3_argv)
        guest_args.append(QString::fromStdString(arg));
    std::cout << QJsonDocument(QJsonObject{
        {"path", QString::fromStdString(spath)}, {"argv", guest_args}
    }).toJson(QJsonDocument::Compact).constData();
}
'''
    for token, content in (("PREFIXES", prefixes), ("FIND_ARG", find_arg),
                           ("SPLIT", split), ("BOOT", boot), ("NORMALIZE", normalize)):
        fixture = fixture.replace(token, content)

    with tempfile.TemporaryDirectory(prefix="rpcs3 cli boot test ") as directory:
        work = Path(directory)
        cpp = work / "fixture.cpp"
        executable = work / "fixture"
        cpp.write_text(fixture)
        flags = shlex.split(subprocess.check_output(
            ["pkg-config", "--cflags", "--libs", "Qt6Core"], text=True))
        subprocess.run([args.cxx, "-std=c++20", "-fPIC", "-Wall", "-Wextra", "-Werror",
                        str(cpp), "-o", str(executable), *flags], check=True, timeout=60)

        def check(argv, path=None, guest_args=()):
            result = subprocess.run([str(executable), *argv], cwd=work,
                                    capture_output=True, text=True, timeout=10)
            if result.returncode:
                raise AssertionError(f"CLI failed for {argv!r}: {result.stderr}")
            expected = {} if path is None else {"path": path, "argv": list(guest_args)}
            assert json.loads(result.stdout) == expected, (argv, result.stdout, expected)

        paths = ["/tmp/TEKKEN 6/USRDIR/EBOOT.BIN", "relative game/EBOOT.BIN",
                 'game "quotes" \'apostrophe\' $(no_shell); literal', "Tekken-č/游戏"]
        count = 0
        for path in paths:
            absolute = str(Path(path) if Path(path).is_absolute() else work / path)
            for argv in ([path], ["--", path], ["--no-gui", "--", path]):
                check(argv, absolute)
                count += 1
            for argv in ([path, "--", "--guest-option", "value with spaces"],
                         ["--", path, "--guest-option", "value with spaces"]):
                check(argv, absolute, ["", "", "--guest-option", "value with spaces"])
                count += 1

        check(["--", "--leading-dash"], str(work / "--leading-dash"))
        check(["game", "legacy-arg", "--", "guest-arg"], str(work / "game"),
              ["", "", "legacy-arg", "", "guest-arg"])
        check([])
        check(["--"])
        count += 4
        for path in ("%RPCS3_VFS%:/dev_hdd0/game/BLUS30359/USRDIR/EBOOT.BIN",
                     "%RPCS3_GAMEID%:BLUS30359"):
            for argv in ([path], ["--", path]):
                check(argv, path)
                count += 1
            check(["--", path, "guest-arg"], path, ["", "", "guest-arg"])
            count += 1
        print(f"PASS: {count} CLI boot cases using actual RPCS3 argument handling and QtCore")


if __name__ == "__main__":
    main()
