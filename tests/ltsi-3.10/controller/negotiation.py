#!/usr/bin/python

# negotiation.py
#
# Simple test for network interface link negotiation between
# a swtich and a board
#
# Copyright (C) 2013 Horms Soltutions Ltd.
#
# Contact: Simon Horman <horms@verge.net.au>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.

import getopt
import itertools;
import os
import re
import select
import subprocess
import sys

all_modes = ['10h', '10f', '100h', '100f', '1000f']

interface_types = [ [ 'fast_ether', 4] , ['giga_ether', 5] ]

def possible_modes (type):
    for i in range(len(interface_types)):
        if type == interface_types[i][0]:
            count = interface_types[i][1]
            return all_modes[0:count]
    fatal_err("Unknown interface type \'%d\'" % type)

def max_mode (modes):
    for m in reversed(all_modes):
        if m in modes:
            return m
    fatal_err("max_mode: All modes are invalid")


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
   (out, err) = proc.communicate()
   err_stdio(msg, outdata + out, errdata + err)

def combinations(modes):
    l = [];
    for i in range(1, len(modes) + 1):
        l += list(itertools.combinations(modes, i))
    return l

class Test:
    def __init__(self, argv_0, sw_hostname, sw_username, sw_password,
                 sw_interface_name, board_hostname, board_username,
                 board_interface_name, board_interface_type, board_path):
        self.sw_hostname = sw_hostname
        self.sw_username = sw_username
        self.sw_password = sw_password
        self.sw_interface_name = sw_interface_name
        self.board_hostname = board_hostname
        self.board_username = board_username
        self.board_interface_name = board_interface_name
        self.board_interface_type = board_interface_type
        self.board_path = board_path

        self.board_modes = possible_modes(self.board_interface_type)
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
        info(info_str)
        try:
            retcode = subprocess.check_call(cmd)
            if retcode < 0:
                err(info_str)
                return False
        except OSError as e:
            print >>sys.stderr, "error: execution failed:", e
            return False
        except subprocess.CalledProcessError as e:
            print >>sys.stderr, "error: execution failed:", e
            return False

        return True

    def board_cmd_args(self, cmd):
        return ['ssh', self.board_hostname, '-l', self.board_username] + cmd

    def board_cmd(self, info_str, cmd):
        return self.local_cmd(info_str, self.board_cmd_args(cmd))

    def swtich_speed(self, info_str, desired_modes):
        cmd = [ self.dir + '/set-switch-negotiation', self.sw_hostname,
                self.sw_username, self.sw_password, self.sw_interface_name,
                'set' ] + desired_modes;
        return self.local_cmd(info_str, cmd)

    def check_board_speed(self, info_str, desired_mode):
        cmd = [ self.board_path + '/link-speed-check.sh',
                self.board_interface_name, desired_mode ]
        return self.board_cmd(info_str, cmd)

    def set_modes(self, info_str, desired_modes):
        i_str = '%s: setting switch negotiation parameters' % info_str
        retcode = self.swtich_speed(i_str, desired_modes)
        if not retcode:
            return retcode
        i_str = '%s: checking link speed on board' % info_str
        return self.check_board_speed(i_str, max_mode(desired_modes))

    def reset_modes(self):
        info_str = 'resetting negotiation parameters'
        return self.set_modes(info_str, self.board_modes)

    def start_link_monitor(self):
        info_msg = 'start monitoring link messages on board'
        cmd = [ 'ip', '--oneline', 'monitor', 'link' ]
        cmd = self.board_cmd_args(cmd)

        return self.start_cmd(info_msg, cmd)

    def collect_link_monitor(self, proc):
        info_str = "collecting monitor link messages from board"
        info(info_str)

        line = ""
        outdata = ""
        errdata = ""
        want_up = False

        while True:
            if proc.poll():
                err_proc(proc, info_str, outdata, '')
                return False
            fds = [proc.stdout, proc.stderr]
            try:
                (r, w, e) = select.select(fds, [], fds, 10)
                if e or w:
                    proc.kill()
                    err_proc(proc, info_str + ': select error', outdata, '')
                    return False
                if not r:
                    proc.kill()
                    err_proc(proc, info_str + ': select timeout', outdata, '')
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
                proc.kill()
                proc.wait()
                return True

            want_up = True
            line = ""

    def run_one(self, desired_modes):

        print "Testing: %s" % ' '.join(desired_modes)

        retcode = self.reset_modes()
        if not retcode:
            return retcode

        # Start monitoring link messages on board
        proc = self.start_link_monitor()
        if proc == None:
            return False

        # Set desired modes for switch speed
        info_str = 'setting negotiation parameters'
        retcode = self.set_modes(info_str, desired_modes)
        if not retcode:
            return retcode

        # Collect output from monitoring of link messages on board
        return self.collect_link_monitor(proc)

    def run(self):
        ok = 0
        ng = 0

        for m in combinations(self.board_modes):
            for i in range(7):
                retval = self.run_one(list(m))
                if retval:
                    break
                print "Retry"

            if retval:
                ok = ok + 1
            else:
                ng = ng + 1

        self.reset_modes()

        print "Test Complete: Passed=%d Faled=%d" % (ok, ng)

        if ng == 0:
            return True
        else:
            return False

def usage():
        fatal_err(
"Usage: negotiation.py [options] SWITCH_HOSTNAME SWTICH_USERNAME \\\n" +
"                      SWITCH_PASSWORD SWTICH_INTERFACE\\\n" +
"                      BOARD_HOSTNAME BOARD_USERNAME \\\n" +
"                      BOARD_INTERFACE BOARD_INTERFACE_TYPE \\\n" +
"                      BOARD_SCRIPT_PATH\n" +
"  where:\n" +
"    SWITCH_HOSTNAME:  Is the hostname of the swtich to connect to\n" +
"    SWITCH_USERNAME:  Is the username to use when when loging into the swtich\n" +
"    SWITCH_PASSWORD:  Is the password to use when when loging into the swtich\n" +
"    SWITCH_INTERFACE: Is the interface to change the settings of on the swtich\n" +
"\n"
"    BOARD_HOSTNAME:  Is the hostname of the board to connect to\n" +
"    BOARD_USERNAME:  Is the username to use when when loging into the board\n" +
"    BOARD_INTERFACE: Is the interface to test on the board\n" +
"    BOARD_INTERFACE_TYPE:\n"
"                     Is the type of the interface on the board.\n" +
"                     Either \'fast_ether\' or \'giga_ether\'\n" +
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
