#!/usr/bin/python

# negotiation.py
#
# Simple test for network interface link negotiation between
# a swtich and a board
#
# Copyright (C) 2013 Horms Solutions Ltd.
#
# Contact: Simon Horman <horms@verge.net.au>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.

import errno
import getopt
import itertools;
import os
import re
import select
import subprocess
import sys
import time

all_modes = ['10h', '10f', '100h', '100f', '1000f']

interface_types = [ [ 'fast_ether', 4] , ['giga_ether', 5] ]

def possible_modes (type):
    for i in range(len(interface_types)):
        if type == interface_types[i][0]:
            count = interface_types[i][1]
            return all_modes[0:count]
    fatal_err("Unknown interface type \'%s\'" % type)

def max_mode (modes):
    for m in reversed(all_modes):
        if m in modes:
            return m
    fatal_err("max_mode: All modes are invalid")


def try_kill (proc):
    try:
        proc.kill()
    except OSError, e:
        if e.errno != errno.ESRCH:
            print >>sys.stderr, 'error: kill failed:', e
            return False

    return True

verbose = False

def info (str):
    if verbose:
        print str
    pass

def err (str):
    print >>sys.stderr, "error: %s" % str

def fatal_err (str):
    err(str)
    exit(1)

def err_stdio(msg, outdata, errdata):
    msg += '\nStdout:'
    if outdata:
        msg += '\n' + outdata.rstrip('\r\n') + '\n'
    msg += '\nStderr:'
    if errdata:
        msg += '\n' + errdata.rstrip('\r\n') + '\n'
    err(msg.rstrip('\r\n'))

def err_proc(proc, msg, outdata, errdata):
    try_kill(proc)

    fds = [proc.stdout, proc.stderr]
    while fds:
        try:
            (r, w, e) = select.select(fds, [], fds, 0.1)
            if not r:
                break;
        except select.error, e:
            print >>sys.stderr, 'error: select failed:', e
            break

        for fd in r:
            data = fd.read()
            if data == '': # EOF
                fds.remove(fd)
                continue

            if fd == proc.stdout:
                outdata += data
            elif fd == proc.stderr:
                errdata += data
            else:
                break

    err_stdio(msg, outdata, errdata)
    proc.wait()

def combinations(modes):
    l = [];
    for i in range(1, len(modes) + 1):
        l += list(itertools.combinations(modes, i))
    return l

