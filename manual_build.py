#!/usr/bin/python

import json
import sys
import subprocess

if len(sys.argv) < 3:
    print('Usage: %s repository branch' % sys.argv[0])
    print('e.g. %s front-end/quasar master' % sys.argv[0])
    sys.exit(1)

repo = sys.argv[1]
branch = sys.argv[2]

# A stripped-down version of the git web hook JSON. Only sends enough data for the githook to function.
req_json = {
    'repository': {
        'url': 'git@107.178.218.39:%s.git' % repo
    },
    'ref': 'refs/heads/%s' % branch,
    'reason': 'Build triggered manually' # 'reason' isn't necessary; I just put it here so it'll show up in the githook log.
}

# Yeah, you could use the requests module, but I'm lazy
subprocess.call(('curl', '-H', 'Content-Type: application/json', '-d', json.dumps(req_json), '-X', 'POST', '107.178.218.39:8000'))

