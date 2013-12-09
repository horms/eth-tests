#!/bin/sh
# link-speed-check.sh
#
# Simple ip-based test for network interface link speed
# 
# Copyright (C) 2013 Horms Soltutions Ltd.
#
# Contact: Simon Horman <horms@verge.net.au>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.


if [ $# -ne 2 ]; then
	echo "usage: $(basename $0) INTERFACE SPEED" >&2
	echo "    e.g.: $(basename $0) eth0 100h" >& 2
	exit 0
fi

# Check that the link is up
STATE=$($(dirname $0)/link-up.sh "$1")
if [ "$STATE" != "UP" ]; then
	echo "error link state of \'$0\' is \'$STATE\', expected UP" >&2
	exit 1
fi

eval $(ethtool eth0 | \
	sed -n	's/.*Speed: /SPEED=/; t 1;
		 s/.*Duplex: /DUPLEX=/; t 2;
		 b
		 : 1 s/Mb\/s//
		 : 2 p')

case $DUPLEX in
Full)	MODE="${SPEED}f" ;;
Half)	MODE="${SPEED}h" ;;
*)	echo "Unknown Duplex setting \'$DUPLEX\' for \'$1\'" >&2
	exit 1
	;;
esac

if [ "$MODE" != "$2" ]; then
	exit 1
fi
