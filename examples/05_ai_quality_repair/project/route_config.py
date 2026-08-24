#!/usr/bin/env python3
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--env', required=True)
    parser.add_argument('--service', required=True)
    args = parser.parse_args()
    known = {
        ('DEV', 'api'): 'http://dev.local/api',
        ('PROD', 'api'): 'https://prod.local/api',
    }
    value = known.get((args.env, args.service))
    if value is None:
        return 1
    print(value)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
