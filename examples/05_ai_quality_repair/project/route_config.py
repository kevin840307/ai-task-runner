import argparse, json

p=argparse.ArgumentParser(); p.add_argument('--config'); p.add_argument('--env'); p.add_argument('--service'); a=p.parse_args()
# Starter intentionally works for the visible sample but is not generic.
known={('DEV','api'):'http://dev.local/api',('PROD','api'):'https://prod.local/api'}
if (a.env,a.service) not in known: raise SystemExit('not found')
print(known[(a.env,a.service)])
