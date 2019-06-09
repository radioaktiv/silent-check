#!/home/christian/radioaktiv/technik/scripts/silent-check/env/bin/python

import argparse

parser = argparse.ArgumentParser(description='Receive information from liquidsoap scripts')
parser.add_argument(
        '--source',
        required=True,
        help='The name of the source',
        metavar='stream',
)

group = parser.add_mutually_exclusive_group(required=True)
group.add_argument(
        '--blank',
        action='store_false',
        help='Specify this flag if blank is detected',
        dest='noise',
)
group.add_argument(
        '--noise',
        action='store_true',
        help='Specify this flag if noise is detected',
        dest='noise',
)

parser.add_argument(
        '--min_noise',
        default=0.0,
        type=float,
        help='The value of min_noise of the on_blank function in seconds',
)
parser.add_argument(
        '--max_blank',
        default=20.0,
        type=float,
        help='The value of max_blank of the on_blank function in seconds',
)
parser.add_argument(
        '--threshold',
        default=-40.0,
        type=float,
        help='The value of threshold of the on_blank function in decibels',
)

args = parser.parse_args()

print(args)

from prometheus_client import Gauge, CollectorRegistry, push_to_gateway

registry = CollectorRegistry()

g = Gauge(
        'silent_check_stream_noise',
        'Result of liquidsoap stream blank detection',
        [
            'source',
            'min_noise',
            'max_blank',
            'threshold'
        ],
        registry=registry
        )
g.labels(source=args.source, min_noise=args.min_noise, max_blank=args.max_blank, threshold=args.threshold).set(args.noise)

push_to_gateway('localhost:9091', job='silent_checker', grouping_key={'source': args.source}, registry=registry)
