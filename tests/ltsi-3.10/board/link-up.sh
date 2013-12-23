#!/bin/sh
# link-up.sh
#
# Simple ip-based test for network interface whose link is up
# 
# Copyright (C) 2013 Horms Solutions Ltd.
#
# Contact: Simon Horman <horms@verge.net.au>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.


if [ $# -lt 1 ]; then
	echo "usage: $(basename $0) INTERFACE" >&2
	echo "    e.g.: $(basename $0) eth0" >& 2
	exit 0
fi

# Wait up to 5 seconds, polling every 10th of a second
for i in $(seq 1 50); do
	STATE=$(ip --oneline link sh "$1"  | \
		sed -ns 's/.*state \([A-Z]\{1,\}\).*/\1/;T;p;q')
	if [ "$STATE" = "UP" ]; then
		echo "$STATE"
		exit 0
	fi
	sleep 0.1
done
echo "$STATE"
exit 1