class Test:
    def __init__(self, argv_0, test_type, sw_hostname, sw_username, sw_password,
                 sw_interface_name, board_hostname, board_username,
                 board_interface_name, board_path):
        self.test_type = test_type
        self.sw_hostname = sw_hostname
        self.sw_username = sw_username
        self.sw_password = sw_password
        self.sw_interface_name = sw_interface_name
        self.board_hostname = board_hostname
        self.board_username = board_username
        self.board_interface_name = board_interface_name
        self.board_path = board_path

        if self.test_type == "fast_ether" or self.test_type == "giga_ether":
            self.board_modes = possible_modes(self.test_type)

        self.dir = os.path.dirname(argv_0)

        base_match = "%s: .* state" % self.board_interface_name
        self.down_pattern = re.compile("%s %s" % (base_match, 'DOWN'))
        self.up_pattern = re.compile("%s %s" % (base_match, 'UP'))

    def start_cmd(self, info_msg, cmd):
        info(info_msg)

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)
        except OSError as e:
            print >>sys.stderr, 'error: ' + info_msg + ': execution failed:', e
            return None

        return proc

    def local_cmd(self, info_str, cmd):
        proc = self.start_cmd(info_str, cmd)
        if not proc:
            return False

        (outdata, errdata) = proc.communicate()
        if proc.returncode != 0:
            err_stdio(info_str, outdata, errdata)
            return False

        return True

    def board_cmd_args(self, cmd):
        return ['ssh', self.board_hostname, '-l', self.board_username] + cmd

    def board_cmd(self, info_str, cmd):
        return self.local_cmd(info_str, self.board_cmd_args(cmd))

    def swtich_shutdown(self, info_str, shutdown):
        cmd = [ self.dir + '/set-switch', self.sw_hostname,
                self.sw_username, self.sw_password, self.sw_interface_name,
                'set']
        if not shutdown:
            cmd += ['no']
        cmd += ['shutdown']

        return self.local_cmd(info_str, cmd)

    def swtich_speed(self, info_str, desired_modes):
        cmd = [ self.dir + '/set-switch', self.sw_hostname,
                self.sw_username, self.sw_password, self.sw_interface_name,
                'set', 'negotiation' ] + desired_modes;
        return self.local_cmd(info_str, cmd)

    def check_board_speed(self, info_str, desired_mode):
        cmd = [ self.board_path + '/link-speed-check.sh',
                self.board_interface_name, desired_mode ]
        return self.board_cmd(info_str, cmd)

    def set_modes(self, info_str, desired_modes):
        i_str = '%s: start monitoring link messages on board' % info_str
        proc = self.start_link_monitor(i_str)
        if proc == None:
            return False

        i_str = '%s: setting switch negotiation parameters' % info_str
        retcode = self.swtich_speed(i_str, desired_modes)
        if not retcode:
            return retcode

        i_str = ('%s: collect output from monitoring of link messages ' +
                 'on board') % info_str
        retcode = self.collect_link_monitor(proc, i_str)

        i_str = '%s: checking link speed on board' % info_str
        return self.check_board_speed(i_str, max_mode(desired_modes)) and retcode

    def reset_modes(self):
        info_str = 'resetting negotiation parameters'
        return self.set_modes(info_str, self.board_modes)

    def start_link_monitor(self, info_msg):
        cmd = [ 'ip', '--oneline', 'monitor', 'link' ]
        cmd = self.board_cmd_args(cmd)

        return self.start_cmd(info_msg, cmd)

    def collect_link_monitor(self, proc, info_str):
        info(info_str)

        line = ""
        outdata = ""
        errdata = ""
        want_up = False

        while True:
            if proc.poll():
                err_proc(proc, info_str, outdata, errdata)
                return False
            fds = [proc.stdout, proc.stderr]
            try:
                (r, w, e) = select.select(fds, [], fds, 20)
                if e or w:
                    err_proc(proc, info_str + ': select error', outdata, errdata)
                    return False
                if not r:
                    err_proc(proc, info_str + ': select timeout', outdata, errdata)
                    return False
            except select.error, e:
                print >>sys.stderr, 'error: select failed:', e
                return False

            fd = r[0]
            c = fd.read(1)
            if c == '': # EOF
                err_proc(proc, info_str + ': insufficient data read',
                         outdata, errdata)
                return False

            if fd == proc.stderr:
                errdata +=c
                continue

            outdata += c
            if c != '\n':
                line += c
                continue

            if want_up:
                pattern = self.up_pattern
            else:
                pattern = self.down_pattern

            if pattern.search(line) == None:
                continue

            if want_up:
                ret = True
                if not try_kill(proc):
                    ret = False
                proc.wait()
                return ret

            want_up = True
            line = ""

    def run_one_negotiate(self, desired_modes):

        print "Testing link negotiation: %s" % ' '.join(desired_modes)

        retcode = self.reset_modes()

        info_str = 'setting negotiation parameters'
        return self.set_modes(info_str, desired_modes) and retcode

    def run_negotiate(self):
        ok = 0
        ng = 0

        for m in combinations(self.board_modes):
            retval = self.run_one_negotiate(list(m))
            if retval:
                ok = ok + 1
            else:
                ng = ng + 1

        self.reset_modes()

        print "Test Complete: Passed=%d Failed=%d" % (ok, ng)

        if ng == 0:
            return True
        else:
            return False

    def run_shutdown__(self):
        # Make sure the link is up
        i_str = 'Setting no shutdown on switch'
        retcode = self.swtich_shutdown(i_str, False)
        if not retcode:
            return retcode

        i_str = 'Start monitoring link messages on board'
        proc = self.start_link_monitor(i_str)
        if proc == None:
            return False

        i_str = 'Setting shutdown on switch'
        retcode = self.swtich_shutdown(i_str, True)
        if not retcode:
            self.swtich_shutdown(i_str, False)
            return retcode

        # The monitor runs over ssh and thus probably isn't working
        # if the link is shutdown. So just sleep for a bit and
        # assume shutdown has taken effect
        time.sleep(1)

        i_str = 'Setting no shutdown on switch'
        retcode = self.swtich_shutdown(i_str, False)
        if not retcode:
            return retcode

        i_str = 'Collect output from monitoring of link messages on board'
        return self.collect_link_monitor(proc, i_str)

    def run_shutdown(self):

        print "Testing link shutdown"

        retcode = self.run_shutdown__()

        if retcode:
            ret_str = "Passed"
        else:
            ret_str = "Failed"

        print "Test Complete: %s" % (ret_str)
        return retcode

    def run(self):
            if self.test_type == "fast_ether" or self.test_type == "giga_ether":
                return self.run_negotiate()
            if self.test_type == "shutdown":
                return self.run_shutdown()

def usage():
        fatal_err(
"Usage: negotiation.py [options] TEST_TYPE \\\n" +
"                      SWITCH_HOSTNAME SWTICH_USERNAME \\\n" +
"                      SWITCH_PASSWORD SWTICH_INTERFACE\\\n" +
"                      BOARD_HOSTNAME BOARD_USERNAME \\\n" +
"                      BOARD_INTERFACE BOARD_SCRIPT_PATH\n" +
"  where:\n" +
"    TEST_TYPE:       Is the type of test to run:\n" +
"                     \'fast_ether\' for link negotiation of fast ethernet\n"
"                     \'giga_ether\' for link negotiation of gigabit ethernet\n"
"                     \'shutdown\' for link shutdown\n"
"\n"
"    SWITCH_HOSTNAME:  Is the hostname of the swtich to connect to\n" +
"    SWITCH_USERNAME:  Is the username to use when when loging into the swtich\n" +
"    SWITCH_PASSWORD:  Is the password to use when when loging into the swtich\n" +
"    SWITCH_INTERFACE: Is the interface to change the settings of on the swtich\n" +
"\n"
"    BOARD_HOSTNAME:  Is the hostname of the board to connect to\n" +
"    BOARD_USERNAME:  Is the username to use when when loging into the board\n" +
"    BOARD_INTERFACE: Is the interface to test on the board\n" +
"    BOARD_TEST_DIR:  Directory on board with test scripts\n" +
"\n" +
"  options:\n" +
"    -h: Dipslay this help message and exit\n" +
"    -v: Be versbose\n" +
"\n" +
"  e.g:\n" +
"    negotiation.py sw0 sw_user sw_pass gi1 \\\n" +
"       armadillo800eva root eth0 fast_ether /opt/eth-tests/ltsi-3.10/common\n" +
""
    )

if len(sys.argv) < 1:
    err("Too few arguments\n")
    usage()
try:
    opts, args = getopt.getopt(sys.argv[1:], "hv", [])
except getopt.GetoptError:
    err("Unknown arguments\n")
    usage()

if len(sys.argv) < 10:
    err("Too few arguments\n")
    usage()

for opt, arg in opts:
    if opt == '-h':
        usage();
    if opt == '-v':
        verbose = True

test = Test(sys.argv[0], *args)
retval = test.run()
if retval == False:
    exit(1)
