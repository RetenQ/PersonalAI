"""Read-only HTTP tool example. Token is prompted, never passed in argv or URL."""
import argparse
import getpass
import json
from urllib.parse import urlsplit
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', required=True)
    parser.add_argument('--resource', choices=['tasks', 'goals', 'reports', 'logs', 'checkins', 'pending'], default='tasks')
    parser.add_argument('--day')
    args = parser.parse_args()
    origin = urlsplit(args.server)
    if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password or origin.path not in {'', '/'} or origin.query or origin.fragment:
        parser.error('Use an HTTPS root address without credentials.')
    token = getpass.getpass('Agent token (hidden): ')
    with httpx.Client(base_url=args.server.rstrip('/'), headers={'Authorization': 'Bearer ' + token},
                      timeout=30, follow_redirects=False, trust_env=False) as client:
        offset = 0
        while True:
            params = {'limit': 50, 'offset': offset}
            if args.day: params['day'] = args.day
            response = client.get('/api/clients/v1/resources/' + args.resource, params=params)
            if response.status_code != 200:
                raise SystemExit(f'Request failed ({response.status_code}); check credentials/scopes. No write was attempted.')
            result = response.json()
            print(json.dumps(result['items'], ensure_ascii=False, indent=2))
            offset = result['next_offset']
            if offset is None: break


if __name__ == '__main__': main()
